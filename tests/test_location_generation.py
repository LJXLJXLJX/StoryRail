"""独立地点图片、全景图与确定性全景取景的生成契约。"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from structured_director_fixtures import add_image_asset, png_header_bytes
from test_director_commands import _visual_project

from core.application.caller import _AGENT_OPERATIONS
from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.qwen_image import MANIFEST as QWEN_MANIFEST
from core.model_providers.qwen_image.plugin import format_prompt_workset
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.structured_director import StructuredDirectorService
from core.structured_director.models import (
    PanoramaCaptureRequest,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)

KIND = ReferenceGenerationKind


class FakeImage:
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.plugin_version = 1
        self.requests = []
        self.size = (1920, 1080)
        self.reject = False
        self._outputs: dict[str, bytes] = {}

    def submit_recipe(self, request):
        self.requests.append(request)
        if self.reject:
            raise ModelProviderError("external_error", "服务拒绝。")
        external_id = f"img-{len(self.requests)}"
        self._outputs[external_id] = png_header_bytes(external_id, *self.size)
        return ProviderHandle(self.plugin_id, self.plugin_version, external_id)

    def observe(self, handle):
        content = self._outputs[handle.external_id]
        return GenerationObservation(
            GenerationPhase.SUCCEEDED,
            1.0,
            "完成",
            ArtifactDescriptor(
                handle.external_id,
                "image/png",
                len(content),
                hashlib.sha256(content).hexdigest(),
            ),
        )

    def cancel(self, handle):
        return GenerationObservation(GenerationPhase.CANCELLED, 0.0, "已取消")

    def read_artifact(self, handle, artifact_id):
        return self._outputs[handle.external_id]


class FakePano(FakeImage):
    def __init__(self) -> None:
        super().__init__("ffmpeg.pano_view")
        self.size = (1920, 1080)
        self.fail_next = False

    def submit(self, request):
        if self.fail_next:
            self.fail_next = False
            self.requests.append(request)
            raise ModelProviderError("transport_error", "测试传输失败")
        return self.submit_recipe(request)


class Rig:
    """真实 Store/Service + 图片和全景 Provider 替身。"""

    def __init__(self, tmp_path: Path, *, pano: bool = True) -> None:
        directory = tmp_path / uuid4().hex
        directory.mkdir()
        self.store, _service, _document, _route = asyncio.run(_visual_project(str(directory)))
        self.image = FakeImage(f"{QWEN_MANIFEST.recipes[0].id.split('.')[0]}.fake")
        self.pano = FakePano()
        registry = ProviderRegistry()
        registry.install(
            PluginInstance(
                QWEN_MANIFEST,
                recipes={recipe.id: self.image for recipe in QWEN_MANIFEST.recipes},
                prompt_formatter=format_prompt_workset,
            )
        )
        if pano:
            registry.register("pano_view", self.pano)
        self.service = StructuredDirectorService(self.store, registry=registry)
        self.registry = DirectorCommandRegistry(self.store)

    @property
    def document(self):
        return self.store.read()

    def run(self, name: str, arguments: dict):
        return self.registry.execute(
            DirectorCommand(name, self.document.revision, uuid4().hex, arguments)
        )

    def build(self, *images: dict) -> dict[str, str]:
        images = images or (
            {
                "key": "front",
                "name": "壁炉正面",
                "kind": "image",
                "description": "人眼高度的壁炉正面中景，木地板与白墙清晰可见。",
                "prompt_text": "温暖老式客厅，壁炉正面中景，无人物。",
            },
        )
        result = self.run(
            "location.apply_operations",
            {
                "scope": {"location_ids": [], "scene_ids": []},
                "operations": [
                    {
                        "op": "create_location",
                        "key": "room",
                        "name": "客厅",
                        "description": "木地板、白墙、暖色调。",
                    },
                    {
                        "op": "update_location",
                        "location_id": "room",
                        "fields": {"key_light": {"description": "壁炉火光"}},
                    },
                    {
                        "op": "upsert_fixture",
                        "location_id": "room",
                        "fixture": "fireplace",
                        "name": "壁炉",
                        "description": "石砌壁炉",
                    },
                    {
                        "op": "upsert_state",
                        "location_id": "room",
                        "state": "night",
                        "name": "夜晚",
                        "description": "只有火光。",
                    },
                    *(
                        {
                            "op": "create_image",
                            "location_id": "room",
                            "key": image["key"],
                            "fields": {k: v for k, v in image.items() if k != "key"},
                        }
                        for image in images
                    ),
                ],
            },
        )
        return result.data["created_ids"]

    def generate_image(self, image_id: str):
        return asyncio.run(
            self.service.generate_location_image(
                image_id=image_id, expected_revision=self.document.revision
            )
        )

    def capture(self, image_id: str):
        return asyncio.run(
            self.service.generate_location_capture(
                image_id=image_id, expected_revision=self.document.revision
            )
        )

    def finish(self, generation_id: str):
        return asyncio.run(self.service._generation_observer.refresh_generation(generation_id))

    def last(self, kind: ReferenceGenerationKind, target_id: str):
        return next(
            item
            for item in reversed(self.document.generations)
            if item.kind is kind and item.target_id == target_id
        )

    def select_image(self, image_id: str, asset_id: str):
        return self.run("location.select_image", {"image_id": image_id, "asset_id": asset_id})

    def image_row(self, image_id: str):
        return self.document.location_library.image_owner(image_id)[1]

    def generate_finish_select(self, image_id: str) -> str:
        self.generate_image(image_id)
        generation = self.last(KIND.LOCATION_IMAGE, image_id)
        self.finish(generation.id)
        asset_id = self.last(KIND.LOCATION_IMAGE, image_id).output_asset_id
        assert asset_id is not None
        self.select_image(image_id, asset_id)
        return asset_id


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


def test_plain_image_uses_project_aspect_and_candidate_requires_human_selection(rig):
    ids = rig.build()
    rig.generate_image(ids["front"])
    generation = rig.last(KIND.LOCATION_IMAGE, ids["front"])
    assert generation.phase is ReferenceGenerationPhase.QUEUED
    assert generation.aspect_ratio == rig.document.aspect_ratio.value
    assert "本图片实际内容说明目标" in generation.prompt_text
    assert rig.image_row(ids["front"]).selected_asset_id is None
    rig.finish(generation.id)
    candidate = rig.last(KIND.LOCATION_IMAGE, ids["front"]).output_asset_id
    assert candidate is not None
    assert rig.image_row(ids["front"]).selected_asset_id is None
    rig.select_image(ids["front"], candidate)
    assert rig.image_row(ids["front"]).selected_asset_id == candidate


def test_plain_image_accepts_an_existing_project_library_image(rig):
    ids = rig.build()
    asset_id = add_image_asset(rig.store, width=1920, height=1080)
    rig.select_image(ids["front"], asset_id)
    assert rig.image_row(ids["front"]).selected_asset_id == asset_id


def test_panorama_capture_child_rejects_an_unrelated_library_image(rig):
    ids = rig.build(
        {
            "key": "pano",
            "name": "空间全景",
            "kind": "panorama",
            "description": "客厅完整全景。",
            "prompt_text": "客厅等距柱状全景。",
        },
        {
            "key": "child",
            "name": "沙发方向",
            "kind": "image",
            "description": "从全景中截取的沙发方向中景。",
            "prompt_text": "",
            "source": {
                "panorama_image_id": "pano",
                "yaw_deg": 45.0,
                "pitch_deg": -5.0,
                "hfov_deg": 70.0,
            },
        },
    )
    asset_id = add_image_asset(rig.store, width=1920, height=1080)
    with pytest.raises(ValueError, match="全景取景子图只能选择"):
        rig.select_image(ids["child"], asset_id)


def test_panorama_is_optional_independent_image_and_always_2_1(rig):
    ids = rig.build(
        {
            "key": "pano",
            "name": "空间全景",
            "kind": "panorama",
            "description": "完整展示客厅四周墙面、门窗与壁炉位置。",
            "prompt_text": "360 度客厅全景，无人物。",
        },
        {
            "key": "detail",
            "name": "壁炉特写",
            "kind": "image",
            "description": "石砌壁炉和火焰的近景。",
            "prompt_text": "石砌壁炉近景。",
        },
    )
    rig.image.size = (2048, 1024)
    rig.generate_image(ids["pano"])
    pano = rig.last(KIND.LOCATION_IMAGE, ids["pano"])
    assert pano.aspect_ratio == "2:1"
    assert "360°×180°" in pano.prompt_text
    assert rig.image_row(ids["detail"]).source is None


def test_description_and_prompt_are_both_required_before_generation(rig):
    with pytest.raises(ValueError, match="description"):
        rig.build(
            {
                "key": "bad",
                "name": "无说明",
                "kind": "image",
                "description": "",
                "prompt_text": "画面。",
            }
        )
    ids = rig.build(
        {
            "key": "empty_prompt",
            "name": "待写提示词",
            "kind": "image",
            "description": "画面中是一面白墙。",
            "prompt_text": "",
        }
    )
    with pytest.raises(ValueError, match="生成提示词"):
        rig.generate_image(ids["empty_prompt"])


def test_arbitrary_explicit_image_references_keep_order(rig):
    ids = rig.build(
        {
            "key": "first",
            "name": "第一张",
            "kind": "image",
            "description": "第一张地点图片。",
            "prompt_text": "第一张。",
        },
        {
            "key": "second",
            "name": "第二张",
            "kind": "image",
            "description": "第二张地点图片。",
            "prompt_text": "第二张。",
        },
    )
    reference = rig.generate_finish_select(ids["first"])
    rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [ids["room"]], "scene_ids": []},
            "operations": [
                {
                    "op": "update_image",
                    "image_id": ids["second"],
                    "fields": {"reference_asset_ids": [reference]},
                }
            ],
        },
    )
    rig.generate_image(ids["second"])
    generation = rig.last(KIND.LOCATION_IMAGE, ids["second"])
    assert generation.input_asset_ids == (reference,)
    assert generation.prompt_text.startswith("第二张。")
    assert "第一张地点图片。" not in generation.prompt_text
    assert "输入图对应关系" not in generation.prompt_text


def test_panorama_capture_freezes_geometry_and_directly_selects_child(rig):
    ids = rig.build(
        {
            "key": "pano",
            "name": "空间全景",
            "kind": "panorama",
            "description": "客厅完整全景。",
            "prompt_text": "客厅等距柱状全景。",
        },
        {
            "key": "child",
            "name": "沙发方向",
            "kind": "image",
            "description": "从全景中截取的沙发方向中景。",
            "prompt_text": "",
            "source": {
                "panorama_image_id": "pano",
                "yaw_deg": 45.0,
                "pitch_deg": -5.0,
                "hfov_deg": 70.0,
            },
        },
    )
    rig.image.size = (2048, 1024)
    panorama_asset = rig.generate_finish_select(ids["pano"])
    rig.capture(ids["child"])
    generation = rig.last(KIND.PANORAMA_CAPTURE, ids["child"])
    assert generation.panorama_capture_request == PanoramaCaptureRequest(
        panorama_asset, 45.0, -5.0, 70.0, rig.document.aspect_ratio.value
    )
    assert rig.image_row(ids["child"]).selected_asset_id is None
    rig.finish(generation.id)
    child_asset = rig.last(KIND.PANORAMA_CAPTURE, ids["child"]).output_asset_id
    assert child_asset is not None
    assert rig.image_row(ids["child"]).selected_asset_id == child_asset


def test_capture_requires_selected_panorama_and_provider(tmp_path):
    rig = Rig(tmp_path, pano=False)
    ids = rig.build(
        {
            "key": "pano",
            "name": "全景",
            "kind": "panorama",
            "description": "完整空间。",
            "prompt_text": "完整空间全景。",
        },
        {
            "key": "child",
            "name": "子图",
            "kind": "image",
            "description": "当前方向。",
            "prompt_text": "",
            "source": {
                "panorama_image_id": "pano",
                "yaw_deg": 0.0,
                "pitch_deg": 0.0,
                "hfov_deg": 60.0,
            },
        },
    )
    with pytest.raises(ValueError, match="尚未选择"):
        rig.capture(ids["child"])
    rig.image.size = (2048, 1024)
    rig.generate_finish_select(ids["pano"])
    with pytest.raises(RuntimeError, match="裁切服务"):
        rig.capture(ids["child"])


def test_invalid_panorama_candidate_cannot_be_selected(rig):
    ids = rig.build(
        {
            "key": "pano",
            "name": "全景",
            "kind": "panorama",
            "description": "完整空间。",
            "prompt_text": "完整空间全景。",
        }
    )
    rig.image.size = (1024, 576)
    rig.generate_image(ids["pano"])
    generation = rig.last(KIND.LOCATION_IMAGE, ids["pano"])
    rig.finish(generation.id)
    candidate = rig.last(KIND.LOCATION_IMAGE, ids["pano"])
    assert candidate.output_asset_id is not None
    assert rig.image_row(ids["pano"]).selected_asset_id is None
    with pytest.raises(ValueError, match="必须是 2:1"):
        rig.select_image(ids["pano"], candidate.output_asset_id)


def test_parallel_generation_is_rejected_and_failure_is_persisted(rig):
    ids = rig.build()
    rig.generate_image(ids["front"])
    with pytest.raises(ValueError, match="进行中的任务"):
        rig.generate_image(ids["front"])
    rig.finish(rig.last(KIND.LOCATION_IMAGE, ids["front"]).id)
    rig.image.reject = True
    document = rig.generate_image(ids["front"])
    assert document.generations[-1].phase is ReferenceGenerationPhase.FAILED
    assert document.generations[-1].error_code == "submission_rejected"


def test_agent_can_generate_but_cannot_select():
    assert "location.generate_image" in _AGENT_OPERATIONS
    assert "location.capture_panorama" in _AGENT_OPERATIONS
    assert "location.select_image" not in _AGENT_OPERATIONS
