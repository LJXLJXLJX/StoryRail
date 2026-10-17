"""同一主流程贯穿授权、写入、工作集和人工交接。"""

import asyncio
from dataclasses import replace

import pytest
from conftest import make_service, provider_registry
from structured_director_fixtures import RecordingProvider
from test_external_reference_proposals import PROPOSAL, command, empty_project
from test_external_script_proposals import agent, confirm_references, http, mixed_proposal
from video_recipes import (
    SegmentVideoGenerationMode,
    SegmentVideoVideoReference,
    recipe_id,
    replace_video,
    save_video_inputs,
)

from core.director_commands import DirectorCommand
from core.director_proposals.reference_library_codec import parse_reference_library_proposal
from core.structured_director.reads.read_tools import execute_project_read
from core.structured_director.reads.workflow_state import references_reviewed


def test_initial_stage_cannot_be_skipped_and_review_is_human_only(tmp_path):
    async def run():
        store, service = await empty_project(tmp_path)
        initial = store.read()
        caller = replace(
            agent(initial, command("request", initial.revision, "unused")),
            grants=(),
            capabilities=frozenset(
                {"project.read", "project.execute", "project.mutate", "project.propose"}
            ),
        )
        before = store.path.read_bytes()
        for name, arguments in [
            ("script.request_proposal", {"raw_user_instruction": "推进"}),
            ("keyframe.apply_operations", {}),
        ]:
            response = await http(
                service, caller, DirectorCommand(name, initial.revision, name, arguments)
            )
            assert response.status == 409, response.body
            assert response.body["error"]["code"] == "stage_prerequisite_not_met"
            assert response.body["error"]["current_stage"] == "reference_library"
            assert store.path.read_bytes() == before
        workset = execute_project_read(
            initial,
            "project.get_workset",
            {"capability": "script", "scope": {"project_id": initial.project_id}},
        )
        assert workset["not_current_stage"] and workset["mutation_blocked"]
        assert workset["workflow"]["required_next_actions"][0]["action"] == (
            "reference.request_proposal"
        )
        requested = await http(
            service,
            caller,
            command("request", initial.revision, "reference", raw_user_instruction="整理角色"),
        )
        saved = await http(
            service,
            caller,
            command(
                "submit",
                store.read().revision,
                "save",
                request_id=requested.body["data"]["request_id"],
                proposal=PROPOSAL,
            ),
        )
        assert saved.status == 200, saved.body
        review = DirectorCommand("reference.confirm_review", store.read().revision, "review", {})
        assert (await http(service, caller, review)).status == 403
        pending = await http(
            service,
            caller,
            DirectorCommand(
                "script.request_proposal",
                store.read().revision,
                "early-script",
                {"raw_user_instruction": "继续"},
            ),
        )
        assert pending.status == 409
        await confirm_references(store, service)
        assert references_reviewed(store.read())
        handoff = execute_project_read(store.read(), "project.get_workflow_state", {})
        assert handoff["workflow"]["required_next_actions"][0]["action"] == (
            "script.request_proposal"
        )
        doc = store.read()
        assert (
            execute_project_read(doc, "project.get_handoff", {})["workflow"][
                "required_next_actions"
            ][0]["action"]
            == "script.request_proposal"
        )
        card = doc.reference_library.characters[0]
        await service.update_character(
            replace(card, name="更新名字"), expected_revision=doc.revision
        )
        assert not references_reviewed(store.read())
        await confirm_references(store, service)
        request = DirectorCommand(
            "script.request_proposal",
            store.read().revision,
            "script",
            {"raw_user_instruction": "生成脚本"},
        )
        assert (await http(service, caller, request)).status == 200

    asyncio.run(run())


def test_voice_only_identity_roundtrip_dialogue_and_visibility(tmp_path):
    import json

    from core.director_proposals.script_codec import parse_structured_director_script_proposal

    async def run():
        store, service = await empty_project(tmp_path)
        payload = {
            "characters": [
                {
                    "name": "广播",
                    "visual_description": None,
                    "voice_description": "稳定低沉的电台声音",
                    "looks": [],
                }
            ],
            "narrator": None,
        }
        proposal = parse_reference_library_proposal(json.dumps(payload))
        store.begin_reference_proposal()
        doc = store.apply_reference_proposal(proposal)
        voice = store.read().reference_library.characters[0]
        assert voice.visual_description is None and doc.reference_library.narrator is None
        with pytest.raises(ValueError, match="voice_identity"):
            replace(voice, voice_description="")
        await confirm_references(store, service)
        store.begin_script_proposal(expected_revision=store.read().revision)
        script = mixed_proposal(voice.id)
        with pytest.raises(ValueError, match="非出镜"):
            store.apply_script_proposal(
                parse_structured_director_script_proposal(json.dumps(script))
            )
        script["scenes"][0]["shots"][0]["visible_character_ids"] = []
        script["scenes"][0]["segments"][0]["dialogue_lines"] = [
            {"character_id": voice.id, "text": "请保持安静。", "delivery": "广播"}
        ]
        doc = store.apply_script_proposal(
            parse_structured_director_script_proposal(json.dumps(script))
        )
        assert doc.director_script.scenes[0].segments[0].dialogue_lines[0].character_id == voice.id
        assert store.read().reference_library.characters[0] == voice

    asyncio.run(run())


def test_confirmed_timing_advances_to_unlock_not_repeated_review(tmp_path):
    from test_director_commands import _location_project

    from core.structured_director.reads.workflow_state import workflow_state

    store, _, document, _ = asyncio.run(_location_project(str(tmp_path)))
    assert (
        document.director_script.production_baseline_revision == document.director_script.revision
    )
    assert workflow_state(store.read())["required_next_actions"][0]["action"] == (
        "visual_production.unlock"
    )


def test_empty_visual_cards_request_planning_without_fake_candidate_selection(tmp_path):
    from test_director_commands import _visual_project

    from core.structured_director.reads.workflow_state import workflow_state

    store, _, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    assert not document.generations
    state = workflow_state(store.read())
    assert state["current_stage"] == "keyframe"
    assert state["stage_status"] == "awaiting_plan"
    assert [item["action"] for item in state["required_next_actions"]] == [
        "keyframe.request_proposal"
    ]
    assert all(item["action"] != "candidate_selection" for item in state["required_next_actions"])


def test_script_edit_after_unlock_rebuilds_production_baseline(tmp_path):
    from test_director_commands import _visual_project

    from core.structured_director.reads.workflow_state import workflow_state

    async def edit_after_unlock():
        _, service, document, _ = await _visual_project(str(tmp_path))
        assert document.director_script is not None
        scene = document.director_script.scenes[0]
        return await service.save_script(
            (replace(scene, summary=scene.summary + "（修订）"),),
            expected_revision=document.revision,
        )

    edited = asyncio.run(edit_after_unlock())
    # Core 在同一次脚本写入里重建生产基线，不退回旁白阶段等待人工确认时序。
    assert edited.director_script.production_baseline_revision == edited.director_script.revision
    assert edited.director_script.production_baseline_scenes == edited.director_script.scenes
    state = workflow_state(edited)
    assert state["current_stage"] != "narration"
    assert all(
        not item["action"].startswith("narration.") for item in state["required_next_actions"]
    )


def test_primary_workflow_parallel_generation_and_unlocked_capabilities_are_orthogonal(tmp_path):
    from test_architecture_acceptance import mixed_acceptance

    from core.structured_director.models import (
        ReferenceGenerationKind,
        ReferenceGenerationPhase,
        StructuredDirectorStatus,
    )
    from core.structured_director.reads.workflow_state import workflow_state

    async def run():
        completed = await mixed_acceptance(tmp_path)
        source = next(
            generation
            for generation in completed.generations
            if generation.kind is ReferenceGenerationKind.SEGMENT_VIDEO
        )
        running = replace(
            source,
            id="f" * 32,
            phase=ReferenceGenerationPhase.RUNNING,
            progress=0.5,
            message="Provider 处理中",
            external_id="parallel-video",
            output_asset_id=None,
            error_code=None,
            retry_of=None,
            dismissed=False,
        )
        document = replace(
            completed,
            status=StructuredDirectorStatus.REVIEWING_FINAL,
            final_approval=None,
            generations=(*completed.generations, running),
            application_requests=tuple(
                request
                for request in completed.application_requests
                if request.operation != "reference.confirm_review"
            ),
        )
        state = workflow_state(document)
        assert state["current_stage"] == "reference_library"
        assert state["stage_status"] == "awaiting_human_review"
        assert state["active_task"] is None
        assert state["semantics"] == {
            "current_stage": "primary_workflow_focus_not_capability_lock",
            "active_task": "primary_workflow_task_only_parallel_activity_uses_task_discovery",
            "required_next_actions": "primary_workflow_actions_only",
        }
        assert state["workspace_capabilities"]["unlocked"] == [
            "narration",
            "keyframe",
            "video",
            "final",
        ]
        assert state["activity_summary"] == {
            "active_generation_count": 1,
            "has_active_generations": True,
            "task_discovery_tool": "read_workflow",
            "semantics": "parallel_project_activity_not_primary_workflow",
        }

        handoff = execute_project_read(document, "project.get_handoff", {})
        assert handoff["revision"] == document.revision
        assert handoff["workflow"] == state
        discovery = handoff["task_discovery"]
        assert discovery["observation_revision"] == document.revision
        assert discovery["semantics"]["workflow_relation"] == (
            "parallel_activity_not_primary_workflow"
        )
        assert any(item["id"] == running.id for item in discovery["active"])

        scene = document.director_script.scenes[0]
        keyframe_workset = execute_project_read(
            document,
            "project.get_workset",
            {
                "capability": "keyframe",
                "scope": {"scene_ids": [scene.id]},
                "target_ids": [scene.shots[0].id],
            },
        )
        video_prompt_workset = execute_project_read(
            document,
            "project.get_workset",
            {
                "capability": "video_prompt",
                "scope": {"scene_ids": [scene.id]},
                "target_ids": [source.target_id],
            },
            provider_recipes=provider_registry(
                fl2va_provider=RecordingProvider(media_type="video/mp4", content=b"fixture")
            ).recipe_views(),
            provider_catalog=provider_registry(
                fl2va_provider=RecordingProvider(media_type="video/mp4", content=b"fixture")
            ),
        )
        for workset in (keyframe_workset, video_prompt_workset):
            assert workset["workflow"] == state
            assert workset["observation_revision"] == document.revision
            assert workset["not_current_stage"]
            assert workset["not_current_stage_semantics"] == (
                "informational_primary_workflow_relevance_only"
            )
            assert not workset["mutation_blocked"]
            assert workset["mutation_blocked_reason"] is None

    asyncio.run(run())


def test_visual_workflow_uses_current_inputs_generations_and_reviewable_candidates(tmp_path):
    from structured_director_fixtures import (
        RecordingProvider,
        RecordingScriptProposer,
        SingleKeyframePlanner,
    )
    from test_director_commands import _visual_project

    from core.model_providers.boundary import GenerationPhase
    from core.structured_director import StructuredDirectorStore
    from core.structured_director.reads.workflow_state import workflow_state

    async def run():
        store, planner_service, document, _ = await _visual_project(
            str(tmp_path),
            script_proposer=RecordingScriptProposer(),
            keyframe_planner=SingleKeyframePlanner(),
        )
        document = await planner_service.prepare_keyframes(expected_revision=document.revision)
        image = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nframe")
        video = RecordingProvider(
            media_type="video/mp4",
            content=b"\x00\x00\x00\x18ftypmp42video",
            duration_seconds=6,
        )
        final = RecordingProvider(
            media_type="video/mp4",
            content=b"\x00\x00\x00\x18ftypmp42final",
            duration_seconds=6,
        )
        core = make_service(
            StructuredDirectorStore(store.path.parent, document.project_id),
            image_provider=image,
            fl2va_provider=video,
            ref2va_provider=video,
            final_assembly_provider=final,
        )
        for index, frame in enumerate(document.keyframe_plan.keyframes):
            image.content = b"\x89PNG\r\n\x1a\nframe" + bytes([index])
            document = await core.generate_keyframe(
                keyframe_id=frame.id, expected_revision=document.revision
            )
            queued = workflow_state(document)
            assert any(
                item["action"] == "generation.wait"
                and document.generations[-1].id in item["generation_ids"]
                for item in queued["required_next_actions"]
            )
            image.observations = [GenerationPhase.SUCCEEDED]
            document = await core._generation_observer.refresh_generation(
                document.generations[-1].id
            )
            candidate = workflow_state(document)["required_next_actions"]
            selection = next(
                item
                for item in candidate
                if item["action"] == "candidate_selection" and item["kind"] == "keyframe_image"
            )
            assert selection["candidate_count"] >= 1 and selection["human_only"]
            document = await core.select_keyframe(
                keyframe_id=frame.id,
                asset_id=document.generations[-1].output_asset_id,
                expected_revision=document.revision,
            )

        segment_id = document.video_plan.segments[0].segment_id
        document = await save_video_inputs(
            core,
            segment_id=segment_id,
            prompt_text="固定机位，人物轻声询问。",
            expected_revision=document.revision,
        )
        ref2va_ready = workflow_state(document)
        assert next(
            item
            for item in ref2va_ready["required_next_actions"]
            if item["action"] == "video.generate"
        )["target_ids"] == [segment_id]
        document = await core.save_segment_video_recipe(
            segment_id=segment_id,
            recipe_id=recipe_id(SegmentVideoGenerationMode.FL2VA),
            expected_revision=document.revision,
        )
        ready = workflow_state(document)
        assert next(
            item for item in ready["required_next_actions"] if item["action"] == "video.generate"
        )["target_ids"] == [segment_id]

        video_generation_ids = []
        for index in range(3):
            video.content = b"\x00\x00\x00\x18ftypmp42video" + bytes([index])
            document = await core._media.generate_segment_video(
                segment_id=segment_id, expected_revision=document.revision
            )
            video_generation_ids.append(document.generations[-1].id)
            waiting = workflow_state(document)
            assert any(
                item["action"] == "generation.wait" for item in waiting["required_next_actions"]
            )
            video.observations = [GenerationPhase.SUCCEEDED]
            document = await core._generation_observer.refresh_generation(
                document.generations[-1].id
            )
        state = workflow_state(document)
        selection = next(
            item
            for item in state["required_next_actions"]
            if item["action"] == "candidate_selection"
        )
        assert selection == {
            "action": "candidate_selection",
            "tool": None,
            "target_ids": [segment_id],
            "human_only": True,
            "requires_explicit_user_request": False,
            "web_path": f"/?project={document.project_id}",
            "kind": "segment_video",
            "candidate_count": 3,
            "candidate_count_unit": "generation_outputs",
            "verification_tool": "list_candidates",
        }
        candidates = execute_project_read(
            document,
            "project.list_candidates",
            {
                "kind": "segment_video",
                "target_ids": [segment_id],
                "phases": ["succeeded"],
            },
        )
        assert len(candidates["items"]) == 3
        assert all(item["reviewable"] for item in candidates["items"])

        for generation_id in video_generation_ids:
            document = await core.dismiss_generation(
                generation_id, expected_revision=document.revision
            )
        after_dismiss = workflow_state(document)["required_next_actions"]
        assert all(item["action"] != "candidate_selection" for item in after_dismiss)
        assert any(item["action"] == "video.generate" for item in after_dismiss)
        video.content = b"\x00\x00\x00\x18ftypmp42replacement"
        document = await core._media.generate_segment_video(
            segment_id=segment_id, expected_revision=document.revision
        )
        video.observations = [GenerationPhase.SUCCEEDED]
        document = await core._generation_observer.refresh_generation(document.generations[-1].id)
        chosen = document.generations[-1]
        document = await core.select_segment_video(
            segment_id=segment_id,
            asset_id=chosen.output_asset_id,
            expected_revision=document.revision,
        )
        state = workflow_state(document)
        # 最终成片只拼接 Scene 成片：缺少成片时工作流先要求逐 Scene 装配。
        assert state["required_next_actions"][-1]["action"] == "final.resolve_inputs"
        scene_ids = [
            item["target_ids"][0]
            for item in state["required_next_actions"]
            if item["action"] == "final.assemble_scene"
        ]
        assert scene_ids == [scene.id for scene in document.director_script.scenes]
        for scene_id in scene_ids:
            document = await core.generate_scene_final_video(
                scene_id=scene_id, expected_revision=document.revision
            )
            for generation_id in [item.id for item in document.generations[-2:]]:
                final.observations = [GenerationPhase.SUCCEEDED]
                document = await core._generation_observer.refresh_generation(generation_id)
        state = workflow_state(document)
        assert [item["action"] for item in state["required_next_actions"]] == ["final.assemble"]
        document = await core.generate_final_video(expected_revision=document.revision)
        assert workflow_state(document)["required_next_actions"][0]["action"] == ("generation.wait")
        final_generations = [item.id for item in document.generations[-2:]]
        for generation_id in final_generations:
            final.observations = [GenerationPhase.SUCCEEDED]
            document = await core._generation_observer.refresh_generation(generation_id)
        final_selection = workflow_state(document)["required_next_actions"][0]
        assert final_selection["action"] == "candidate_selection"
        assert final_selection["kind"] == "final_video"
        document = await core.select_final_video(
            generation_id=final_generations[0], expected_revision=document.revision
        )
        # 只选了一种语言时仍在候选选择，不能进入 Approval。
        assert workflow_state(document)["required_next_actions"][0]["action"] == (
            "candidate_selection"
        )
        document = await core.select_final_video(
            generation_id=final_generations[1], expected_revision=document.revision
        )
        approval = workflow_state(document)["required_next_actions"][0]
        assert approval["action"] == "final.approve" and approval["human_only"]

    asyncio.run(run())


def test_input_changed_segment_video_candidate_stays_selectable_with_soft_hint(tmp_path):
    """输入快照变化只是软提示：旧候选仍可选择、可被装配使用。"""

    from structured_director_fixtures import (
        RecordingProvider,
        RecordingScriptProposer,
        SingleKeyframePlanner,
    )
    from test_director_commands import _visual_project

    from core.model_providers.boundary import GenerationPhase
    from core.structured_director import StructuredDirectorHttpApi, StructuredDirectorStore
    from core.structured_director.video_inputs import effective_video

    async def run():
        store, planner_service, document, _ = await _visual_project(
            str(tmp_path),
            script_proposer=RecordingScriptProposer(),
            keyframe_planner=SingleKeyframePlanner(),
        )
        document = await planner_service.prepare_keyframes(expected_revision=document.revision)
        image = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nframe")
        video = RecordingProvider(
            media_type="video/mp4",
            content=b"\x00\x00\x00\x18ftypmp42video",
            duration_seconds=6,
        )
        core = make_service(
            StructuredDirectorStore(store.path.parent, document.project_id),
            image_provider=image,
            fl2va_provider=video,
            ref2va_provider=video,
        )
        for index, frame in enumerate(document.keyframe_plan.keyframes):
            image.content = b"\x89PNG\r\n\x1a\nframe" + bytes([index])
            document = await core.generate_keyframe(
                keyframe_id=frame.id, expected_revision=document.revision
            )
            image.observations = [GenerationPhase.SUCCEEDED]
            document = await core._generation_observer.refresh_generation(
                document.generations[-1].id
            )
            document = await core.select_keyframe(
                keyframe_id=frame.id,
                asset_id=document.generations[-1].output_asset_id,
                expected_revision=document.revision,
            )
        segment_id = document.video_plan.segments[0].segment_id
        document = await save_video_inputs(
            core,
            segment_id=segment_id,
            prompt_text="固定机位，人物轻声询问。",
            expected_revision=document.revision,
        )
        document = await core.save_segment_video_recipe(
            segment_id=segment_id,
            recipe_id=recipe_id(SegmentVideoGenerationMode.FL2VA),
            expected_revision=document.revision,
        )
        document = await core._media.generate_segment_video(
            segment_id=segment_id, expected_revision=document.revision
        )
        video.observations = [GenerationPhase.SUCCEEDED]
        document = await core._generation_observer.refresh_generation(document.generations[-1].id)
        generation = document.generations[-1]
        asset_id = generation.output_asset_id
        api = StructuredDirectorHttpApi(core, resource_path="/structured-director")

        def candidate(body):
            return next(item for item in body["generations"] if item["id"] == generation.id)

        fresh = await api.handle("GET", "/structured-director")
        assert candidate(fresh.body)["inputs_outdated"] is False

        # 保存新提示词让旧候选的输入快照过期：选择入口必须保留，只加软提示。
        document = await save_video_inputs(
            core,
            segment_id=segment_id,
            prompt_text="改换运镜后重新生成。",
            expected_revision=document.revision,
        )
        stale = await api.handle("GET", "/structured-director")
        outdated = candidate(stale.body)
        assert outdated["inputs_outdated"] is True
        assert outdated["allowed_actions"] == ["select_segment_video", "dismiss_history"]
        document = await core.select_segment_video(
            segment_id=segment_id,
            asset_id=asset_id,
            expected_revision=document.revision,
        )
        selected = next(
            item for item in document.video_plan.segments if item.segment_id == segment_id
        )
        assert selected.selected_asset_id == asset_id
        # 装配读取用户的选择，不因输入变化再次拒绝。
        assert effective_video(document, segment_id) == asset_id

    asyncio.run(run())


def test_video_reference_gate_checks_mp4_duration_window(tmp_path):
    import struct

    from structured_director_fixtures import (
        RecordingProvider,
        RecordingScriptProposer,
        SingleKeyframePlanner,
    )
    from test_director_commands import _visual_project

    from core.model_providers.boundary import GenerationPhase
    from core.structured_director import StructuredDirectorStore

    def mp4(duration_seconds: float) -> bytes:
        def box(kind: bytes, payload: bytes) -> bytes:
            return struct.pack(">I4s", len(payload) + 8, kind) + payload

        mvhd = box(
            b"mvhd",
            b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, 1_000, int(duration_seconds * 1_000)),
        )
        return box(b"ftyp", b"isom\x00\x00\x02\x00isom") + box(b"moov", mvhd)

    async def run():
        store, planner_service, document, _ = await _visual_project(
            str(tmp_path),
            script_proposer=RecordingScriptProposer(),
            keyframe_planner=SingleKeyframePlanner(),
        )
        document = await planner_service.prepare_keyframes(expected_revision=document.revision)
        image = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nframe")
        core = make_service(
            StructuredDirectorStore(store.path.parent, document.project_id),
            image_provider=image,
            ref2va_provider=RecordingProvider(media_type="video/mp4", content=b"fixture"),
        )
        for index, frame in enumerate(document.keyframe_plan.keyframes):
            image.content = b"\x89PNG\r\n\x1a\nframe" + bytes([index])
            document = await core.generate_keyframe(
                keyframe_id=frame.id, expected_revision=document.revision
            )
            image.observations = [GenerationPhase.SUCCEEDED]
            document = await core._generation_observer.refresh_generation(
                document.generations[-1].id
            )
            document = await core.select_keyframe(
                keyframe_id=frame.id,
                asset_id=document.generations[-1].output_asset_id,
                expected_revision=document.revision,
            )
        segment_id = document.video_plan.segments[0].segment_id
        document = await core.import_media_asset(
            media_type="video/mp4",
            content=mp4(20.0),
            expected_revision=document.revision,
        )
        too_long = document.assets[-1].id
        with pytest.raises(ValueError, match="参考视频必须是 2 到 15 秒"):
            await save_video_inputs(
                core,
                segment_id=segment_id,
                prompt_text="固定机位，人物轻声询问。",
                additional_image_references=(),
                audio_references=(),
                video_references=(SegmentVideoVideoReference(too_long, "超出时长上限。"),),
                expected_revision=document.revision,
            )
        video = document.video_plan.segments[0]
        document = replace(
            document,
            video_plan=replace(
                document.video_plan,
                segments=(
                    replace_video(
                        video,
                        prompt_text="固定机位，人物轻声询问。",
                        video_references=(SegmentVideoVideoReference(too_long, "超出时长上限。"),),
                    ),
                    *document.video_plan.segments[1:],
                ),
            ),
        )
        blocked = execute_project_read(
            document,
            "project.get_dependencies",
            {"action": "video.generate", "target_ids": [segment_id]},
            provider_catalog=core._registry,
        )
        assert blocked["ready_target_ids"] == []
        assert blocked["blocked_target_ids"] == [segment_id]
        assert "参考视频必须是 2 到 15 秒。" in blocked["items"][0]["reasons"]

        document = store.read()
        document = await core.import_media_asset(
            media_type="video/mp4",
            content=mp4(3.0),
            expected_revision=document.revision,
        )
        valid = document.assets[-1].id
        document = await save_video_inputs(
            core,
            segment_id=segment_id,
            prompt_text="固定机位，人物轻声询问。",
            additional_image_references=(),
            audio_references=(),
            video_references=(SegmentVideoVideoReference(valid, "参考运镜与节奏。"),),
            expected_revision=document.revision,
        )
        ready = execute_project_read(
            document,
            "project.get_dependencies",
            {"action": "video.generate", "target_ids": [segment_id]},
            provider_catalog=core._registry,
        )
        assert ready["ready_target_ids"] == [segment_id]
        assert ready["items"][0]["reasons"] == []

    asyncio.run(run())


def test_location_recommendations_follow_bindings_and_stay_optional(tmp_path):
    """地点推荐动作的出现/消失条件；永不进 required，推荐工具真实存在。"""

    from test_director_commands import _location_project
    from test_external_production import assert_workflow_tools_exist

    from core.director_commands import parse_location_operations_patch
    from core.structured_director.reads.workflow_state import workflow_state

    store, service, document, _ = asyncio.run(_location_project(str(tmp_path)))
    script = document.director_script
    first, second = script.scenes
    # 解开一个 Scene 的地点绑定与一个 Shot 的视图绑定。
    patch = parse_location_operations_patch(
        {
            "scope": {
                "location_ids": [],
                "scene_ids": [second.id],
                "shot_ids": [first.shots[0].id],
            },
            "operations": [
                {
                    "op": "bind_scene",
                    "scene_id": second.id,
                    "location_id": None,
                    "state_id": None,
                },
                {"op": "bind_shot", "shot_id": first.shots[0].id, "view_id": None},
            ],
        }
    )
    document, _receipt, _data = store.apply_location_operations(
        patch, expected_revision=document.revision, command_id="unbind"
    )
    state = workflow_state(store.read())
    # required 不受影响：仍是解锁视觉生产。
    assert [item["action"] for item in state["required_next_actions"]] == [
        "visual_production.unlock"
    ]
    recommended = state["recommended_next_actions"]
    planning = next(item for item in recommended if item["action"] == "location.request_proposal")
    assert planning["tool"] == "submit_proposal"
    assert planning["tool_action"] == "request"
    assert planning["capability"] == "location"
    assert planning["requires_explicit_user_request"]
    # 推荐只带数量；完整 ID 列表只在 unlock 影响预览的 location_advisory 里。
    assert planning["unbound_scene_count"] == 1
    assert planning["shots_without_view_count"] == 1
    assert "unbound_scene_ids" not in planning
    assert "shot_ids_without_view" not in planning
    assert "1 个 Scene 尚未绑定地点" in planning["message"]
    assert "1 个 Shot 尚未绑定机位视图" in planning["message"]
    assert "背景一致性" in planning["message"] and "可选" in planning["message"]
    # 主图未选定：同时推荐成套生成。
    assert any(item["action"] == "location.generate_set" for item in recommended)
    assert all(
        not item["action"].startswith("location.") for item in state["required_next_actions"]
    )
    assert_workflow_tools_exist(state)

    # 引用库确认记录缺失时推荐消失。
    unreviewed = replace(
        document,
        application_requests=tuple(
            record
            for record in document.application_requests
            if record.operation != "reference.confirm_review"
        ),
    )
    assert workflow_state(unreviewed)["recommended_next_actions"] == []

    # D6：解锁本身就是跳过；解锁后不再推荐规划与成套生成（此时主图仍未选定）。
    unlocked = asyncio.run(
        service.unlock_visual_production(expected_revision=store.read().revision)
    )
    assert workflow_state(unlocked)["recommended_next_actions"] == []


def test_location_recommendations_wait_for_production_baseline(tmp_path):
    """生产基线失效（旁白已选、Shot 未规划）时不推荐地点动作。"""

    from test_scene_driver_invariants import narration_project, select_audio

    from core.structured_director.reads.workflow_state import workflow_state

    async def run():
        directory = tmp_path / "narration"
        directory.mkdir()
        _, service, _, document = await narration_project(directory)
        stale = await select_audio(service, document)
        script = stale.director_script
        assert script.production_baseline_revision != script.revision
        state = workflow_state(stale)
        assert state["current_stage"] == "narration"
        assert state["recommended_next_actions"] == []

    asyncio.run(run())


def test_location_recommendations_cover_generation_and_disappear_when_complete(tmp_path):
    """绑定齐全但图片未选齐时推荐成套生成；主图与视图全部选定后推荐消失。"""

    from structured_director_fixtures import add_image_asset
    from test_director_commands import _location_project
    from test_external_production import assert_workflow_tools_exist

    from core.director_commands import LocationMasterSelection, LocationViewSelection
    from core.structured_director.models import ReferenceGenerationKind
    from core.structured_director.reads.workflow_state import workflow_state
    from scripts.harness.fixtures.candidates import register_image_candidate

    store, _, document, _ = asyncio.run(_location_project(str(tmp_path)))
    state = workflow_state(store.read())
    assert state["required_next_actions"][0]["action"] == "visual_production.unlock"
    recommended = state["recommended_next_actions"]
    # Scene/Shot 绑定已由 _location_project 完成：不再推荐规划。
    assert not any(item["action"] == "location.request_proposal" for item in recommended)
    # 主图未选定：推荐成套生成，范围 = 未选齐的地点。
    generate = next(item for item in recommended if item["action"] == "location.generate_set")
    assert generate["tool"] == "media_batch"
    assert generate["tool_action"] == "start"
    assert generate["kind"] == "location"
    assert generate["requires_explicit_user_request"]
    assert set(generate["target_ids"]) == {
        location.id for location in document.location_library.locations
    }
    assert_workflow_tools_exist(state)

    for location in store.read().location_library.locations:
        asset_id = add_image_asset(store)
        register_image_candidate(
            store,
            kind=ReferenceGenerationKind.LOCATION_MASTER_IMAGE,
            target_id=location.id,
            asset_id=asset_id,
        )
        store.select_location_master(
            LocationMasterSelection(location.id, asset_id),
            expected_revision=store.read().revision,
            command_id=f"select-master-{location.id[:8]}",
        )
    # 主图选定使此前选定的视图失效；重新选择后地点成套完成。
    for location in store.read().location_library.locations:
        for view in location.views:
            if view.selected_asset_id is not None:
                continue
            asset_id = add_image_asset(store)
            register_image_candidate(
                store,
                kind=ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
                target_id=view.id,
                asset_id=asset_id,
            )
            store.select_location_view(
                LocationViewSelection(view.id, asset_id),
                expected_revision=store.read().revision,
                command_id=f"select-view-{view.id[:8]}",
            )
    assert workflow_state(store.read())["recommended_next_actions"] == []


def test_unlock_impact_preview_lists_unbound_scenes_and_shots(tmp_path):
    """visual_production.unlock 的影响预览列出未绑定地点的 Scene 与未绑定视图的 Shot。"""

    from test_director_commands import _location_project, _visual_project

    from core.director_commands import (
        DirectorCommand,
        DirectorCommandRegistry,
        parse_location_operations_patch,
    )
    from core.structured_director.reads.impact import preview_command_impact

    # 已绑定 Scene 但 Shot 未绑定视图：预览分开列出两类缺口。
    unbound = tmp_path / "unbound"
    unbound.mkdir()
    store, _, document, _ = asyncio.run(_visual_project(str(unbound)))
    scene = document.director_script.scenes[0]
    patch = parse_location_operations_patch(
        {
            "scope": {"location_ids": [], "scene_ids": [scene.id], "shot_ids": []},
            "operations": [
                {
                    "op": "create_location",
                    "key": "roof",
                    "name": "天台",
                    "kind": "exterior",
                    "description": "空旷天台。",
                },
                {
                    "op": "bind_scene",
                    "scene_id": scene.id,
                    "location_id": "roof",
                    "state_id": None,
                },
            ],
        }
    )
    document, _receipt, _data = store.apply_location_operations(
        patch, expected_revision=document.revision, command_id="bind-scene-only"
    )
    command = DirectorCommand("visual_production.unlock", document.revision, "preview", {})
    preview = preview_command_impact(document, command)
    assert preview["command_name"] == "visual_production.unlock"
    advisory = preview["location_advisory"]
    assert advisory["scenes_without_location"] == [
        item.id for item in document.director_script.scenes if item.id != scene.id
    ]
    assert advisory["shots_without_view"] == [shot.id for shot in scene.shots]
    assert "解锁不受影响" in advisory["message"]

    # 绑定齐全的项目：预览不列缺口；正式执行回执携带同一份提示。
    bound = tmp_path / "bound"
    bound.mkdir()
    store, _, document, _ = asyncio.run(_location_project(str(bound)))
    command = DirectorCommand("visual_production.unlock", document.revision, "preview", {})
    preview = preview_command_impact(document, command)
    assert preview["will_write"] is True
    assert preview["location_advisory"] == {
        "scenes_without_location": [],
        "shots_without_view": [],
        "message": "全部 Scene 已绑定地点、已绑定地点的 Shot 均有机位视图。",
    }
    execution = DirectorCommandRegistry(store).execute(
        DirectorCommand("visual_production.unlock", document.revision, "unlock", {})
    )
    assert execution.data["location_advisory"]["scenes_without_location"] == []
    # 重复解锁是 noop，但仍携带同一份地点提示。
    again = DirectorCommandRegistry(store).execute(
        DirectorCommand("visual_production.unlock", store.read().revision, "unlock-again", {})
    )
    assert again.receipt.status == "noop"
    assert again.data["location_advisory"]["shots_without_view"] == []
