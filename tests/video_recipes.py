"""视频 recipe 测试场景的输入装配：按示例视频插件 manifest 构造与校验领域状态。"""

from dataclasses import replace
from enum import StrEnum
from types import SimpleNamespace

from sample_plugins import VIDEO as MANIFEST

from core.model_providers.manifest import Capability
from core.model_providers.recipe import RecipeBook, RecipeInputs, _parse_slot_wire
from core.structured_director.models.video import SegmentVideo


class SegmentVideoGenerationMode(StrEnum):
    FL2VA = "fl2va"
    REF2VA = "ref2va"


def recipe_id(mode):
    return str(mode) if str(mode).startswith("sample_video.") else f"sample_video.{mode}"


def video_mode(video):
    return SegmentVideoGenerationMode(video.active_recipe.removeprefix("sample_video."))


def video_wire_mode(video):
    return video["active_recipe"].removeprefix("sample_video.")


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
    slot = next(slot for slot in MANIFEST.recipe("sample_video.ref2va").slots if slot.key == key)
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
    from provider_factory import RecipeAdapter

    service._registry._plugins["sample_video"].recipes[recipe_id(mode)] = RecipeAdapter(provider)


def set_video_settings(service, **settings):
    service._registry.update_plugin_settings("sample_video", settings)


def h3_dialogue_prompt(workset, *, tail=""):
    """按官方 Ref2VA 六段结构写出能通过插件校验的对白提示词；台词只出现在 `<d>` 中一次。"""
    speakers = {}
    for line in workset["prompt_dialogue"]:
        speakers.setdefault(line["speaker"], len(speakers) + 1)
    definitions = [
        f"<Subject {number}> 是关键帧中的{speaker}，保持外观与服装。"
        for speaker, number in speakers.items()
    ]
    retention = [
        f"<Subject {number}> (appears in [Shot 1]): fully_preserved - 外观与服装保持一致。"
        for number in speakers.values()
    ]
    spoken = []
    for line in workset["prompt_dialogue"]:
        number = speakers[line["speaker"]]
        label = line["audio_label"]
        definitions.append(f"{label} 是 <Subject {number}> (S{number}) 的对白音频。")
        retention.append(f"{label}: partially_copy - 原信号放在这句对白的时间窗内。")
        spoken.append(
            f"<Subject {number}> (S{number}) 按 {label} 开口说：<d>[Chinese] {line['text']}</d>"
        )
    return "\n".join(
        [
            "subject_definitions:",
            *definitions,
            "summary:",
            "[keyframe completion + audio reuse] 角色在室内依次对话。",
            "retention_analysis:",
            *retention,
            "detailed_description:",
            "写实电影风格。",
            "[Shot 1] 中景固定机位，" + " ".join(spoken),
            "overall_soundscape:",
            "室内空调低鸣，衣料摩擦声。除上述对白外无其它人类语音。",
            "non_diegetic_music:",
            "N/A" + tail,
        ]
    )
