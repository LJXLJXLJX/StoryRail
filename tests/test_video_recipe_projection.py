"""视频 recipe 目录、输入预览与隔离保存；合成 Provider 不执行模型。"""

import asyncio
from dataclasses import replace

import pytest
from structured_director_fixtures import RecordingProvider
from test_prompt_worksets import fixture
from video_recipes import replace_video_provider

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.model_providers.manifest import Field, Widget
from core.model_providers.recipe import RecipeBook
from core.model_providers.registry import PluginInstance
from core.structured_director.errors import RevisionConflictError
from core.structured_director.reads.read_tools import execute_project_read
from core.structured_director.reads.video_recipes import video_recipe_state


def test_preview_labels_switch_guards_and_revision_are_read_only(tmp_path):
    store, service, document, _ = asyncio.run(fixture(tmp_path))
    video = document.video_plan.segments[0]
    before = store.path.read_bytes()
    state = service.preview_segment_video_inputs(
        video.segment_id, video.recipe_inputs, document.revision
    )
    assert (
        state["duration_seconds"]
        == document.director_script.scenes[0].segments[0].duration_estimate_seconds
    )
    assert [item["label"] for item in state["bindings"]] == [
        "<Picture 1>",
        "<Picture 2>",
        "<Audio 1>",
        "<Audio 2>",
        "<Audio 3>",
        "<Audio 4>",
        "<Audio 5>",
    ]
    options = {item["id"]: item for item in state["options"]}
    assert not options["minimax_h3.fl2va"]["allowed"]
    assert "请先移除参考音频" in options["minimax_h3.fl2va"]["reason"]
    assert state["ready"]
    with pytest.raises(RevisionConflictError):
        service.preview_segment_video_inputs(
            video.segment_id, video.recipe_inputs, document.revision - 1
        )
    assert store.path.read_bytes() == before


def test_recipe_switch_preserves_each_recipe_mechanism_parameters(tmp_path):
    async def run():
        store, service, document, _ = await fixture(tmp_path)
        plugin = service._registry._plugins["minimax_h3"]
        manifest = replace(
            plugin.manifest,
            recipes=tuple(
                replace(
                    recipe,
                    params=(
                        *recipe.params,
                        Field(
                            "motion", Widget.NUMBER, "动作强度", default=0.5, minimum=0, maximum=1
                        ),
                    ),
                )
                for recipe in plugin.manifest.recipes
            ),
        )
        service._registry._plugins[plugin.plugin_id] = PluginInstance(
            manifest,
            recipes=plugin.recipes,
            prompt_formatter=plugin.prompt_formatter,
            prompt_skills=plugin.prompt_skills,
        )
        segment_id = document.video_plan.segments[1].segment_id
        document = await service.save_segment_video_recipe(
            segment_id=segment_id,
            recipe_id="minimax_h3.ref2va",
            expected_revision=document.revision,
        )
        document = await service.save_segment_video_inputs(
            segment_id=segment_id,
            prompt_text="固定机位。",
            bindings={},
            params={"motion": 0.4},
            expected_revision=document.revision,
        )
        document = await service.save_segment_video_recipe(
            segment_id=segment_id, recipe_id="minimax_h3.fl2va", expected_revision=document.revision
        )
        document = await service.save_segment_video_inputs(
            segment_id=segment_id,
            prompt_text="固定机位。",
            bindings={},
            params={"motion": 0.7},
            expected_revision=document.revision,
        )
        document = await service.save_segment_video_recipe(
            segment_id=segment_id,
            recipe_id="minimax_h3.ref2va",
            expected_revision=document.revision,
        )
        video = next(item for item in document.video_plan.segments if item.segment_id == segment_id)
        assert dict(video.recipe_inputs.params) == {"motion": 0.4}
        assert dict(video.recipes.get("minimax_h3.fl2va").params) == {"motion": 0.7}
        stored = next(
            item for item in store.read().video_plan.segments if item.segment_id == segment_id
        )
        assert stored.recipes == video.recipes

    asyncio.run(run())


def test_missing_recipe_remains_visible_and_does_not_rewrite_saved_inputs(tmp_path):
    store, service, document, _ = asyncio.run(fixture(tmp_path))
    video = document.video_plan.segments[0]
    before = store.path.read_bytes()
    service._registry._plugins.pop("minimax_h3")
    state = video_recipe_state(document, video, service._registry, service.provider_recipe_views())
    assert not state["available"] and not state["ready"]
    assert state["options"] == []
    assert "不可用" in state["reason"]
    assert store.read().video_plan.segments[0].recipes == video.recipes
    assert store.path.read_bytes() == before


def test_ref2va_is_ready_without_frames_but_fl2va_is_not(tmp_path):
    store, service, document, _ = asyncio.run(fixture(tmp_path))
    video = document.video_plan.segments[0]
    document = replace(
        document,
        keyframe_plan=replace(
            document.keyframe_plan,
            segments=tuple(
                replace(item, start_enabled=False, end_enabled=False)
                if item.segment_id == video.segment_id
                else item
                for item in document.keyframe_plan.segments
            ),
        ),
    )
    views = service.provider_recipe_views()
    ref2va = video_recipe_state(document, video, service._registry, views)
    fl2va = video_recipe_state(
        document,
        replace(video, active_recipe="minimax_h3.fl2va"),
        service._registry,
        views,
    )
    assert ref2va["ready"] and ref2va["reason"] is None
    assert not fl2va["ready"]
    assert "含对白的 Segment 必须使用支持参考音频" in fl2va["reason"]


def test_ref2va_submits_without_images_when_audio_is_present(tmp_path):
    async def run():
        store, service, document, _ = await fixture(tmp_path)
        video = document.video_plan.segments[0]
        document = (
            DirectorCommandRegistry(store)
            .execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "disable-boundaries",
                    {
                        "operations": [
                            {
                                "op": "set_activation",
                                "segment_id": video.segment_id,
                                "start_enabled": False,
                                "end_enabled": False,
                            }
                        ]
                    },
                )
            )
            .document
        )
        document = await service.save_segment_video_inputs(
            segment_id=video.segment_id,
            prompt_text="空旷站台上，一盏顶灯轻微闪烁。",
            bindings=video.recipe_inputs.to_json()["bindings"],
            params={},
            expected_revision=document.revision,
        )
        dependency = execute_project_read(
            document,
            "project.get_dependencies",
            {"action": "video.generate", "target_ids": [video.segment_id]},
            provider_catalog=service._registry,
        )
        assert dependency["ready_target_ids"] == [video.segment_id]

        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)
        await service._media.generate_segment_video(
            segment_id=video.segment_id, expected_revision=document.revision
        )
        request = provider.requests[-1]
        assert request.first_frame is None
        assert request.last_frame is None
        assert request.additional_frames == ()
        assert len(request.reference_audios) == 5
        assert request.reference_videos == ()

    asyncio.run(run())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), [float("nan")]])
def test_recipe_book_rejects_nonfinite_mechanism_values(value):
    with pytest.raises(ValueError):
        RecipeBook.from_json({"fixture.recipe": {"bindings": {}, "params": {"value": value}}})


def test_empty_prompt_rejects_video_before_generation_intent(tmp_path):
    async def run():
        store, service, document, _ = await fixture(tmp_path)
        video = document.video_plan.segments[0]
        assert video.prompt_text == ""
        before = store.path.read_bytes()
        generation_ids = tuple(item.id for item in document.generations)
        with pytest.raises(ValueError, match="请先填写并保存当前视频提示词"):
            await service._media.generate_segment_video(
                segment_id=video.segment_id, expected_revision=document.revision
            )
        assert tuple(item.id for item in store.read().generations) == generation_ids
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_dialogue_addition_is_complete_described_and_read_only(tmp_path):
    store, service, document, _ = asyncio.run(fixture(tmp_path))
    video = document.video_plan.segments[0]
    before = store.path.read_bytes()
    state = service.preview_segment_video_inputs(
        video.segment_id, video.recipe_inputs, document.revision
    )
    addition = state["dialogue_audio"]
    assert addition["error"] is None
    assert len(addition["bindings"]) == 3
    segment = document.director_script.scenes[0].segments[0]
    for line, binding in zip(segment.dialogue_lines, addition["bindings"], strict=True):
        assert line.text in binding["description"]
        assert "说话人：" in binding["description"]
        assert "真实时长：1.000 秒" in binding["description"]
        assert "后续视频生成必须严格应用这段对白" in binding["description"]
        assert binding["asset_id"] in addition["replace_asset_ids"]
    missing = replace(
        document,
        dialogue_plan=replace(
            document.dialogue_plan,
            items=tuple(
                replace(item, selected_audio_asset_id=None, start_seconds=None)
                if item.dialogue_line_id == segment.dialogue_lines[1].id
                else replace(item, start_seconds=None)
                for item in document.dialogue_plan.items
            ),
        ),
    )
    state = video_recipe_state(missing, video, service._registry, service.provider_recipe_views())
    assert state["dialogue_audio"]["bindings"] == []
    assert "第 2 句「好的。」" in state["dialogue_audio"]["error"]
    assert store.path.read_bytes() == before


def test_generation_never_injects_missing_dialogue_references(tmp_path):
    from core.structured_director.prompt_worksets import video_prompt_workset
    from core.structured_director.reads.dependencies import _dependency

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        video = document.video_plan.segments[0]
        inputs = video.recipe_inputs.to_json()
        inputs["bindings"]["reference_audios"] = inputs["bindings"]["reference_audios"][:2]
        document = await service.save_segment_video_inputs(
            segment_id=video.segment_id,
            prompt_text="测试显式对白引用。",
            bindings=inputs["bindings"],
            params=inputs["params"],
            expected_revision=document.revision,
        )
        before = store.path.read_bytes()
        workset = video_prompt_workset(
            document,
            video.segment_id,
            provider_recipes=service.provider_recipe_views(),
        )
        assert (
            len([item for item in workset["asset_inputs"] if item["label"].startswith("<Audio")])
            == 2
        )
        assert workset["core_prepended_dialogue_prompt"] is None
        state = service.preview_segment_video_inputs(
            video.segment_id, document.video_plan.segments[0].recipe_inputs, document.revision
        )
        assert not state["ready"] and "缺少本段已选对白" in state["reason"]
        dependency = _dependency(
            document, "video.generate", video.segment_id, catalog=service._registry
        )
        assert not dependency["ready"]
        assert any("缺少本段已选对白" in reason for reason in dependency["reasons"])
        with pytest.raises(ValueError, match="缺少本段已选对白"):
            await service._media.generate_segment_video(
                segment_id=video.segment_id, expected_revision=document.revision
            )
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_dialogue_labels_follow_explicit_order_without_duplicate_submission(tmp_path):
    from core.structured_director.prompt_worksets import video_prompt_workset

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        video = document.video_plan.segments[0]
        inputs = video.recipe_inputs.to_json()
        inputs["bindings"]["reference_audios"].reverse()
        document = await service.save_segment_video_inputs(
            segment_id=video.segment_id,
            prompt_text="测试引用顺序。",
            bindings=inputs["bindings"],
            params=inputs["params"],
            expected_revision=document.revision,
        )
        workset = video_prompt_workset(
            document, video.segment_id, provider_recipes=service.provider_recipe_views()
        )
        assert "<Audio 3> 对应原始对白：先听我说。" in workset["core_prepended_dialogue_prompt"]
        assert "<Audio 1> 对应原始对白：我们开始。" in workset["core_prepended_dialogue_prompt"]
        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)
        await service._media.generate_segment_video(
            segment_id=video.segment_id, expected_revision=document.revision
        )
        assert len(provider.requests[-1].reference_audios) == 5
        assert [item.content for item in provider.requests[-1].reference_audios] == [
            store.read_asset(binding["asset_id"])[1]
            for binding in inputs["bindings"]["reference_audios"]
        ]

    asyncio.run(run())


@pytest.mark.parametrize("already_bound", [False, True])
def test_reselecting_tts_only_replaces_existing_corresponding_audio(tmp_path, already_bound):
    from structured_director_fixtures import wav_bytes

    from scripts.harness.fixtures.candidates import register_dialogue_audio_candidate

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        video = document.video_plan.segments[0]
        segment = document.director_script.scenes[0].segments[0]
        line = segment.dialogue_lines[0]
        old = next(
            item.selected_audio_asset_id
            for item in document.dialogue_plan.items
            if item.dialogue_line_id == line.id
        )
        inputs = video.recipe_inputs.to_json()
        if not already_bound:
            inputs["bindings"]["reference_audios"] = inputs["bindings"]["reference_audios"][:2]
            document = await service.save_segment_video_inputs(
                segment_id=video.segment_id,
                prompt_text="只保存手动参考。",
                bindings=inputs["bindings"],
                params=inputs["params"],
                expected_revision=document.revision,
            )
        document = await service.import_media_asset(
            media_type="audio/wav",
            content=wav_bytes(duration_seconds=2.0) + b"new-dialogue",
            expected_revision=document.revision,
        )
        asset = document.assets[-1]
        card = next(
            card for card in document.reference_library.characters if card.id == line.character_id
        )
        generation_id = register_dialogue_audio_candidate(
            store,
            dialogue_line_id=line.id,
            source_asset_id=asset.id,
            voice_reference_asset_id=card.voice_reference_asset_id,
            reference_transcript=card.voice_reference_transcript,
            text=line.text,
        )
        document = await service.select_dialogue_audio(
            dialogue_line_id=line.id,
            generation_id=generation_id,
            expected_revision=store.read().revision,
        )
        updated = document.video_plan.segments[0].recipe_inputs.to_json()
        if already_bound:
            assert len(updated["bindings"]["reference_audios"]) == 5
            replacement = next(
                binding
                for binding in updated["bindings"]["reference_audios"]
                if binding["asset_id"] == asset.id
            )
            assert "真实时长：2.000 秒" in replacement["description"]
            assert all(
                binding["asset_id"] != old for binding in updated["bindings"]["reference_audios"]
            )
            assert (
                updated["bindings"]["reference_audios"][:2]
                == inputs["bindings"]["reference_audios"][:2]
            )
        else:
            assert updated == inputs
        state = service.preview_segment_video_inputs(
            video.segment_id, document.video_plan.segments[0].recipe_inputs, document.revision
        )
        assert old in state["dialogue_audio"]["replace_asset_ids"]
        assert asset.id in state["dialogue_audio"]["replace_asset_ids"]

    asyncio.run(run())


def _update_inputs(service, document, bindings, *, attach=False, prompt_text="合并测试。"):
    video = document.video_plan.segments[0]
    arguments = {
        "scope": {"scene_ids": [document.director_script.scenes[0].id]},
        "segment_id": video.segment_id,
        "prompt_text": prompt_text,
        "bindings": bindings,
        "params": {},
    }
    if attach:
        arguments["attach_dialogue_audio"] = True
    return service._command_registry.execute(
        DirectorCommand(
            "video.update_recipe_inputs",
            document.revision,
            f"merge-{document.revision}-{attach}",
            arguments,
        )
    )


def test_recipe_inputs_merge_by_slot_and_attach_dialogue_like_web_button(tmp_path):
    from core.structured_director.video_inputs import dialogue_audio_bindings

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        video = document.video_plan.segments[0]
        original = video.recipe_inputs.to_json()
        dialogue = [
            {"asset_id": item.asset_id, "description": item.description}
            for item in dialogue_audio_bindings(document, video.segment_id)
        ]
        dialogue_ids = {item["asset_id"] for item in dialogue}
        manual = [
            item
            for item in original["bindings"]["reference_audios"]
            if item["asset_id"] not in dialogue_ids
        ]

        # 只给出 reference_audios：其他槽位与参数保持原样。
        document = _update_inputs(service, document, {"reference_audios": manual}).document
        saved = document.video_plan.segments[0].recipe_inputs.to_json()
        assert saved["bindings"]["reference_audios"] == manual
        assert {k: v for k, v in saved["bindings"].items() if k != "reference_audios"} == {
            k: v for k, v in original["bindings"].items() if k != "reference_audios"
        }
        assert saved["params"] == original["params"]

        # 只带 attach：对白按剧本顺序在前，手动参考保留在后。
        document = _update_inputs(service, document, {}, attach=True).document
        attached = document.video_plan.segments[0].recipe_inputs.to_json()
        assert attached["bindings"]["reference_audios"] == [*dialogue, *manual]

        # 重复添加不产生重复音频，也不写新 revision。
        result = _update_inputs(service, document, {}, attach=True)
        assert result.document.revision == document.revision
        assert store.read().video_plan.segments[0].recipe_inputs.to_json() == attached

    asyncio.run(run())


def test_attach_dialogue_rejects_whole_request_when_tts_missing(tmp_path):
    from core.director_commands import VideoInputsUpdate
    from core.model_providers.manifest import Capability, Role
    from core.model_providers.recipe import RecipeInputs
    from core.structured_director.video_mutations import _prepare_segment_video_plan_update

    store, service, document, _ = asyncio.run(fixture(tmp_path))
    segment = document.director_script.scenes[0].segments[0]
    video = document.video_plan.segments[0]
    missing = replace(
        document,
        dialogue_plan=replace(
            document.dialogue_plan,
            items=tuple(
                replace(item, selected_audio_asset_id=None, start_seconds=None)
                if item.dialogue_line_id == segment.dialogue_lines[1].id
                else replace(item, start_seconds=None)
                for item in document.dialogue_plan.items
            ),
        ),
    )
    _, recipe = service._registry.recipe_definition(Capability.VIDEO_GENERATE, video.active_recipe)
    slot = next(item for item in recipe.slots if item.role is Role.REFERENCE_AUDIO)
    update = VideoInputsUpdate(
        (document.director_script.scenes[0].id,), video.segment_id, "正文。", RecipeInputs(), True
    )
    with pytest.raises(ValueError, match="第 2 句「好的。」"):
        _prepare_segment_video_plan_update(missing, update, "c" * 32, dialogue_slot=slot)
    with pytest.raises(ValueError, match="不支持参考音频"):
        _prepare_segment_video_plan_update(document, update, "c" * 32)


def test_core_prepends_dialogue_prompt_once_even_if_prompt_already_has_it(tmp_path):
    from core.structured_director.prompt_worksets import video_prompt_workset

    async def run():
        store, service, document, _ = await fixture(tmp_path)
        video = document.video_plan.segments[0]
        prefix = video_prompt_workset(
            document, video.segment_id, provider_recipes=service.provider_recipe_views()
        )["core_prepended_dialogue_prompt"]
        provider = RecordingProvider(media_type="video/mp4", content=b"fake")
        replace_video_provider(service, "ref2va", provider)
        # 已按旧约定把约束写在开头的正文，提交时不再重复前置。
        for prompt_text in (f"{prefix}\n\n正文。",):
            document = await service.save_segment_video_inputs(
                segment_id=video.segment_id,
                prompt_text=prompt_text,
                bindings={},
                params={},
                expected_revision=store.read().revision,
            )
            document = await service._media.generate_segment_video(
                segment_id=video.segment_id, expected_revision=document.revision
            )
            assert provider.requests[-1].prompt == f"{prefix}\n\n正文。"

    asyncio.run(run())
