"""画布式图片插件（输入图 <imageN> 编号、画幅由画布保证、声明 seed）的 Core 侧行为。

用示例插件 `sample_canvas_image` 与 `sample_image` 校验：提示词约定覆盖槽位、实际编号进入提示词、
Core 每次提交分配 seed、提示词 Skill 只交付一次。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from sample_plugins import CANVAS_IMAGE, IMAGE, canvas_image_prompt_skills
from test_keyframe_character_references import _project_with_costumes, _select

from core.model_providers.boundary import ModelProviderError, ProviderHandle
from core.model_providers.manifest import ImagePromptConvention
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.structured_director import StructuredDirectorService
from core.structured_director.models import ReferenceGenerationKind
from core.structured_director.prompt_worksets import image_prompt_guide


def test_prompt_convention_must_cover_every_image_slot() -> None:
    with pytest.raises(ValueError, match="图片提示词约定"):
        replace(IMAGE, image_prompt=ImagePromptConvention("image"))
    assert CANVAS_IMAGE.image_input_label("sample_canvas_image.edit", 2, 3) == "<image2>"
    assert CANVAS_IMAGE.image_input_label("sample_canvas_image.edit", 1, 1) == "图片"
    assert IMAGE.image_input_label("sample_image.edit", 1, 3) is None


class _RecordingCanvas:
    plugin_id = "sample-canvas-image.fake"
    plugin_version = 1

    def __init__(self) -> None:
        self.requests = []
        self.reject = False

    def submit_recipe(self, request):
        self.requests.append(request)
        if self.reject:
            raise ModelProviderError("external_error", "服务拒绝。")
        return ProviderHandle(self.plugin_id, self.plugin_version, f"r{len(self.requests)}")

    def observe(self, handle):
        raise AssertionError("测试不观察。")

    cancel = observe

    def read_artifact(self, handle, artifact_id):
        raise AssertionError("测试不读取产物。")


def canvas_image_service(store):
    provider = _RecordingCanvas()
    registry = ProviderRegistry()
    registry.install(
        PluginInstance(
            CANVAS_IMAGE,
            recipes={recipe.id: provider for recipe in CANVAS_IMAGE.recipes},
            prompt_skills=canvas_image_prompt_skills,
        )
    )
    return StructuredDirectorService(store, registry=registry), provider, registry


def _keyframe_generations(document, keyframe_id):
    return [
        item
        for item in document.generations
        if item.kind is ReferenceGenerationKind.KEYFRAME_IMAGE and item.target_id == keyframe_id
    ]


@pytest.mark.parametrize("explicit_references", [False, True])
def test_canvas_submission_only_uses_authored_reference_instructions(
    tmp_path, explicit_references
) -> None:
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    character, other = document.reference_library.characters
    authored = (
        "<image1>: 甲的身份和造型。\n<image2>: 乙的身份和造型。\n\n"
        "保留<image1>与<image2>的人物，甲在左、乙在右，平视中景。"
        if explicit_references
        else "甲乙并排，平视中景。"
    )
    # 两个同框角色各提交一张造型图。
    document = _select(
        store,
        document,
        keyframe_id,
        character.id,
        character.looks[0].id,
        visible_character_ids=[character.id, other.id],
        prompt_text=authored,
    )
    service, provider, _registry = canvas_image_service(store)
    document = asyncio.run(
        service.generate_keyframe(keyframe_id=keyframe_id, expected_revision=document.revision)
    )
    prompt = provider.requests[0].param("prompt")
    assert prompt.startswith(authored)
    assert prompt.count("<image1>: ") == int(explicit_references)
    assert prompt.count("<image2>: ") == int(explicit_references)
    assert "只约束对应局部细节" not in prompt and "不照搬其机位" not in prompt
    assert "第 1 张输入图" not in prompt
    assert "项目固定画幅" not in prompt and "保持项目画幅比例" not in prompt
    assert _keyframe_generations(document, keyframe_id)[0].prompt_text == prompt


def test_single_input_image_is_called_picture_without_label(tmp_path) -> None:
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    character = document.reference_library.characters[0]
    document = _select(store, document, keyframe_id, character.id, character.looks[2].id)
    service, provider, _registry = canvas_image_service(store)
    asyncio.run(
        service.generate_keyframe(keyframe_id=keyframe_id, expected_revision=document.revision)
    )
    prompt = provider.requests[0].param("prompt")
    assert "图片: " not in prompt and "<image1>" not in prompt


def test_core_assigns_new_seed_per_submission_and_retry_keeps_it(tmp_path) -> None:
    store, _service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    character = document.reference_library.characters[0]
    document = _select(store, document, keyframe_id, character.id, None)
    service, provider, _registry = canvas_image_service(store)
    provider.reject = True
    document = asyncio.run(
        service.generate_keyframe(keyframe_id=keyframe_id, expected_revision=document.revision)
    )
    first = _keyframe_generations(document, keyframe_id)[0]
    assert first.phase.value == "failed" and first.seed is not None
    assert provider.requests[0].param("seed") == first.seed
    assert first.recipe_params.to_json() == {
        "sample_canvas_image.generate": {"height": None, "width": None}
    }
    assert first.provider_snapshot.summary == "2K（长边 2048）"
    document = asyncio.run(service.retry_generation(first.id, expected_revision=document.revision))
    retried = _keyframe_generations(document, keyframe_id)[1]
    assert (retried.retry_of, retried.seed) == (first.id, first.seed)
    document = asyncio.run(
        service.generate_keyframe(keyframe_id=keyframe_id, expected_revision=document.revision)
    )
    assert _keyframe_generations(document, keyframe_id)[-1].seed == first.seed + 1


def test_unseeded_image_generations_keep_no_seed(tmp_path) -> None:
    store, service, document, keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    character = document.reference_library.characters[0]
    document = _select(store, document, keyframe_id, character.id, None)
    registry = ProviderRegistry()
    registry.install(
        PluginInstance(
            IMAGE,
            recipes={recipe.id: _RecordingCanvas() for recipe in IMAGE.recipes},
        )
    )
    service = StructuredDirectorService(store, registry=registry)
    document = asyncio.run(
        service.generate_keyframe(keyframe_id=keyframe_id, expected_revision=document.revision)
    )
    generation = _keyframe_generations(document, keyframe_id)[0]
    assert generation.seed is None
    assert "项目固定画幅" in generation.prompt_text


def test_image_prompt_guide_delivers_skill_once(tmp_path) -> None:
    store, _service, _document, _keyframe_id = asyncio.run(_project_with_costumes(tmp_path))
    _service, _provider, registry = canvas_image_service(store)
    guide = image_prompt_guide(registry)
    assert [item["recipe_id"] for item in guide["recipes"]] == [
        "sample_canvas_image.generate",
        "sample_canvas_image.edit",
    ]
    assert guide["recipes"][0]["image_prompt"]["aspect_ratio_in_prompt"] is False
    assert [skill["name"] for skill in guide["plugin_skills"]] == ["sample-canvas-image-prompt"]
    names = {item["name"] for item in guide["plugin_skills"][0]["resources"]}
    assert names == {"SKILL.md"}
    unbound = image_prompt_guide(None)
    assert unbound["recipes"] == [] and unbound["plugin_skills"] == []
    assert unbound["global_skills"] == guide["global_skills"]
    assert [skill["name"] for skill in guide["global_skills"]] == ["slatehand-image-prompt-writing"]
