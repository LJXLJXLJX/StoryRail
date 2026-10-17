"""领域模型：location 域。

地点（Location）是跨 Scene 共享的固定空间：主图给出完整空间，视图（View）是 Shot 可绑定的机位。
方位以主图为准：0° 为全景正中，顺时针递增；视图几何复用全景裁切工具的同一组范围常量。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from core.model_providers.contracts import (
    PANO_HFOV_RANGE,
    PANO_PITCH_RANGE,
    PANO_YAW_RANGE,
    validate_pano_view_geometry,
)

from ._shared import MAX_IMAGE_INPUTS, _require_id, _require_text, _validate_unique_ids

MAX_LOCATIONS = 200
MAX_LOCATION_FIXTURES = 40
MAX_LOCATION_STATES = 10
MAX_LOCATION_VIEWS = 30
# 相对陈设的偏转角；正值顺时针。
LOCATION_YAW_OFFSET_RANGE = (-180.0, 180.0)


class LocationKind(StrEnum):
    INTERIOR = "interior"
    EXTERIOR = "exterior"


def _require_degrees(
    value: float, bounds: tuple[float, float], field: str, *, include_maximum: bool
) -> None:
    minimum, maximum = bounds
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < minimum
        or (value > maximum if include_maximum else value >= maximum)
    ):
        closing = "]" if include_maximum else ")"
        raise ValueError(f"{field} 必须在 [{minimum:g}, {maximum:g}{closing} 度内。")


def _optional_azimuth(value: float | None, field: str) -> None:
    if value is not None:
        _require_degrees(value, PANO_YAW_RANGE, field, include_maximum=False)


def _optional_description(value: str, field: str, maximum: int) -> None:
    if len(value) > maximum:
        raise ValueError(f"{field} 不能超过 {maximum} 字符。")


@dataclass(frozen=True, slots=True)
class LocationFixture:
    """固定陈设；`azimuth_deg` 来自主图标定，未标定时为 None。"""

    id: str
    name: str
    description: str = ""
    azimuth_deg: float | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "location.fixture.id")
        _require_text(self.name, "location.fixture.name", 200)
        _optional_description(self.description, "location.fixture.description", 2_000)
        _optional_azimuth(self.azimuth_deg, "location.fixture.azimuth_deg")


@dataclass(frozen=True, slots=True)
class LocationKeyLight:
    description: str
    azimuth_deg: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.description, "location.key_light.description", 1_000)
        _optional_azimuth(self.azimuth_deg, "location.key_light.azimuth_deg")


@dataclass(frozen=True, slots=True)
class LocationMaster:
    """主图生成计划与人选定的主图；画幅由 Location.kind 决定。"""

    prompt_text: str = ""
    reference_asset_ids: tuple[str, ...] = ()
    selected_asset_id: str | None = None

    def __post_init__(self) -> None:
        _optional_description(self.prompt_text, "location.master.prompt_text", 19_000)
        _validate_unique_ids(self.reference_asset_ids, "location.master.reference_asset_ids")
        if len(self.reference_asset_ids) > MAX_IMAGE_INPUTS:
            raise ValueError(f"地点主图最多使用 {MAX_IMAGE_INPUTS} 张参考图。")
        if self.selected_asset_id is not None:
            _require_id(self.selected_asset_id, "location.master.selected_asset_id")


@dataclass(frozen=True, slots=True)
class LocationState:
    """同一空间的可见状态变体（例如“夜晚”“打斗后”）。"""

    id: str
    name: str
    description: str

    def __post_init__(self) -> None:
        _require_id(self.id, "location.state.id")
        _require_text(self.name, "location.state.name", 200)
        _require_text(self.description, "location.state.description", 2_000)


@dataclass(frozen=True, slots=True)
class LocationView:
    """Shot 可绑定的机位视图。

    朝向二选一：`azimuth_deg` 直接给出方位，或 `look_at_fixture_id + yaw_offset_deg` 相对陈设定义。
    画幅恒等于项目画幅。`crop_asset_id` 只属于室内视图，由 Core 按当前几何写入。
    """

    id: str
    name: str
    purpose: str
    pitch_deg: float = 0.0
    hfov_deg: float = 60.0
    azimuth_deg: float | None = None
    look_at_fixture_id: str | None = None
    yaw_offset_deg: float | None = None
    state_id: str | None = None
    refine_prompt_text: str = ""
    reference_view_ids: tuple[str, ...] = ()
    crop_asset_id: str | None = None
    selected_asset_id: str | None = None

    def __post_init__(self) -> None:
        _require_id(self.id, "location.view.id")
        _require_text(self.name, "location.view.name", 200)
        _require_text(self.purpose, "location.view.purpose", 1_000)
        relative = self.look_at_fixture_id is not None or self.yaw_offset_deg is not None
        if relative == (self.azimuth_deg is not None):
            raise ValueError(
                "视图朝向必须二选一：azimuth_deg，或 look_at_fixture_id 与 yaw_offset_deg。"
            )
        if relative:
            if self.look_at_fixture_id is None or self.yaw_offset_deg is None:
                raise ValueError(
                    "相对陈设的视图必须同时给出 look_at_fixture_id 与 yaw_offset_deg。"
                )
            _require_id(self.look_at_fixture_id, "location.view.look_at_fixture_id")
            _require_degrees(
                self.yaw_offset_deg,
                LOCATION_YAW_OFFSET_RANGE,
                "location.view.yaw_offset_deg",
                include_maximum=True,
            )
        else:
            _optional_azimuth(self.azimuth_deg, "location.view.azimuth_deg")
        _require_degrees(
            self.pitch_deg, PANO_PITCH_RANGE, "location.view.pitch_deg", include_maximum=True
        )
        _require_degrees(
            self.hfov_deg, PANO_HFOV_RANGE, "location.view.hfov_deg", include_maximum=True
        )
        if self.state_id is not None:
            _require_id(self.state_id, "location.view.state_id")
        _optional_description(self.refine_prompt_text, "location.view.refine_prompt_text", 19_000)
        _validate_unique_ids(self.reference_view_ids, "location.view.reference_view_ids")
        if self.id in self.reference_view_ids:
            raise ValueError("地点视图不能参考自身。")
        # 底图（裁切图或主图）+ 主图 + 参考视图，合计不超过单次图片调用上限。
        if len(self.reference_view_ids) + 2 > MAX_IMAGE_INPUTS:
            raise ValueError(
                f"地点视图的底图、主图与参考视图合计不能超过 {MAX_IMAGE_INPUTS} 张输入。"
            )
        for asset_id, field in (
            (self.crop_asset_id, "location.view.crop_asset_id"),
            (self.selected_asset_id, "location.view.selected_asset_id"),
        ):
            if asset_id is not None:
                _require_id(asset_id, field)


@dataclass(frozen=True, slots=True)
class LocationCropRequest:
    """一次全景裁切的冻结输入：主图快照与按当前标定解析出的绝对机位。

    裁切回调只在它仍等于视图当前的 `Location.crop_request` 时写入 `crop_asset_id`。
    """

    master_asset_id: str
    yaw_deg: float
    pitch_deg: float
    hfov_deg: float
    aspect_ratio: str

    def __post_init__(self) -> None:
        _require_id(self.master_asset_id, "location_crop_request.master_asset_id")
        validate_pano_view_geometry(self.yaw_deg, self.pitch_deg, self.hfov_deg, self.aspect_ratio)


@dataclass(frozen=True, slots=True)
class Location:
    id: str
    name: str
    kind: LocationKind
    description: str = ""
    fixtures: tuple[LocationFixture, ...] = ()
    key_light: LocationKeyLight | None = None
    master: LocationMaster = LocationMaster()
    # 标定所基于的主图；与 master.selected_asset_id 不同即视为未标定。
    calibrated_master_asset_id: str | None = None
    states: tuple[LocationState, ...] = ()
    views: tuple[LocationView, ...] = ()

    @property
    def calibrated(self) -> bool:
        return (
            self.master.selected_asset_id is not None
            and self.calibrated_master_asset_id == self.master.selected_asset_id
        )

    def view(self, view_id: str) -> LocationView | None:
        return next((item for item in self.views if item.id == view_id), None)

    def fixture(self, fixture_id: str) -> LocationFixture | None:
        return next((item for item in self.fixtures if item.id == fixture_id), None)

    def view_yaw(self, view: LocationView) -> float | None:
        """视图相对主图正中的绝对方位；相对陈设的视图在标定前或陈设无方位时为 None。"""
        if view.azimuth_deg is not None:
            return view.azimuth_deg
        fixture = None if view.look_at_fixture_id is None else self.fixture(view.look_at_fixture_id)
        if not self.calibrated or fixture is None or fixture.azimuth_deg is None:
            return None
        yaw = (fixture.azimuth_deg + (view.yaw_offset_deg or 0.0)) % 360.0
        return 0.0 if yaw >= 360.0 else yaw

    def crop_request(self, view: LocationView, aspect_ratio: str) -> LocationCropRequest | None:
        """室内视图按当前主图与几何应得的裁切输入；前置不满足时为 None。"""
        master = self.master.selected_asset_id
        yaw = self.view_yaw(view)
        if self.kind is not LocationKind.INTERIOR or master is None or yaw is None:
            return None
        return LocationCropRequest(master, yaw, view.pitch_deg, view.hfov_deg, aspect_ratio)

    def __post_init__(self) -> None:
        _require_id(self.id, "location.id")
        _require_text(self.name, "location.name", 200)
        if not isinstance(self.kind, LocationKind):
            raise ValueError("location.kind 必须是 interior 或 exterior。")
        _optional_description(self.description, "location.description", 4_000)
        if len(self.fixtures) > MAX_LOCATION_FIXTURES:
            raise ValueError(f"单个地点最多 {MAX_LOCATION_FIXTURES} 项固定陈设。")
        if len(self.states) > MAX_LOCATION_STATES:
            raise ValueError(f"单个地点最多 {MAX_LOCATION_STATES} 个状态。")
        if len(self.views) > MAX_LOCATION_VIEWS:
            raise ValueError(f"单个地点最多 {MAX_LOCATION_VIEWS} 个视图。")
        if self.calibrated_master_asset_id is not None:
            _require_id(self.calibrated_master_asset_id, "location.calibrated_master_asset_id")
        fixture_ids = {item.id for item in self.fixtures}
        state_ids = {item.id for item in self.states}
        view_ids = {item.id for item in self.views}
        if (
            len(fixture_ids) != len(self.fixtures)
            or len(state_ids) != len(self.states)
            or len(view_ids) != len(self.views)
        ):
            raise ValueError("同一地点的陈设、状态和视图 ID 不能重复。")
        for view in self.views:
            if view.look_at_fixture_id is not None and view.look_at_fixture_id not in fixture_ids:
                raise ValueError(f"视图「{view.name}」朝向的陈设不属于该地点。")
            if view.state_id is not None and view.state_id not in state_ids:
                raise ValueError(f"视图「{view.name}」的状态不属于该地点。")
            if not set(view.reference_view_ids) <= view_ids:
                raise ValueError(f"视图「{view.name}」只能参考同一地点的其它视图。")
            if view.crop_asset_id is not None and self.kind is not LocationKind.INTERIOR:
                raise ValueError("只有室内地点的视图保存全景裁切图。")
        _validate_view_graph(self.views)


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
                *(item.id for item in location.views),
            )
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("地点、陈设、状态和视图 ID 在项目内不能重复。")

    def location(self, location_id: str) -> Location | None:
        return next((item for item in self.locations if item.id == location_id), None)

    def view_owner(self, view_id: str) -> tuple[Location, LocationView] | None:
        for location in self.locations:
            view = location.view(view_id)
            if view is not None:
                return location, view
        return None


def _validate_view_graph(views: tuple[LocationView, ...]) -> None:
    view_by_id = {item.id: item for item in views}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(view_id: str) -> None:
        if view_id in visited:
            return
        if view_id in visiting:
            raise ValueError("地点视图的参考依赖不能形成环。")
        visiting.add(view_id)
        for dependency_id in view_by_id[view_id].reference_view_ids:
            visit(dependency_id)
        visiting.remove(view_id)
        visited.add(view_id)

    for item in views:
        visit(item.id)
