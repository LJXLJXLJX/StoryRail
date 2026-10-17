"""H3 测试场景的 recipe 输入装配；旧行为断言继续校验新领域状态与 manifest。"""

from dataclasses import replace
from enum import StrEnum
from types import SimpleNamespace

from core.model_providers.manifest import Capability
from core.model_providers.minimax_h3.manifest import MANIFEST
from core.model_providers.minimax_h3.prompt_contract import (
    H3DialogueInput,
    H3PromptContext,
    H3PromptMode,
)
from core.model_providers.recipe import RecipeBook, RecipeInputs, _parse_slot_wire
from core.structured_director.keyframe_requests import _find_segment_context
from core.structured_director.models import StructuredDirectorDocument
from core.structured_director.models.video import SegmentVideo
from core.structured_director.video_inputs import resolve_video_inputs


class SegmentVideoGenerationMode(StrEnum):
    FL2VA = "fl2va"
    REF2VA = "ref2va"


def recipe_id(mode):
    return str(mode) if str(mode).startswith("minimax_h3.") else f"minimax_h3.{mode}"


def video_mode(video):
    return SegmentVideoGenerationMode(video.active_recipe.removeprefix("minimax_h3."))


def video_wire_mode(video):
    return video["active_recipe"].removeprefix("minimax_h3.")


def video_slot(video, key):
    return video.recipe_inputs.slot(key)


_KEYS = {
    "additional_image_references": "additional_images",
    "audio_references": "reference_audios",
    "video_references": "reference_videos",
}


def video_wire_dict(raw):
    value = dict(raw)
    mode = value.pop("generation_mode", None)
    refs = {wire: value.pop(old) for old, wire in _KEYS.items() if old in value}
    persisted = (
        "selected_asset_id" in value
        or "upscaled_asset_id" in value
        or ("segment_id" in value and "scope" not in value and "expected_revision" not in value)
    )
    if persisted:
        active = value.get("active_recipe") or recipe_id(mode or "fl2va")
        value["active_recipe"] = active
        recipes = dict(value.get("recipes", {}))
        if refs:
            previous = recipes.get(active, {"bindings": {}, "params": {}})
            recipes[active] = {
                "bindings": {**previous["bindings"], **refs},
                "params": previous["params"],
            }
        value["recipes"] = recipes
    else:
        if mode is not None:
            value["recipe_id"] = recipe_id(mode)
        if refs:
            value["bindings"] = {
                **value.get("bindings", {}),
                **{key: items for key, items in refs.items() if items},
            }
            value.setdefault("params", {})
    return value


def _reference(key, asset_id, description):
    slot = next(slot for slot in MANIFEST.recipe("minimax_h3.ref2va").slots if slot.key == key)
    return _parse_slot_wire(slot, [{"asset_id": asset_id, "description": description}])[0]


def SegmentVideoImageReference(asset_id, description):
    return _reference("additional_images", asset_id, description)


def SegmentVideoAudioReference(asset_id, description):
    return _reference("reference_audios", asset_id, description)


def SegmentVideoVideoReference(asset_id, description):
    return _reference("reference_videos", asset_id, description)


def make_video(
    segment_id,
    prompt_text,
    generation_mode=SegmentVideoGenerationMode.FL2VA,
    additional_image_references=(),
    audio_references=(),
    video_references=(),
    selected_asset_id=None,
    upscaled_asset_id=None,
    **kwargs,
):
    active = kwargs.pop("active_recipe", recipe_id(generation_mode))
    bindings = {
        wire: [{"asset_id": item.asset_id, "description": item.description} for item in items]
        for wire, items in zip(
            _KEYS.values(),
            (additional_image_references, audio_references, video_references),
            strict=True,
        )
        if items
    }
    book = kwargs.pop(
        "recipes",
        RecipeBook.from_json({active: {"bindings": bindings, "params": {}}})
        if bindings
        else RecipeBook(),
    )
    video = SegmentVideo(
        segment_id, prompt_text, active, book, selected_asset_id, upscaled_asset_id, **kwargs
    )
    validate_video(video)
    return video


def validate_video(video):
    from core.model_providers.registry import PluginInstance, ProviderRegistry

    class FixtureProvider:
        def submit_recipe(self, request):
            raise AssertionError("只用于契约校验")

        def observe(self, handle):
            raise AssertionError("只用于契约校验")

        def cancel(self, handle):
            raise AssertionError("只用于契约校验")

        def read_artifact(self, handle, artifact_id):
            raise AssertionError("只用于契约校验")

    registry = ProviderRegistry()
    registry.install(
        PluginInstance(
            MANIFEST, recipes={recipe.id: FixtureProvider() for recipe in MANIFEST.recipes}
        )
    )
    types = {
        "additional_images": "image/png",
        "reference_audios": "audio/wav",
        "reference_videos": "video/mp4",
    }
    assets = [
        SimpleNamespace(id=item.asset_id, media_type=types[key], duration_seconds=3.0)
        for key, items in video.recipe_inputs.bindings
        for item in items
    ]
    registry.validate_recipe_inputs(
        Capability.VIDEO_GENERATE, video.active_recipe, video.recipe_inputs, assets
    )


def replace_video(video, **changes):
    mode = changes.pop("generation_mode", None)
    active = recipe_id(mode) if mode is not None else video.active_recipe
    inputs = video.recipes.get(active).to_json()
    for old, key in _KEYS.items():
        if old in changes:
            inputs["bindings"][key] = [
                {"asset_id": item.asset_id, "description": item.description}
                for item in changes.pop(old)
            ]
    inputs["bindings"] = {key: items for key, items in inputs["bindings"].items() if items}
    updated = replace(
        video,
        active_recipe=active,
        recipes=video.recipes.with_entry(active, RecipeInputs.from_json(inputs)),
        **changes,
    )
    validate_video(updated)
    return updated


def build_h3_context(
    document: StructuredDirectorDocument,
    segment_id: str,
    *,
    historical_prompt_text: str | None = None,
    user_message: str = "",
) -> H3PromptContext:
    script = document.director_script
    keyframe_plan = document.keyframe_plan
    video_plan = document.video_plan
    if script is None or keyframe_plan is None or video_plan is None:
        raise ValueError("视频生产上下文尚未建立。")
    scene, shot, segment = _find_segment_context(script.scenes, segment_id)
    binding = next(
        (item for item in keyframe_plan.segments if item.segment_id == segment_id),
        None,
    )
    plan_item = next(
        (item for item in video_plan.segments if item.segment_id == segment_id),
        None,
    )
    if binding is None or plan_item is None:
        raise ValueError("Segment 视频计划不存在。")
    if historical_prompt_text is not None and (
        not isinstance(historical_prompt_text, str) or len(historical_prompt_text) > 20_000
    ):
        raise ValueError("历史 H3 提示词必须是最多 20000 字的文本。")
    if not isinstance(user_message, str) or len(user_message) > 20_000:
        raise ValueError("本轮 H3 优化要求必须是最多 20000 字的文本。")
    keyframes = {item.id: item for item in keyframe_plan.keyframes}
    start = keyframes[binding.start_keyframe_id]
    end = keyframes[binding.end_keyframe_id]
    actual = resolve_video_inputs(document, segment_id)
    has_start = actual.start_asset_id is not None
    has_end = actual.end_asset_id is not None
    characters = {item.id: item for item in document.reference_library.characters}
    if plan_item.active_recipe == "minimax_h3.ref2va":
        mode = H3PromptMode.REF2VA
    elif has_start and has_end:
        mode = H3PromptMode.FL2VA
    elif has_start:
        mode = H3PromptMode.I2VA
    else:
        mode = H3PromptMode.L2VA
    if segment.duration_estimate_seconds < 0.2:
        raise ValueError("Segment 时长不能短于 0.2 秒。")
    context = H3PromptContext(
        mode=mode,
        duration_seconds=segment.duration_estimate_seconds,
        aspect_ratio=document.aspect_ratio.value,
        scene_title=scene.title,
        scene_setting=scene.setting,
        shot_composition=shot.composition,
        camera_movement=shot.camera_movement,
        shot_action=shot.action,
        segment_action=segment.action,
        historical_prompt=(
            plan_item.prompt_text
            if historical_prompt_text is None
            else historical_prompt_text.strip()
        ),
        user_direction=user_message.strip(),
        audio_direction=shot.audio_direction,
        start_frame_description=(
            (start.prompt_text.strip() or "以已选首帧图片的可见内容为准。") if has_start else None
        ),
        end_frame_description=(
            (end.prompt_text.strip() or "以已选尾帧图片的可见内容为准。") if has_end else None
        ),
        dialogue=tuple(
            H3DialogueInput(
                character_name=(
                    item.speaker_label
                    if item.character_id is None
                    else characters[item.character_id].name
                    if item.character_id in characters
                    else item.character_id
                ),
                text=item.text,
                delivery=item.delivery,
                on_screen=(
                    None
                    if item.character_id is None
                    else item.character_id in shot.visible_character_ids
                ),
            )
            for item in segment.dialogue_lines
        ),
        additional_image_descriptions=tuple(
            reference.description for reference in plan_item.recipe_inputs.slot("additional_images")
        ),
        audio_reference_descriptions=tuple(
            reference.description for reference in plan_item.recipe_inputs.slot("reference_audios")
        ),
        video_reference_descriptions=tuple(
            reference.description for reference in plan_item.recipe_inputs.slot("reference_videos")
        ),
        scene_driver=scene.driver,
    )
    return context


def video_prompt_workset(document, segment_id):
    from provider_factory import provider_registry
    from structured_director_fixtures import RecordingProvider

    from core.structured_director.prompt_worksets import video_prompt_workset as build

    catalog = provider_registry(
        fl2va_provider=RecordingProvider(media_type="video/mp4", content=b"fake"),
        ref2va_provider=RecordingProvider(media_type="video/mp4", content=b"fake"),
    )
    return build(
        document, segment_id, provider_recipes=catalog.recipe_views(), provider_catalog=catalog
    )


def video_wire_slot(value, key):
    if "recipes" in value:
        return (
            value["recipes"].get(value["active_recipe"], {"bindings": {}})["bindings"].get(key, [])
        )
    if "bindings" in value:
        return value["bindings"].get(key, [])
    return value[{wire: old for old, wire in _KEYS.items()}[key]]


async def save_video_inputs(service, *, segment_id, prompt_text, expected_revision, **values):
    current = next(
        item for item in service._store.read().video_plan.segments if item.segment_id == segment_id
    )
    if current.active_recipe is None:
        from core.model_providers.manifest import Capability, DomainPredicate

        document = service._store.read()
        segment = next(
            segment
            for scene in document.director_script.scenes
            for segment in scene.segments
            if segment.id == segment_id
        )
        predicates = (
            frozenset({DomainPredicate.SEGMENT_HAS_DIALOGUE})
            if segment.dialogue_lines
            else frozenset()
        )
        selected = service._registry.recipe_for(Capability.VIDEO_GENERATE, predicates)
        if selected is None:
            raise AssertionError("测试必须安装视频插件")
        document = await service.save_segment_video_recipe(
            segment_id=segment_id, recipe_id=selected[1].id, expected_revision=expected_revision
        )
        expected_revision = document.revision
        current = next(
            item for item in document.video_plan.segments if item.segment_id == segment_id
        )
    inputs = current.recipe_inputs.to_json()
    for old, key in _KEYS.items():
        if old in values and values[old] is not None:
            inputs["bindings"][key] = [
                {"asset_id": item.asset_id, "description": item.description}
                for item in values.pop(old)
            ]
    inputs["bindings"] = {key: items for key, items in inputs["bindings"].items() if items}
    inputs.update(values)
    return await service.save_segment_video_inputs(
        segment_id=segment_id,
        prompt_text=prompt_text,
        expected_revision=expected_revision,
        **inputs,
    )


def replace_video_provider(service, mode, provider):
    from provider_factory import _VideoRecipeAdapter

    service._registry._plugins["minimax_h3"].recipes[recipe_id(mode)] = _VideoRecipeAdapter(
        provider
    )


def set_video_render(service, render):
    service._registry.update_plugin_settings(
        "minimax_h3",
        {
            "preset": "turbo_v2" if render.steps == 8 else "hybrid_v2",
            "resolution": render.resolution.value,
            "sage_attention": render.sage_attention,
            "selflift": render.selflift,
        },
    )
