"""地点库领域模型。

Location 只保存跨 Scene 共享的语义事实与独立图片条目。图片不构成主图/视图树，
也不被 Shot 或 Keyframe 绑定。全景图只是可在查看器中取景的特殊图片类型；
取景结果保存来源快照，但生成后是独立的普通图片。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.model_providers.contracts import validate_pano_view_geometry

from ._shared import MAX_IMAGE_INPUTS, _require_id, _require_text, _validate_unique_ids

MAX_LOCATIONS = 200
MAX_LOCATION_FIXTURES = 40
MAX_LOCATION_STATES = 10
MAX_LOCATION_IMAGES = 200


def _optional_description(value: str, field: str, maximum: int) -> None:
    if len(value) > maximum:
        raise ValueError(f"{field} 不能超过 {maximum} 字符。")


class LocationImageKind(StrEnum):
    IMAGE = "image"
    PANORAMA = "panorama"


@dataclass(frozen=True, slots=True)
class LocationFixture:
    """地点中稳定存在的陈设；不保存相对于某张图片的方位。"""

    id: str
    name: str
    description: str = ""

    def __post_init__(self) -> None:
        _require_id(self.id, "location.fixture.id")
        _require_text(self.name, "location.fixture.name", 200)
        _optional_description(self.description, "location.fixture.description", 2_000)


@dataclass(frozen=True, slots=True)
class LocationKeyLight:
    description: str

    def __post_init__(self) -> None:
        _require_text(self.description, "location.key_light.description", 1_000)


@dataclass(frozen=True, slots=True)
class LocationState:
    """同一空间的语义状态（例如“夜晚”“打斗后”）。"""

    id: str
    name: str
    description: str

    def __post_init__(self) -> None:
        _require_id(self.id, "location.state.id")
        _require_text(self.name, "location.state.name", 200)
        _require_text(self.description, "location.state.description", 2_000)


@dataclass(frozen=True, slots=True)
class PanoramaCaptureSource:
    """普通图片从全景图取景时冻结的来源；只记录 provenance，不形成活依赖。"""

    panorama_image_id: str
    yaw_deg: float
    pitch_deg: float
    hfov_deg: float

    def __post_init__(self) -> None:
        _require_id(self.panorama_image_id, "location.image.source.panorama_image_id")
        # 画幅由项目在提交时补入；这里只复用相同的角度边界。
        validate_pano_view_geometry(self.yaw_deg, self.pitch_deg, self.hfov_deg, "16:9")


@dataclass(frozen=True, slots=True)
class PanoramaCaptureRequest:
    """一次确定性全景取景冻结的媒体输入。"""

    panorama_asset_id: str
    yaw_deg: float
    pitch_deg: float
    hfov_deg: float
    aspect_ratio: str

    def __post_init__(self) -> None:
        _require_id(self.panorama_asset_id, "panorama_capture_request.panorama_asset_id")
        validate_pano_view_geometry(
            self.yaw_deg,
            self.pitch_deg,
            self.hfov_deg,
            self.aspect_ratio,
        )

    @property
    def master_asset_id(self) -> str:
        """媒体协议沿用的输入名；语义上是被取景的全景图片 Asset。"""
        return self.panorama_asset_id


@dataclass(frozen=True, slots=True)
class LocationImage:
    """地点中的独立图片条目。

    `description` 是人或 Agent 根据实际画面填写的强制纯文本说明。`prompt_text`
    与 `reference_asset_ids` 只描述下一次生成计划；候选采用后写入
    `selected_asset_id`。全景取景产生的普通图片保存 `source`，但不会随父图变化
    或移除而失效。
    """

    id: str
    name: str
    kind: LocationImageKind
    description: str
    prompt_text: str = ""
    reference_asset_ids: tuple[str, ...] = ()
    selected_asset_id: str | None = None
    source: PanoramaCaptureSource | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "location.image.id")
        _require_text(self.name, "location.image.name", 200)
        if not isinstance(self.kind, LocationImageKind):
            raise ValueError("location.image.kind 必须是 image 或 panorama。")
        _require_text(self.description, "location.image.description", 4_000)
        _optional_description(self.prompt_text, "location.image.prompt_text", 19_000)
        _validate_unique_ids(self.reference_asset_ids, "location.image.reference_asset_ids")
        if len(self.reference_asset_ids) > MAX_IMAGE_INPUTS:
            raise ValueError(f"地点图片最多使用 {MAX_IMAGE_INPUTS} 张参考图。")
        if self.selected_asset_id is not None:
            _require_id(self.selected_asset_id, "location.image.selected_asset_id")
        if self.source is not None and self.kind is not LocationImageKind.IMAGE:
            raise ValueError("只有普通地点图片可以记录全景取景来源。")


@dataclass(frozen=True, slots=True)
class Location:
    id: str
    name: str
    description: str = ""
    fixtures: tuple[LocationFixture, ...] = ()
    key_light: LocationKeyLight | None = None
    states: tuple[LocationState, ...] = ()
    images: tuple[LocationImage, ...] = ()

    def image(self, image_id: str) -> LocationImage | None:
        return next((item for item in self.images if item.id == image_id), None)

    def fixture(self, fixture_id: str) -> LocationFixture | None:
        return next((item for item in self.fixtures if item.id == fixture_id), None)

    def __post_init__(self) -> None:
        _require_id(self.id, "location.id")
        _require_text(self.name, "location.name", 200)
        _optional_description(self.description, "location.description", 4_000)
        if len(self.fixtures) > MAX_LOCATION_FIXTURES:
            raise ValueError(f"单个地点最多 {MAX_LOCATION_FIXTURES} 项固定陈设。")
        if len(self.states) > MAX_LOCATION_STATES:
            raise ValueError(f"单个地点最多 {MAX_LOCATION_STATES} 个状态。")
        if len(self.images) > MAX_LOCATION_IMAGES:
            raise ValueError(f"单个地点最多 {MAX_LOCATION_IMAGES} 张图片。")
        fixture_ids = {item.id for item in self.fixtures}
        state_ids = {item.id for item in self.states}
        image_ids = {item.id for item in self.images}
        if (
            len(fixture_ids) != len(self.fixtures)
            or len(state_ids) != len(self.states)
            or len(image_ids) != len(self.images)
        ):
            raise ValueError("同一地点的陈设、状态和图片 ID 不能重复。")


@dataclass(frozen=True, slots=True)
class LocationLibrary:
    locations: tuple[Location, ...] = ()

    def __post_init__(self) -> None:
        if len(self.locations) > MAX_LOCATIONS:
            raise ValueError(f"项目最多 {MAX_LOCATIONS} 个地点。")
        ids = [
            item_id
            for location in self.locations
            for item_id in (
                location.id,
                *(item.id for item in location.fixtures),
                *(item.id for item in location.states),
                *(item.id for item in location.images),
            )
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("地点、陈设、状态和图片 ID 在项目内不能重复。")

    def location(self, location_id: str) -> Location | None:
        return next((item for item in self.locations if item.id == location_id), None)

    def image_owner(self, image_id: str) -> tuple[Location, LocationImage] | None:
        for location in self.locations:
            image = location.image(image_id)
            if image is not None:
                return location, image
        return None

    def selected_image_asset(self, image_id: str) -> str | None:
        owner = self.image_owner(image_id)
        return None if owner is None else owner[1].selected_asset_id
