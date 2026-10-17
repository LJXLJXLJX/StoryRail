"""地点主图与视图生成：前置拒绝、主图画幅与全景写法、室内先裁切后细化、裁切过期丢弃、
室外 edit 转向、输入映射与名额、候选选择规则、重试、seed 与 provider_snapshot。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from structured_director_fixtures import png_header_bytes
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
from core.model_providers.codex_image.manifest import MANIFEST as CODEX_MANIFEST
from core.model_providers.qwen_image import MANIFEST as QWEN_MANIFEST
from core.model_providers.qwen_image.plugin import format_prompt_workset
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.structured_director import StructuredDirectorHttpApi, StructuredDirectorService
from core.structured_director.image_inputs import ImageInput, ordered_image_inputs
from core.structured_director.models import (
    GenerationOperation,
    LocationCropRequest,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)
from core.structured_director.mutations.generation import complete_generation_document
from integrations.storyrail_mcp.production_tools import MODELS, translate

KIND = ReferenceGenerationKind


class FakeImage:
    """图片插件替身：按提交记录 RecipeRequest，观察即成功并返回指定尺寸的 PNG 头。"""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.plugin_version = 1
        self.requests = []
        self.size = (2048, 1024)
        self.reject = False
        self._outputs: dict[str, bytes] = {}

    def submit_recipe(self, request):
        self.requests.append(request)
        if self.reject:
            raise ModelProviderError("external_error", "服务拒绝。")
        external_id = f"img-{len(self.requests)}"
        self._outputs[external_id] = png_header_bytes(external_id, *self.size)
        return ProviderHandle(self.plugin_id, 1, external_id)

    def observe(self, handle):
        content = self._outputs[handle.external_id]
        return GenerationObservation(
            GenerationPhase.SUCCEEDED,
            1.0,
            "完成",
            ArtifactDescriptor(
                handle.external_id, "image/png", len(content), hashlib.sha256(content).hexdigest()
            ),
        )

    def cancel(self, handle):
        return GenerationObservation(GenerationPhase.CANCELLED, 0.0, "已取消")

    def read_artifact(self, handle, artifact_id):
        return self._outputs[handle.external_id]


class FakePano(FakeImage):
    def __init__(self) -> None:
        super().__init__("ffmpeg.pano_view")
        self.size = (2048, 1152)
        self.fail_next = False

    def submit(self, request):
        if self.fail_next:
            self.fail_next = False
            self.requests.append(request)
            raise ModelProviderError("transport_error", "测试传输失败")
        return self.submit_recipe(request)


class Rig:
    """空项目 + 正式地点命令；Qwen（声明 seed、`<imageN>`、不写画幅句）或 Codex 图片插件。"""

    def __init__(self, tmp_path: Path, *, manifest=QWEN_MANIFEST, pano: bool = True) -> None:
        directory = tmp_path / uuid4().hex
        directory.mkdir()
        self.store, _service, _document, _route = asyncio.run(_visual_project(str(directory)))
        self.image = FakeImage(f"{manifest.recipes[0].id.split('.')[0]}.fake")
        self.pano = FakePano()
        registry = ProviderRegistry()
        registry.install(
            PluginInstance(
                manifest,
                recipes={recipe.id: self.image for recipe in manifest.recipes},
                prompt_formatter=format_prompt_workset if manifest is QWEN_MANIFEST else None,
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

    def build(self, kind: str = "interior", *views: dict) -> dict[str, str]:
        views = views or (
            {"key": "front", "name": "正打", "purpose": "朝壁炉·人眼高·中景", "azimuth_deg": 90.0},
        )
        execution = self.run(
            "location.apply_operations",
            {
                "scope": {"location_ids": [], "scene_ids": [], "shot_ids": []},
                "operations": [
                    {
                        "op": "create_location",
                        "key": "room",
                        "name": "客厅",
                        "kind": kind,
                        "description": "木地板、白墙、暖色调。",
                    },
                    {
                        "op": "update_location",
                        "location_id": "room",
                        "fields": {
                            "master_prompt_text": "温暖的老式客厅。",
                            "key_light": {"description": "壁炉火光", "azimuth_deg": 90.0},
                        },
                    },
                    {
                        "op": "upsert_fixture",
                        "location_id": "room",
                        "fixture": "fireplace",
                        "name": "壁炉",
                        "description": "石砌壁炉",
                        "azimuth_deg": None,
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
                            "op": "create_view",
                            "location_id": "room",
                            "key": view["key"],
                            "fields": {k: v for k, v in view.items() if k != "key"},
                        }
                        for view in views
                    ),
                ],
            },
        )
        return execution.data["created_ids"]

    def generate_master(self, location_id: str):
        return asyncio.run(
            self.service.generate_location_master(
                location_id=location_id, expected_revision=self.document.revision
            )
        )

    def generate_view(self, view_id: str):
        return asyncio.run(
            self.service.generate_location_view(
                view_id=view_id, expected_revision=self.document.revision
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

    def select_master(self, location_id: str, asset_id: str):
        return self.run(
            "location.select_master", {"location_id": location_id, "asset_id": asset_id}
        )

    def select_view(self, view_id: str, asset_id: str):
        return self.run("location.select_view", {"view_id": view_id, "asset_id": asset_id})

    def master_ready(self, location_id: str) -> str:
        self.generate_master(location_id)
        generation = self.finish(self.last(KIND.LOCATION_MASTER_IMAGE, location_id).id)
        asset_id = self.last(KIND.LOCATION_MASTER_IMAGE, location_id).output_asset_id
        del generation
        self.select_master(location_id, asset_id)
        return asset_id

    def view(self, view_id: str):
        return self.document.location_library.view_owner(view_id)[1]


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


# --- 主图 ---


def test_interior_master_is_2_1_panorama_with_fixture_directions(rig):
    created = rig.build("interior")
    location_id = created["room"]
    rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [location_id], "scene_ids": [], "shot_ids": []},
            "operations": [
                {
                    "op": "upsert_fixture",
                    "location_id": location_id,
                    "fixture": created["fireplace"],
                    "name": "壁炉",
                    "description": "石砌壁炉",
                    "azimuth_deg": 90.0,
                }
            ],
        },
    )
    rig.generate_master(location_id)
    generation = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id)
    request = rig.image.requests[-1]
    assert generation.target_id == location_id
    assert generation.operation is GenerationOperation.GENERATE
    assert generation.aspect_ratio == "2:1" == request.param("aspect_ratio")
    assert generation.provider_snapshot is not None
    assert generation.provider_snapshot.recipe_id == "qwen_image.generate"
    assert generation.seed is not None
    prompt = request.param("prompt")
    for phrase in ("等距柱状投影", "不得出现任何人物", "左右边缘必须无缝衔接", "温暖的老式客厅"):
        assert phrase in prompt
    assert "- 壁炉：右侧，方位 90°；石砌壁炉" in prompt
    assert "主光：壁炉火光（来自右侧，方位 90°）" in prompt
    # Qwen 由画布保证画幅，不写画幅句。
    assert "固定画幅" not in prompt


def test_exterior_master_follows_project_aspect_and_codex_writes_aspect_once(tmp_path):
    rig = Rig(tmp_path, manifest=CODEX_MANIFEST)
    location_id = rig.build("exterior")["room"]
    rig.generate_master(location_id)
    generation = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id)
    request = rig.image.requests[-1]
    assert generation.aspect_ratio is None
    assert request.param("aspect_ratio") == "16:9"
    prompt = request.param("prompt")
    assert prompt.count("16:9") == 1 and "固定画幅：16:9。" in prompt
    assert "等距柱状" not in prompt
    assert generation.seed is None  # Codex 不声明 Seed


def test_master_requires_prompt_and_rejects_parallel_task(rig):
    location_id = rig.build()["room"]
    rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [location_id], "scene_ids": [], "shot_ids": []},
            "operations": [
                {
                    "op": "update_location",
                    "location_id": location_id,
                    "fields": {"master_prompt_text": ""},
                }
            ],
        },
    )
    with pytest.raises(ValueError, match="主图提示词"):
        rig.generate_master(location_id)
    rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [location_id], "scene_ids": [], "shot_ids": []},
            "operations": [
                {
                    "op": "update_location",
                    "location_id": location_id,
                    "fields": {"master_prompt_text": "客厅。"},
                }
            ],
        },
    )
    rig.generate_master(location_id)
    with pytest.raises(ValueError, match="进行中的主图任务"):
        rig.generate_master(location_id)


def test_master_callback_only_saves_candidate_and_seed_advances(rig):
    location_id = rig.build()["room"]
    rig.generate_master(location_id)
    first = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id)
    rig.finish(first.id)
    location = rig.document.location_library.location(location_id)
    assert location.master.selected_asset_id is None
    rig.generate_master(location_id)
    second = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id)
    assert second.seed == first.seed + 1


# --- 选择规则 ---


def test_selection_requires_own_successful_visible_candidate(rig):
    created = rig.build()
    location_id, view_id = created["room"], created["front"]
    rig.generate_master(location_id)
    generation = rig.finish(rig.last(KIND.LOCATION_MASTER_IMAGE, location_id).id)
    candidate = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id)
    del generation
    with pytest.raises(ValueError, match="主图候选"):
        rig.select_master(location_id, uuid4().hex)
    with pytest.raises(ValueError, match="视图成功且未隐藏"):
        rig.select_view(view_id, candidate.output_asset_id)
    rig.run("generation.dismiss", {"generation_id": candidate.id})
    with pytest.raises(ValueError, match="主图候选"):
        rig.select_master(location_id, candidate.output_asset_id)


def test_interior_master_selection_requires_2_1_panorama(rig):
    location_id = rig.build()["room"]
    rig.image.size = (1920, 1080)
    rig.generate_master(location_id)
    rig.finish(rig.last(KIND.LOCATION_MASTER_IMAGE, location_id).id)
    asset_id = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id).output_asset_id
    with pytest.raises(ValueError, match="2:1 等距柱状全景"):
        rig.select_master(location_id, asset_id)


def test_exterior_master_selection_accepts_project_aspect(rig):
    location_id = rig.build("exterior")["room"]
    rig.image.size = (1920, 1080)
    asset_id = rig.master_ready(location_id)
    assert rig.document.location_library.location(location_id).master.selected_asset_id == asset_id


# --- 室内视图：先裁切，再显式细化 ---


def test_view_rejected_before_master_and_for_uncalibrated_fixture(rig):
    created = rig.build(
        "interior",
        {"key": "front", "name": "正打", "purpose": "中景", "azimuth_deg": 0.0},
        {
            "key": "fire",
            "name": "壁炉",
            "purpose": "朝壁炉",
            "look_at_fixture_id": "fireplace",
            "yaw_offset_deg": 10.0,
        },
    )
    with pytest.raises(ValueError, match="请先选择地点「客厅」的主图"):
        rig.generate_view(created["front"])
    rig.master_ready(created["room"])
    with pytest.raises(ValueError, match="尚未在当前主图上标定方位"):
        rig.generate_view(created["fire"])
    assert rig.pano.requests == []


def test_interior_view_crops_first_then_refines_on_explicit_call(rig):
    created = rig.build()
    location_id, view_id = created["room"], created["front"]
    master = rig.master_ready(location_id)
    image_requests = len(rig.image.requests)

    document = rig.generate_view(view_id)
    crop = rig.last(KIND.LOCATION_VIEW_CROP, view_id)
    assert len(rig.image.requests) == image_requests  # 只提交裁切
    assert crop.operation is GenerationOperation.PROCESS
    assert crop.location_crop_request == LocationCropRequest(master, 90.0, 0.0, 60.0, "16:9")
    assert crop.input_asset_ids == (master,)
    assert crop.provider_snapshot is None and crop.seed is None
    assert "裁切进行中" in crop.message
    request = rig.pano.requests[-1]
    assert (request.yaw_deg, request.pitch_deg, request.hfov_deg, request.aspect_ratio) == (
        90.0,
        0.0,
        60.0,
        "16:9",
    )
    assert rig.view(view_id).crop_asset_id is None
    with pytest.raises(ValueError, match="进行中的生成任务"):
        rig.generate_view(view_id)

    document = rig.finish(crop.id)
    crop_asset = rig.last(KIND.LOCATION_VIEW_CROP, view_id).output_asset_id
    assert rig.view(view_id).crop_asset_id == crop_asset
    assert len(rig.image.requests) == image_requests  # 回调不续提交细化
    assert not any(item.kind is KIND.LOCATION_VIEW_IMAGE for item in document.generations)
    asset = next(item for item in document.assets if item.id == crop_asset)
    assert asset.relative_path.startswith("assets/images/locations/crops/")

    rig.generate_view(view_id)
    refine = rig.last(KIND.LOCATION_VIEW_IMAGE, view_id)
    request = rig.image.requests[-1]
    assert refine.operation is GenerationOperation.EDIT
    assert refine.input_asset_ids == (crop_asset,)  # 细化只提交裁切底图，不带全景主图
    assert [item.content for item in request.slot("source_image")] == [
        rig.store.read_asset(crop_asset)[1]
    ]
    assert not request.slot("reference_image")
    prompt = request.param("prompt")
    assert prompt.startswith("输入图对应关系")
    assert prompt.index("图片「地点-客厅-正打-裁切.png」") < prompt.index("修复全景裁切底图")
    for required in (
        "重点解决等距柱状全景转为透视图后产生的空间扭曲",
        "建筑结构或直线弯曲",
        "画面边缘拉伸",
        "物体比例失衡",
        "恢复为可信的单一透视",
        "允许对物体轮廓、局部尺度和边缘位置作必要调整",
        "不得改变空间布局",
        "不得出现任何人物、文字或水印",
    ):
        assert required in prompt
    assert "<image" not in prompt and "地点主图硬约束" not in prompt
    # 细化只修复裁切底图：不附空间描述、陈设清单、purpose 或正文，避免编辑模型重画空间
    for absent in ("固定空间", "视图用途", "壁炉", "主光", "正文"):
        assert absent not in prompt
    assert refine.provider_snapshot.recipe_id == "qwen_image.edit"

    rig.finish(refine.id)
    candidate = rig.last(KIND.LOCATION_VIEW_IMAGE, view_id).output_asset_id
    assert rig.view(view_id).selected_asset_id is None  # 不自动选择
    rig.select_view(view_id, candidate)
    assert rig.view(view_id).selected_asset_id == candidate


def test_late_crop_result_is_history_only_when_geometry_changed(rig):
    created = rig.build()
    location_id, view_id = created["room"], created["front"]
    rig.master_ready(location_id)
    rig.generate_view(view_id)
    crop = rig.last(KIND.LOCATION_VIEW_CROP, view_id)
    # 绕过进行中保护模拟几何已变化：结果到达时快照不再等于当前值。
    document = rig.document
    location = document.location_library.location(location_id)
    view = replace(location.view(view_id), pitch_deg=-10.0)
    library = replace(
        document.location_library,
        locations=(replace(location, views=(view,)),),
    )
    rig.store._atomic_write(
        replace(document, revision=document.revision + 1, location_library=library)
    )
    document = rig.finish(crop.id)
    finished = rig.last(KIND.LOCATION_VIEW_CROP, view_id)
    assert finished.phase is ReferenceGenerationPhase.SUCCEEDED
    assert rig.view(view_id).crop_asset_id is None
    # 再次生成视图会按新几何重新裁切。
    rig.generate_view(view_id)
    assert rig.last(KIND.LOCATION_VIEW_CROP, view_id).location_crop_request.pitch_deg == -10.0


def test_crop_callback_discards_result_for_reselected_master(rig):
    created = rig.build()
    location_id, view_id = created["room"], created["front"]
    master = rig.master_ready(location_id)
    rig.generate_master(location_id)
    rig.finish(rig.last(KIND.LOCATION_MASTER_IMAGE, location_id).id)
    other_master = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id).output_asset_id
    rig.generate_view(view_id)
    queued = rig.last(KIND.LOCATION_VIEW_CROP, view_id)
    document = rig.document
    location = document.location_library.location(location_id)
    reselected = replace(location, master=replace(location.master, selected_asset_id=other_master))
    stale = replace(
        document, location_library=replace(document.location_library, locations=(reselected,))
    )
    timestamp = "2099-01-01T00:00:00+00:00"
    completed = complete_generation_document(stale, queued, asset_id=master, timestamp=timestamp)
    assert completed.location_library.view_owner(view_id)[1].crop_asset_id is None
    current = complete_generation_document(document, queued, asset_id=master, timestamp=timestamp)
    assert current.location_library.view_owner(view_id)[1].crop_asset_id == master


def test_reference_views_follow_master_and_must_be_selected(rig):
    created = rig.build(
        "interior",
        {"key": "front", "name": "正打", "purpose": "中景", "azimuth_deg": 0.0},
        {
            "key": "back",
            "name": "反打",
            "purpose": "背面中景",
            "azimuth_deg": 180.0,
            "state_id": "night",
            "refine_prompt_text": "夜色更深。",
            "reference_view_ids": ["front"],
        },
    )
    location_id, front, back = created["room"], created["front"], created["back"]
    rig.master_ready(location_id)
    with pytest.raises(ValueError, match="参考视图「正打」尚未选择图片"):
        rig.generate_view(back)
    for view_id in (front,):
        rig.generate_view(view_id)
        rig.finish(rig.last(KIND.LOCATION_VIEW_CROP, view_id).id)
        rig.generate_view(view_id)
        rig.finish(rig.last(KIND.LOCATION_VIEW_IMAGE, view_id).id)
        rig.select_view(view_id, rig.last(KIND.LOCATION_VIEW_IMAGE, view_id).output_asset_id)
    rig.generate_view(back)
    rig.finish(rig.last(KIND.LOCATION_VIEW_CROP, back).id)
    rig.generate_view(back)
    refine = rig.last(KIND.LOCATION_VIEW_IMAGE, back)
    assert refine.input_asset_ids == (
        rig.view(back).crop_asset_id,
        rig.view(front).selected_asset_id,
    )
    prompt = refine.prompt_text
    assert "<image2>「" in prompt and "已选定的视图「正打」" in prompt
    assert prompt.endswith(
        "本视图状态「夜晚」：只有火光。（只在底图上叠加该状态的可见差量，构图不变）"
    )
    assert "夜色更深" not in prompt  # 室内不使用 refine_prompt_text


def test_input_quota_lists_squeezed_inputs(rig):
    document = rig.document
    entries = [ImageInput(uuid4().hex, f"参考{index}", f"输入{index}") for index in range(7)]
    with pytest.raises(
        ValueError, match="合计 7 张输入图，超过上限 5 张；会被挤掉的输入："
    ) as error:
        ordered_image_inputs(
            document, entries, operation=GenerationOperation.EDIT, label="视图「正打」"
        )
    message = str(error.value)
    assert f"「{entries[5].asset_id}」（参考5）、「{entries[6].asset_id}」（参考6）" in message
    assert entries[4].asset_id not in message


# --- 室外：edit 转向 ---


def test_exterior_view_turns_master_with_core_angle_and_shot_size(tmp_path):
    rig = Rig(tmp_path, manifest=CODEX_MANIFEST, pano=False)
    created = rig.build(
        "exterior",
        {"key": "left", "name": "街口", "purpose": "远景", "azimuth_deg": 300.0, "hfov_deg": 100.0},
    )
    rig.image.size = (1920, 1080)
    master = rig.master_ready(created["room"])
    rig.generate_view(created["left"])
    generation = rig.last(KIND.LOCATION_VIEW_IMAGE, created["left"])
    request = rig.image.requests[-1]
    assert generation.operation is GenerationOperation.EDIT
    assert generation.input_asset_ids == (master,)
    assert not any(item.kind is KIND.LOCATION_VIEW_CROP for item in rig.document.generations)
    prompt = request.param("prompt")
    assert "第 1 张输入图「" in prompt and "机位转向以它为基准" in prompt
    assert "机位相对主图：水平向左转 60°，平视；景别：广角远景（水平视场角约 100°）。" in prompt
    assert prompt.count("固定画幅：16:9。") == 1


# --- 重试 ---


def test_master_retry_keeps_seed_and_links_retry_of(rig):
    location_id = rig.build()["room"]
    rig.image.reject = True
    rig.generate_master(location_id)
    failed = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id)
    assert failed.phase is ReferenceGenerationPhase.FAILED
    rig.image.reject = False
    asyncio.run(rig.service.retry_generation(failed.id, expected_revision=rig.document.revision))
    retried = rig.last(KIND.LOCATION_MASTER_IMAGE, location_id)
    assert retried.id != failed.id
    assert (retried.retry_of, retried.seed, retried.aspect_ratio) == (failed.id, failed.seed, "2:1")


def test_crop_and_refine_retry_create_new_generations(rig):
    created = rig.build()
    location_id, view_id = created["room"], created["front"]
    rig.master_ready(location_id)
    rig.pano.fail_next = True
    rig.generate_view(view_id)
    uncertain = rig.last(KIND.LOCATION_VIEW_CROP, view_id)
    assert uncertain.phase is ReferenceGenerationPhase.SUBMISSION_UNCERTAIN
    asyncio.run(rig.service.retry_generation(uncertain.id, expected_revision=rig.document.revision))
    crop = rig.last(KIND.LOCATION_VIEW_CROP, view_id)
    assert crop.retry_of == uncertain.id
    assert crop.location_crop_request == uncertain.location_crop_request
    rig.finish(crop.id)

    rig.image.reject = True
    rig.generate_view(view_id)
    failed = rig.last(KIND.LOCATION_VIEW_IMAGE, view_id)
    rig.image.reject = False
    asyncio.run(rig.service.retry_generation(failed.id, expected_revision=rig.document.revision))
    retried = rig.last(KIND.LOCATION_VIEW_IMAGE, view_id)
    assert (retried.retry_of, retried.seed, retried.input_asset_ids) == (
        failed.id,
        failed.seed,
        failed.input_asset_ids,
    )


def test_crop_request_round_trips_through_project_json(rig):
    created = rig.build()
    rig.master_ready(created["room"])
    rig.generate_view(created["front"])
    crop = rig.last(KIND.LOCATION_VIEW_CROP, created["front"])
    raw = json.loads((rig.store._project_directory / "project.json").read_text(encoding="utf-8"))
    stored = next(item for item in raw["generations"] if item["id"] == crop.id)
    assert stored["location_crop_request"]["yaw_deg"] == 90.0
    image = next(item for item in raw["generations"] if item["kind"] == "location_master_image")
    assert "location_crop_request" not in image
    assert rig.store.read().generations == rig.document.generations


def test_missing_pano_provider_is_reported(tmp_path):
    rig = Rig(tmp_path, pano=False)
    created = rig.build()
    rig.master_ready(created["room"])
    with pytest.raises(RuntimeError, match="全景裁切服务尚未配置"):
        rig.generate_view(created["front"])


# --- 入口 ---


def test_agent_may_generate_but_not_select():
    assert {"location.generate_master", "location.generate_view"} <= _AGENT_OPERATIONS
    assert not {"location.select_master", "location.select_view"} & _AGENT_OPERATIONS


def test_mcp_generate_media_translates_location_kinds():
    target = "a" * 32
    for kind, command, field in (
        ("location_master", "location.generate_master", "location_id"),
        ("location_view", "location.generate_view", "view_id"),
    ):
        request = MODELS["generate_media"].model_validate(
            {
                "project_id": target,
                "expected_revision": 3,
                "idempotency_key": "k",
                "kind": kind,
                "target_id": target,
            }
        )
        assert translate("generate_media", request) == (command, {field: target})


def test_location_receipts_offer_generation_actions(rig):
    execution = rig.run(
        "location.apply_operations",
        {
            "scope": {"location_ids": [], "scene_ids": [], "shot_ids": []},
            "operations": [
                {
                    "op": "create_location",
                    "key": "x",
                    "name": "x",
                    "kind": "exterior",
                    "description": "",
                }
            ],
        },
    )
    assert execution.receipt.next_allowed_actions == (
        "location.generate_master",
        "location.generate_view",
    )


def test_http_card_buttons_submit_single_target(rig):
    created = rig.build()
    api = StructuredDirectorHttpApi(rig.service, resource_path="/r", store=rig.store)
    response = asyncio.run(
        api.handle(
            "POST",
            f"/r/locations/{created['room']}/master/generate",
            json.dumps({"expected_revision": rig.document.revision}).encode(),
        )
    )
    assert response.status == 202
    generation = rig.last(KIND.LOCATION_MASTER_IMAGE, created["room"])
    rig.finish(generation.id)
    rig.select_master(
        created["room"], rig.last(KIND.LOCATION_MASTER_IMAGE, created["room"]).output_asset_id
    )
    response = asyncio.run(
        api.handle(
            "POST",
            f"/r/location-views/{created['front']}/generate",
            json.dumps({"expected_revision": rig.document.revision}).encode(),
        )
    )
    assert response.status == 202
    assert (
        rig.last(KIND.LOCATION_VIEW_CROP, created["front"]).phase is ReferenceGenerationPhase.QUEUED
    )
