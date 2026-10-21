"""全局图片引用格式、真实编号与最终 Provider 提示词的对应关系。"""

from types import SimpleNamespace

import pytest
from provider_factory import provider_registry
from structured_director_fixtures import RecordingProvider

from core.model_providers.image_prompt_skill import image_prompt_guide, image_prompt_skill
from core.model_providers.manifest import Capability
from core.model_providers.qwen_image.manifest import MANIFEST as QWEN
from core.structured_director.image_inputs import ImageInput, ImageInputs, ordered_image_inputs
from core.structured_director.image_prompt_style import ImagePromptStyle
from core.structured_director.keyframe_requests import (
    _keyframe_effective_prompt,
    _keyframe_reference_prompt,
)
from core.structured_director.location_requests import location_image_prompt
from core.structured_director.models import GenerationOperation, Keyframe, LocationImageKind
from core.structured_director.reference_image_requests import reference_image_prompt


def inputs(count=2):
    return ImageInputs(
        tuple(f"{index:032x}" for index in range(1, count + 1)),
        tuple((f"private-filename-{index}.png", "默认用途") for index in range(1, count + 1)),
        GenerationOperation.GENERATE,
        tuple(("辅助参考",) for _ in range(count)),
    )


PROMPT = (
    "<Picture1>: 画风参考，采用线条与色彩。\n"
    "<Picture2>: 空间参考，保留建筑与陈设。\n\n"
    "画面正文：\n采用<Picture1>的画风，基于<Picture2>保留空间布局，改为平视中近景。"
)


@pytest.mark.parametrize("prompt", [PROMPT, "旧的自由正文保持原样。"])
def test_only_authored_references_enter_every_project_image_prompt(prompt):
    actual = inputs()
    document = SimpleNamespace(aspect_ratio=SimpleNamespace(value="16:9"))
    frame = Keyframe("a" * 32, "b" * 32, None, prompt, ())
    location = SimpleNamespace(name="厅堂", description="石质空间", fixtures=(), key_light=None)
    image = SimpleNamespace(
        prompt_text=prompt, kind=LocationImageKind.IMAGE, description="大厅布局"
    )
    plan = SimpleNamespace(location=location, image=image, inputs=actual, aspect_ratio="16:9")
    for compiled in (
        _keyframe_effective_prompt(document, frame, actual),
        location_image_prompt(document, plan),
        reference_image_prompt(document, image, actual, ImagePromptStyle()),
    ):
        assert compiled.startswith(prompt)
        assert compiled.count("<Picture1>: 画风参考") == prompt.count("<Picture1>: 画风参考")
        assert compiled.count("<Picture2>: 空间参考") == prompt.count("<Picture2>: 空间参考")
        assert "private-filename" not in compiled and "默认用途" not in compiled
        assert "输入图对应关系" not in compiled
        assert "不照搬其机位" not in compiled and "只约束对应局部细节" not in compiled
    preview = _keyframe_reference_prompt(actual)
    assert "private-filename-1.png" in preview and "<Picture1>" in preview
    assert "默认用途" not in preview and "画风参考" not in preview
    assert all("purpose" not in item for item in actual.describe())


@pytest.mark.parametrize("count", [1, 2])
def test_qwen_uses_its_actual_single_or_multiple_image_labels(count):
    actual = inputs(count)
    style = ImagePromptStyle(QWEN, "qwen_image.generate")
    labels = ("图片",) if count == 1 else ("<image1>", "<image2>")
    prompt = "\n".join(f"{label}: 提供视觉参考。" for label in labels)
    prompt += "\n\n" + "；".join(f"参考{label}的视觉信息" for label in labels)
    assert actual.validate_prompt(prompt, style) == prompt
    assert [item["label"] for item in actual.describe(style)] == list(labels)
    assert all(label in prompt for label in labels)


@pytest.mark.parametrize(
    "prompt",
    [
        "<Picture1>: 画风。\n\n正文只写场景。",
        "<Picture2>: 空间。\n<Picture1>: 画风。\n\n参考<Picture1>与<Picture2>。",
        "<Picture1>: \n<Picture2>: 空间。\n\n参考<Picture1>与<Picture2>。",
        "<Picture1>: 画风。\n<Picture2>: 空间。\n<Picture3>: 多余图片。\n\n"
        "参考<Picture1>与<Picture2>。",
    ],
)
def test_explicit_mapping_rejects_missing_wrong_or_unreferenced_inputs(prompt):
    with pytest.raises(ValueError):
        inputs().validate_prompt(prompt)


def test_no_input_has_no_mapping_and_plain_historical_text_is_preserved():
    assert (
        inputs(0).validate_prompt("平视中景，石柱位于画面两侧。") == "平视中景，石柱位于画面两侧。"
    )
    with pytest.raises(ValueError, match="没有实际输入图"):
        inputs(0).validate_prompt("<Picture1>: 风格。\n\n参考<Picture1>的风格。")
    assert inputs().validate_prompt("旧的自由正文保持原样。") == "旧的自由正文保持原样。"


def test_source_reordering_and_duplicate_roles_share_the_same_actual_label():
    assets = [SimpleNamespace(id=id, display_name=f"{id}.png") for id in ("a", "b")]
    actual = ordered_image_inputs(
        SimpleNamespace(assets=assets),
        [
            ImageInput("a", "角色", "身份"),
            ImageInput("b", "底图", "底图"),
            ImageInput("a", "辅助", "画风"),
        ],
        operation=GenerationOperation.EDIT,
        label="引用",
        source_asset_id="b",
    )
    assert actual.asset_ids == ("b", "a")
    assert actual.describe()[0]["label"] == "<Picture1>"
    assert actual.describe()[1]["roles"] == ["角色", "辅助"]


def test_global_skill_is_delivered_without_qwen_or_even_a_bound_image_provider():
    registry = provider_registry(
        image_provider=RecordingProvider(media_type="image/png", content=b"png")
    )
    skill = image_prompt_skill()
    assert image_prompt_guide(None)["global_skills"] == [skill]
    guide = image_prompt_guide(registry)
    assert guide["global_skills"] == [skill]
    for capability in (Capability.IMAGE_GENERATE, Capability.IMAGE_EDIT):
        _plugin, recipe = registry.recipe_for(capability)
        assert registry.format_prompt_workset(capability, recipe.id, {})["global_skills"] == [skill]
