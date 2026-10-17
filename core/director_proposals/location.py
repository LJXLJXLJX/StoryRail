"""地点规划的专业输入与 proposal。

proposal 是增补语义：列出的地点、陈设、状态、视图按完整项新建或整体替换，
未列出的项保持不变、不删除。
新建项用局部 `key` 互相引用，已有项用正式 `id`；Core 落库时把 key 映射为正式 ID。
文字长度、角度范围与数量上限由地点领域模型在落库时统一校验，这里只校验结构与引用关系。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from core.director_commands import is_location_key

_ID = re.compile(r"[0-9a-f]{32}")


def _ref_is_valid(value: str) -> bool:
    return _ID.fullmatch(value) is not None or is_location_key(value)


@dataclass(frozen=True, slots=True)
class LocationCharacterInput:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class LocationShotInput:
    id: str
    composition: str
    camera_movement: str
    action: str
    visible_characters: tuple[LocationCharacterInput, ...]
    view_id: str | None = None


@dataclass(frozen=True, slots=True)
class LocationSceneInput:
    id: str
    title: str
    summary: str
    setting: str
    shots: tuple[LocationShotInput, ...]
    location_id: str | None = None
    state_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExistingLocationInput:
    """编译 proposal 所需的已有地点事实：项归属、当前方位与主图是否已选。"""

    id: str
    fixture_azimuths: tuple[tuple[str, float | None], ...]
    state_ids: tuple[str, ...]
    view_ids: tuple[str, ...]
    key_light_azimuth_deg: float | None
    master_selected: bool


def _identity(item_id: str | None, key: str | None, label: str) -> None:
    if (item_id is None) == (key is None):
        raise ValueError(f"{label} 必须且只能给出 id 或 key 之一。")
    if item_id is not None and not _ID.fullmatch(item_id):
        raise ValueError(f"{label}.id 必须是 32 位小写十六进制 ID。")
    if key is not None and not is_location_key(key):
        raise ValueError(
            f"{label}.key 必须是 1 到 64 位小写字母开头的 [a-z0-9_-]，且不能是 32 位 ID。"
        )


def _optional_ref(value: str | None, label: str) -> None:
    if value is not None and not _ref_is_valid(value):
        raise ValueError(f"{label} 必须是 32 位 ID 或本 proposal 新建项的 key。")


@dataclass(frozen=True, slots=True)
class LocationFixtureProposal:
    """固定陈设；`azimuth_deg` 是大致方位（0° 为全景正中，顺时针）。"""

    name: str
    description: str
    azimuth_deg: float | None
    id: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        _identity(self.id, self.key, "fixture")


@dataclass(frozen=True, slots=True)
class LocationStateProposal:
    name: str
    description: str
    id: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        _identity(self.id, self.key, "state")


@dataclass(frozen=True, slots=True)
class LocationKeyLightProposal:
    description: str
    azimuth_deg: float | None


@dataclass(frozen=True, slots=True)
class LocationViewProposal:
    name: str
    purpose: str
    azimuth_deg: float | None
    look_at_fixture_id: str | None
    yaw_offset_deg: float | None
    pitch_deg: float
    hfov_deg: float
    state_id: str | None
    refine_prompt_text: str
    reference_view_ids: tuple[str, ...]
    id: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        _identity(self.id, self.key, "view")
        _optional_ref(self.look_at_fixture_id, "view.look_at_fixture_id")
        _optional_ref(self.state_id, "view.state_id")
        for item in self.reference_view_ids:
            _optional_ref(item, "view.reference_view_ids")
        if len(self.reference_view_ids) != len(set(self.reference_view_ids)):
            raise ValueError("view.reference_view_ids 不能重复。")


@dataclass(frozen=True, slots=True)
class LocationProposal:
    name: str
    kind: Literal["interior", "exterior"]
    description: str
    key_light: LocationKeyLightProposal | None
    master_prompt_text: str
    fixtures: tuple[LocationFixtureProposal, ...]
    states: tuple[LocationStateProposal, ...]
    views: tuple[LocationViewProposal, ...]
    id: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        _identity(self.id, self.key, "location")
        for items, label in (
            (self.fixtures, "陈设"),
            (self.states, "状态"),
            (self.views, "视图"),
        ):
            ids = [item.id for item in items if item.id is not None]
            if len(ids) != len(set(ids)):
                raise ValueError(f"地点「{self.name}」的{label} id 不能重复。")
        local = {
            "fixture": {item.key for item in self.fixtures if item.key is not None},
            "state": {item.key for item in self.states if item.key is not None},
            "view": {item.key for item in self.views if item.key is not None},
        }
        for view in self.views:
            for ref, kind in (
                (view.look_at_fixture_id, "fixture"),
                (view.state_id, "state"),
                *((item, "view") for item in view.reference_view_ids),
            ):
                if ref is not None and is_location_key(ref) and ref not in local[kind]:
                    raise ValueError(
                        f"视图「{view.name}」引用的 key「{ref}」不是同一地点在本 proposal 中新建的"
                        f"{_KIND_LABELS[kind]}。"
                    )


@dataclass(frozen=True, slots=True)
class SceneLocationBindingProposal:
    """`location_id` 为 null 表示解除 Scene 的地点绑定。"""

    scene_id: str
    location_id: str | None
    state_id: str | None

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.scene_id):
            raise ValueError("scene_bindings[].scene_id 必须是 32 位 ID。")
        _optional_ref(self.location_id, "scene_bindings[].location_id")
        _optional_ref(self.state_id, "scene_bindings[].state_id")
        if self.location_id is None and self.state_id is not None:
            raise ValueError("Scene 没有绑定地点时不能指定地点状态。")


@dataclass(frozen=True, slots=True)
class ShotViewBindingProposal:
    """`view_id` 为 null 表示解除 Shot 的视图绑定。"""

    shot_id: str
    view_id: str | None

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.shot_id):
            raise ValueError("shot_bindings[].shot_id 必须是 32 位 ID。")
        _optional_ref(self.view_id, "shot_bindings[].view_id")


@dataclass(frozen=True, slots=True)
class LocationPlanProposal:
    locations: tuple[LocationProposal, ...]
    scene_bindings: tuple[SceneLocationBindingProposal, ...]
    shot_bindings: tuple[ShotViewBindingProposal, ...]

    def __post_init__(self) -> None:
        if not (self.locations or self.scene_bindings or self.shot_bindings):
            raise ValueError("地点规划 proposal 不能为空。")
        location_ids = [item.id for item in self.locations if item.id is not None]
        if len(location_ids) != len(set(location_ids)):
            raise ValueError("同一已有地点只能在 proposal 中出现一次。")
        keys = [
            item.key
            for location in self.locations
            for item in (location, *location.fixtures, *location.states, *location.views)
            if item.key is not None
        ]
        duplicated = sorted({key for key in keys if keys.count(key) > 1})
        if duplicated:
            raise ValueError(f"key 在同一 proposal 内必须唯一：{'、'.join(duplicated)}。")
        for items, field in (
            ([item.scene_id for item in self.scene_bindings], "scene_bindings"),
            ([item.shot_id for item in self.shot_bindings], "shot_bindings"),
        ):
            if len(items) != len(set(items)):
                raise ValueError(f"{field} 中同一目标只能绑定一次。")
        location_keys = {item.key for item in self.locations if item.key is not None}
        state_keys = {
            state.key: location.key or location.id
            for location in self.locations
            for state in location.states
            if state.key is not None
        }
        view_keys = {view.key for location in self.locations for view in location.views if view.key}
        for binding in self.scene_bindings:
            location = binding.location_id
            if location is not None and is_location_key(location) and location not in location_keys:
                raise ValueError(f"Scene 绑定引用了未新建的地点 key「{location}」。")
            state = binding.state_id
            if state is not None and is_location_key(state) and state_keys.get(state) != location:
                raise ValueError(f"Scene 绑定的状态 key「{state}」不属于所绑定的地点。")
        for binding in self.shot_bindings:
            view = binding.view_id
            if view is not None and is_location_key(view) and view not in view_keys:
                raise ValueError(f"Shot 绑定引用了未新建的视图 key「{view}」。")


_KIND_LABELS = {"fixture": "陈设", "state": "状态", "view": "视图"}
