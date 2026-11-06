"""地点语义与独立图片条目的专业输入和增补 proposal。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.director_commands import is_location_key

_ID = re.compile(r"[0-9a-f]{32}")


def _valid_ref(value: str) -> bool:
    return _ID.fullmatch(value) is not None or is_location_key(value)


def _identity(item_id: str | None, key: str | None, label: str) -> None:
    if (item_id is None) == (key is None):
        raise ValueError(f"{label} 必须且只能给出 id 或 key 之一。")
    if item_id is not None and not _ID.fullmatch(item_id):
        raise ValueError(f"{label}.id 不合法。")
    if key is not None and not is_location_key(key):
        raise ValueError(f"{label}.key 不合法。")


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
    id: str
    fixture_ids: tuple[str, ...]
    state_ids: tuple[str, ...]
    image_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LocationFixtureProposal:
    name: str
    description: str
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


@dataclass(frozen=True, slots=True)
class PanoramaCaptureSourceProposal:
    panorama_image_id: str
    yaw_deg: float
    pitch_deg: float
    hfov_deg: float

    def __post_init__(self) -> None:
        if not _valid_ref(self.panorama_image_id):
            raise ValueError("panorama_image_id 必须是正式 ID 或本 proposal 的 key。")


@dataclass(frozen=True, slots=True)
class LocationImageProposal:
    name: str
    kind: str
    description: str
    prompt_text: str
    reference_asset_ids: tuple[str, ...]
    source: PanoramaCaptureSourceProposal | None
    id: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        _identity(self.id, self.key, "image")
        if self.kind not in {"image", "panorama"}:
            raise ValueError("地点图片 kind 必须是 image 或 panorama。")
        if not self.description.strip():
            raise ValueError("地点图片必须填写实际内容说明。")
        if self.source is not None and self.kind != "image":
            raise ValueError("只有普通地点图片可以记录全景取景来源。")


@dataclass(frozen=True, slots=True)
class LocationProposal:
    name: str
    description: str
    key_light: LocationKeyLightProposal | None
    fixtures: tuple[LocationFixtureProposal, ...]
    states: tuple[LocationStateProposal, ...]
    images: tuple[LocationImageProposal, ...]
    id: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        _identity(self.id, self.key, "location")
        local_images = {item.key for item in self.images if item.key is not None}
        for image in self.images:
            if (
                image.source is not None
                and is_location_key(image.source.panorama_image_id)
                and image.source.panorama_image_id not in local_images
            ):
                raise ValueError("全景取景来源 key 必须是同一地点本 proposal 新建的图片。")


@dataclass(frozen=True, slots=True)
class SceneLocationBindingProposal:
    scene_id: str
    location_id: str | None
    state_id: str | None

    def __post_init__(self) -> None:
        if not _ID.fullmatch(self.scene_id):
            raise ValueError("scene_id 不合法。")
        if self.location_id is not None and not _valid_ref(self.location_id):
            raise ValueError("location_id 不合法。")
        if self.state_id is not None and not _valid_ref(self.state_id):
            raise ValueError("state_id 不合法。")
        if self.location_id is None and self.state_id is not None:
            raise ValueError("Scene 未选择地点时不能指定状态。")


@dataclass(frozen=True, slots=True)
class LocationPlanProposal:
    locations: tuple[LocationProposal, ...]
    scene_bindings: tuple[SceneLocationBindingProposal, ...]

    def __post_init__(self) -> None:
        if not (self.locations or self.scene_bindings):
            raise ValueError("地点规划 proposal 不能为空。")
        keys = [
            item.key
            for location in self.locations
            for item in (location, *location.fixtures, *location.states, *location.images)
            if item.key is not None
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("同一 proposal 的局部 key 不能重复。")
