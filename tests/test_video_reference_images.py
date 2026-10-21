"""无时间位置参考图：v35 兼容、规划/生成/选用分离、真实 recipe 绑定。"""

import asyncio
from dataclasses import replace

import pytest
from mcp import Client
from provider_factory import provider_registry
from structured_director_fixtures import RecordingProvider
from test_external_script_proposals import confirm_references
from test_prompt_worksets import fixture
from test_storyrail_mcp import endpoint

from core.application.caller import Caller
from core.director_commands import DirectorCommand
from core.structured_director.reads.professional_worksets import workset_read
from core.structured_director.reads.semantic_projection import build_semantic_projection
from core.structured_director.reads.video_recipes import keyframe_video_context
from core.structured_director.reads.workflow_state import workflow_state


def image_update(doc, index=0):
    scene = doc.director_script.scenes[0]
    return {
        "scope": {"scene_ids": [scene.id]},
        "segment_id": scene.segments[0].id,
        "slot_index": index,
        "prompt_text": "控制台与隔离玻璃的完整空间关系。",
        "description": "控制台与玻璃的空间布局参考",
        "visible_character_ids": [],
        "character_references": [],
        "reference_asset_ids": [],
    }


def test_agent_can_discover_plan_and_generate_arbitrary_other_image_through_mcp(tmp_path):
    store, service, doc, _ = asyncio.run(fixture(tmp_path))
    service._registry.install(
        provider_registry(
            image_provider=RecordingProvider(
                media_type="image/png", content=b"\x89PNG\r\n\x1a\nabstract-diagram"
            )
        )._plugins["codex_image"]
    )
    caller = Caller(
        "reference-image-agent",
        "agent",
        frozenset({doc.project_id}),
        frozenset({"project.read", "project.mutate", "project.execute"}),
        4102444800,
        (),
        True,
    )
    scene = doc.director_script.scenes[0]
    segment = scene.segments[0]

    async def run(server):
        async with Client(server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert "save_reference_image_plan" in tools
            assert "reference_image" in tools["generate_media"].description
            assert "select_reference_image" not in tools
            args = image_update(doc, 2)
            args.pop("scope")
            args.update(
                project_id=doc.project_id,
                expected_revision=doc.revision,
                idempotency_key="mcp-other-image-plan",
                scene_ids=[scene.id],
                prompt_text="抽象色块与线条构成的几何示意图，不含人物或地点。",
                description="几何示意图，用于视觉风格参考。",
            )
            before = store.path.read_bytes()
            for invalid in ({"slot_index": 4}, {"asset_id": "f" * 32}, {"scene_ids": ["f" * 32]}):
                rejected = await client.call_tool("save_reference_image_plan", {**args, **invalid})
                assert rejected.is_error
                assert store.path.read_bytes() == before
            saved = await client.call_tool("save_reference_image_plan", args)
            assert not saved.is_error, saved.structured_content
            replay = await client.call_tool("save_reference_image_plan", args)
            assert replay.structured_content["replay"]
            current = store.read()
            image = current.video_plan.segments[0].reference_images[0]
            assert image.visible_character_ids == ()
            assert current.generations == doc.generations
            for extension in ("selection", "keyframe", "video_prompt"):
                read = await client.call_tool(
                    "read_story",
                    {
                        "project_id": doc.project_id,
                        "level": "segment",
                        "scene_ids": [scene.id],
                        "ids": [segment.id],
                        "extensions": [extension],
                    },
                )
                assert not read.is_error, read.structured_content
                inputs = read.structured_content["data"]["items"][0]["video_inputs"]
                assert inputs["reference_image_plans"][0]["id"] == image.id
                assert inputs["reference_image_plans"][0]["slot_index"] == 2
                assert inputs["reference_image_plans"][0]["prompt_text"] == args["prompt_text"]
                assert inputs["reference_image_plans"][0]["selected_asset_id"] is None
            generate_args = {
                "project_id": doc.project_id,
                "expected_revision": current.revision,
                "idempotency_key": "mcp-other-image-generate",
                "kind": "reference_image",
                "target_id": image.id,
            }
            generated = await client.call_tool("generate_media", generate_args)
            assert not generated.is_error, generated.structured_content
            current = store.read()
            assert current.generations[-1].target_id == image.id
            assert current.generations[-1].kind.value == "video_reference_image"
            assert (
                current.video_plan.segments[0].recipe_inputs
                == doc.video_plan.segments[0].recipe_inputs
            )
            replay = await client.call_tool("generate_media", generate_args)
            assert not replay.is_error
            assert replay.structured_content["replay"]
            assert store.read().generations == current.generations
            generation_id = current.generations[-1].id
            for _ in range(3):
                observed = await client.call_tool(
                    "manage_generation",
                    {
                        "project_id": doc.project_id,
                        "action": "wait",
                        "generation_ids": [generation_id],
                    },
                )
                assert not observed.is_error, observed.structured_content
                if store.read().generations[-1].output_asset_id is not None:
                    break
            candidates = await client.call_tool(
                "list_candidates",
                {
                    "project_id": doc.project_id,
                    "kind": "video_reference_image",
                    "target_ids": [image.id],
                },
            )
            assert not candidates.is_error
            candidate = candidates.structured_content["data"]["items"][0]
            assert candidate["reviewable"] and not candidate["selected"]
            media = await client.call_tool(
                "read_media_input",
                {"project_id": doc.project_id, "asset_id": candidate["output_asset"]["id"]},
            )
            assert not media.is_error, media.structured_content
            assert any(block.type == "image" for block in media.content)

    with endpoint(tmp_path, store, service, caller, full_api=True) as (server, _):
        asyncio.run(run(server))


def test_reference_image_planning_preserves_v35_and_video_bindings(tmp_path):
    async def run():
        store, service, doc, _ = await fixture(tmp_path)
        before_bindings = doc.video_plan.segments[0].recipes
        command = DirectorCommand(
            "video.save_reference_image_plan", doc.revision, "ref-plan", image_update(doc, 3)
        )
        result = await service.execute_director_command(command)
        doc = result.document
        image = doc.video_plan.segments[0].reference_images[0]
        assert image.slot_index == 3
        assert doc.video_plan.segments[0].recipes == before_bindings
        reread = store.read()
        assert reread.video_plan.segments[0].reference_images == (image,)
        assert '"schema_version": 35' in store.path.read_text()
        facts = workset_read(
            doc,
            {
                "capability": "keyframe",
                "scope": image_update(doc)["scope"],
                "target_ids": [doc.video_plan.segments[0].segment_id],
            },
            provider_recipes=service.provider_recipe_views(),
        )["core_facts"]["video_inputs"][0]
        assert facts["reference_image_plans"][0]["id"] == image.id
        assert "none" in facts["frame_strategies"]
        assert facts["reference_inputs"]
        assert store.read().revision == doc.revision

    asyncio.run(run())


def test_bound_arbitrary_image_is_readable_without_a_generation_plan(tmp_path):
    async def run():
        store, service, doc, asset_id = await fixture(tmp_path)
        args = {
            key: value
            for key, value in image_update(doc).items()
            if key in {"scope", "segment_id", "slot_index"}
        }
        args.update(asset_id=asset_id, description="用户导入的任意图片，作为视觉参考。")
        doc = (
            await service.execute_director_command(
                DirectorCommand(
                    "video.select_reference_image", doc.revision, "choose-any-image", args
                )
            )
        ).document
        before = store.path.read_bytes()
        item = build_semantic_projection(
            doc,
            {
                "level": "segment",
                "scope": args["scope"],
                "ids": [args["segment_id"]],
                "extensions": ["selection"],
            },
            provider_recipes=service.provider_recipe_views(),
            provider_catalog=service.provider_catalog,
        )["items"][0]
        assert item["video_inputs"]["reference_image_plans"] == []
        image = next(
            binding
            for binding in item["video_inputs"]["reference_inputs"]
            if binding["role"] == "reference_image"
        )
        assert image["asset_id"] == asset_id
        assert image["slot_index"] == 0
        assert image["description"] == args["description"]
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_reference_image_generation_is_candidate_only_and_selection_binds_same_slot(tmp_path):
    async def run():
        store, service, doc, _ = await fixture(tmp_path)
        doc = (
            await service.execute_director_command(
                DirectorCommand(
                    "video.save_reference_image_plan",
                    doc.revision,
                    "plan-image",
                    image_update(doc, 3),
                )
            )
        ).document
        image = doc.video_plan.segments[0].reference_images[0]
        image_registry = provider_registry(
            image_provider=RecordingProvider(
                media_type="image/png", content=b"\x89PNG\r\n\x1a\nreference-image"
            )
        )
        service._registry.install(image_registry._plugins["codex_image"])
        before = doc.video_plan.segments[0].recipe_inputs
        generated = await service.execute_director_command(
            DirectorCommand(
                "video.generate_reference_image",
                doc.revision,
                "generate-image",
                {"image_id": image.id},
            )
        )
        doc = generated.document
        assert doc.generations[-1].kind.value == "video_reference_image"
        assert doc.video_plan.segments[0].recipe_inputs == before
        generation_id = doc.generations[-1].id
        await service._generation_observer.refresh_generation(generation_id)
        doc = await service._generation_observer.refresh_generation(generation_id)
        assert doc.generations[-1].phase.value == "succeeded"
        assert doc.video_plan.segments[0].recipe_inputs == before
        asset_id = doc.generations[-1].output_asset_id
        args = {
            key: value
            for key, value in image_update(doc, 3).items()
            if key in {"scope", "segment_id", "slot_index", "description"}
        }
        args["asset_id"] = asset_id
        doc = (
            await service.execute_director_command(
                DirectorCommand("video.select_reference_image", doc.revision, "select-image", args)
            )
        ).document
        video = doc.video_plan.segments[0]
        bindings = dict(video.recipe_inputs.bindings)["additional_images"]
        assert bindings[0].asset_id == asset_id
        assert video.reference_images[0].id == image.id
        assert video.reference_images[0].slot_index == 0
        assert store.read().video_plan.segments[0].reference_images == video.reference_images
        # 人类选中的任意图片必须出现在可读工作集，不能只收录首尾帧或地点图片。
        request = {
            "capability": "video_prompt",
            "scope": image_update(doc)["scope"],
            "target_ids": [video.segment_id],
        }
        facts = workset_read(
            doc,
            request,
            provider_recipes=service.provider_recipe_views(),
            provider_catalog=service.provider_catalog,
        )["core_facts"]
        assert asset_id in {item["asset_id"] for item in facts["bindable_assets"]}
        assert facts["video_inputs"][0]["reference_image_plans"][0]["selected_asset_id"] == asset_id

    asyncio.run(run())


def test_none_strategy_follows_recipe_instead_of_being_unplanned(tmp_path):
    async def run():
        store, service, doc, _ = await fixture(tmp_path)
        await confirm_references(store, service)
        doc = store.read()
        segment_id = doc.video_plan.segments[0].segment_id
        # 其它 Segment 保持已经选择的边界图。
        doc = replace(
            doc,
            keyframe_plan=replace(
                doc.keyframe_plan,
                segments=tuple(
                    replace(item, start_enabled=False, end_enabled=False)
                    if item.segment_id == segment_id
                    else item
                    for item in doc.keyframe_plan.segments
                ),
            ),
        )
        context = keyframe_video_context(doc, segment_id, service.provider_recipe_views())
        assert "none" in context["frame_strategies"]
        workflow = workflow_state(doc, provider_catalog=service.provider_catalog)
        assert workflow["current_stage"] != "keyframe"
        video = doc.video_plan.segments[0]
        fl2va = replace(
            doc,
            video_plan=replace(
                doc.video_plan,
                segments=tuple(
                    replace(item, active_recipe="minimax_h3.fl2va")
                    if item.segment_id == segment_id
                    else item
                    for item in doc.video_plan.segments
                ),
            ),
        )
        assert (
            "none"
            not in keyframe_video_context(fl2va, segment_id, service.provider_recipe_views())[
                "frame_strategies"
            ]
        )
        assert (
            workflow_state(fl2va, provider_catalog=service.provider_catalog)["current_stage"]
            == "keyframe"
        )
        assert video.active_recipe == "minimax_h3.ref2va"

    asyncio.run(run())


def test_reference_image_rejects_unknown_fields_and_out_of_scope(tmp_path):
    async def run():
        store, service, doc, _ = await fixture(tmp_path)
        before = store.path.read_bytes()
        for args in (
            {**image_update(doc), "unknown": True},
            {**image_update(doc), "slot_index": 4},
            {**image_update(doc), "scope": {"scene_ids": []}},
        ):
            with pytest.raises(ValueError):
                await service.execute_director_command(
                    DirectorCommand(
                        "video.save_reference_image_plan", doc.revision, "bad-image", args
                    )
                )
            assert store.path.read_bytes() == before

    asyncio.run(run())


def test_keyframe_proposal_adds_reference_plan_atomically_without_changing_bindings(tmp_path):
    from test_external_planning_proposals import proposal_for, request
    from test_external_script_proposals import agent, http

    async def run():
        store, service, doc, _ = await fixture(tmp_path)
        req = request(doc, "keyframe")
        caller = agent(doc, req)
        started = await http(service, caller, req)
        assert started.status == 200, started.body
        request_id = started.body["data"]["request_id"]
        doc = store.read()
        saved_bindings = doc.video_plan.segments[0].recipes
        payload = proposal_for(doc, "keyframe")
        image = image_update(doc)
        payload["segments"][0]["reference_images"] = [
            {key: value for key, value in image.items() if key not in {"scope", "segment_id"}}
        ]
        submit = DirectorCommand(
            "keyframe.submit_proposal",
            doc.revision,
            "reference-proposal",
            {"request_id": request_id, "proposal": payload},
        )
        response = await http(service, caller, submit)
        assert response.status == 200, response.body
        finished = store.read()
        assert finished.revision == doc.revision + 1
        assert finished.active_director_run is None
        assert (
            finished.video_plan.segments[0].reference_images[0].prompt_text == image["prompt_text"]
        )
        assert finished.video_plan.segments[0].recipes == saved_bindings

    asyncio.run(run())


def test_agent_cannot_select_reference_image_candidates_or_bypass_via_recipe_inputs(tmp_path):
    from dataclasses import replace

    from core.application.caller import _AGENT_OPERATIONS, Caller, current_caller
    from core.director_commands.video_commands import VideoInputsUpdate
    from core.model_providers.recipe import SlotBinding
    from core.structured_director import (
        GenerationOperation,
        ReferenceGeneration,
        ReferenceGenerationKind,
        ReferenceGenerationPhase,
    )

    assert "video.select_reference_image" not in _AGENT_OPERATIONS

    async def run():
        store, service, doc, _ = await fixture(tmp_path)
        doc = (
            await service.execute_director_command(
                DirectorCommand(
                    "video.save_reference_image_plan", doc.revision, "plan-guard", image_update(doc)
                )
            )
        ).document
        # 已知的项目图片登记成该规划的历史成功候选，证明 Agent 不能直接采用候选。
        image = doc.video_plan.segments[0].reference_images[0]
        candidate = ReferenceGeneration(
            id="f" * 32,
            kind=ReferenceGenerationKind.VIDEO_REFERENCE_IMAGE,
            operation=GenerationOperation.GENERATE,
            target_id=image.id,
            phase=ReferenceGenerationPhase.SUCCEEDED,
            progress=1.0,
            message="候选",
            prompt_text="参考图",
            input_asset_ids=(),
            sample_text=None,
            seed=None,
            plugin_id="test.image",
            plugin_version=1,
            external_id="external-candidate",
            output_asset_id=next(
                asset.id for asset in doc.assets if asset.media_type.startswith("image/")
            ),
            error_code=None,
            cancellation_requested=False,
            retry_of=None,
        )
        store._atomic_write(
            replace(doc, revision=doc.revision + 1, generations=(*doc.generations, candidate))
        )
        doc = store.read()
        video = doc.video_plan.segments[0]
        before = store.path.read_bytes()
        inputs = replace(
            video.recipe_inputs,
            bindings=tuple(
                sorted(
                    {
                        **dict(video.recipe_inputs.bindings),
                        "additional_images": (SlotBinding(candidate.output_asset_id, "候选"),),
                    }.items()
                )
            ),
        )
        caller = Caller("agent", "agent", frozenset({doc.project_id}), frozenset(), 9999999999)
        token = current_caller.set(caller)
        try:
            with pytest.raises(ValueError, match="人类"):
                store.set_segment_video_inputs(
                    VideoInputsUpdate(
                        (doc.director_script.scenes[0].id,),
                        video.segment_id,
                        video.prompt_text,
                        inputs,
                    ),
                    expected_revision=doc.revision,
                    command_id="bypass",
                )
        finally:
            current_caller.reset(token)
        assert store.path.read_bytes() == before

    asyncio.run(run())
