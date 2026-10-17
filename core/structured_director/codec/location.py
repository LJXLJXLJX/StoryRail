"""文档编解码：location 域的 parse/serialize 函数对；未声明字段一律拒绝。"""

from __future__ import annotations

from typing import Any

from ..models import (
    Location,
    LocationFixture,
    LocationKeyLight,
    LocationKind,
    LocationLibrary,
    LocationMaster,
    LocationState,
    LocationView,
)
from ._shared import (
    _exact_object,
    _number,
    _object_list,
    _optional_number,
    _optional_string,
    _string,
    _string_list,
)

_LIBRARY_FIELDS = {"locations"}
_LOCATION_FIELDS = {
    "id",
    "name",
    "kind",
    "description",
    "fixtures",
    "key_light",
    "master",
    "calibrated_master_asset_id",
    "states",
    "views",
}
_FIXTURE_FIELDS = {"id", "name", "description", "azimuth_deg"}
_KEY_LIGHT_FIELDS = {"description", "azimuth_deg"}
_MASTER_FIELDS = {"prompt_text", "reference_asset_ids", "selected_asset_id"}
_STATE_FIELDS = {"id", "name", "description"}
_VIEW_FIELDS = {
    "id",
    "name",
    "purpose",
    "azimuth_deg",
    "look_at_fixture_id",
    "yaw_offset_deg",
    "pitch_deg",
    "hfov_deg",
    "state_id",
    "refine_prompt_text",
    "reference_view_ids",
    "crop_asset_id",
    "selected_asset_id",
}


def serialize_location(location: Location) -> dict[str, Any]:
    return {
        "id": location.id,
        "name": location.name,
        "kind": location.kind.value,
        "description": location.description,
        "fixtures": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "azimuth_deg": item.azimuth_deg,
            }
            for item in location.fixtures
        ],
        "key_light": (
            None
            if location.key_light is None
            else {
                "description": location.key_light.description,
                "azimuth_deg": location.key_light.azimuth_deg,
            }
        ),
        "master": {
            "prompt_text": location.master.prompt_text,
            "reference_asset_ids": list(location.master.reference_asset_ids),
            "selected_asset_id": location.master.selected_asset_id,
        },
        "calibrated_master_asset_id": location.calibrated_master_asset_id,
        "states": [
            {"id": item.id, "name": item.name, "description": item.description}
            for item in location.states
        ],
        "views": [serialize_location_view(item) for item in location.views],
    }


def serialize_location_view(view: LocationView) -> dict[str, Any]:
    return {
        "id": view.id,
        "name": view.name,
        "purpose": view.purpose,
        "azimuth_deg": view.azimuth_deg,
        "look_at_fixture_id": view.look_at_fixture_id,
        "yaw_offset_deg": view.yaw_offset_deg,
        "pitch_deg": view.pitch_deg,
        "hfov_deg": view.hfov_deg,
        "state_id": view.state_id,
        "refine_prompt_text": view.refine_prompt_text,
        "reference_view_ids": list(view.reference_view_ids),
        "crop_asset_id": view.crop_asset_id,
        "selected_asset_id": view.selected_asset_id,
    }


def serialize_location_library(library: LocationLibrary) -> dict[str, Any]:
    return {"locations": [serialize_location(item) for item in library.locations]}


def _parse_location_library(value: object) -> LocationLibrary:
    fields = _exact_object(value, _LIBRARY_FIELDS)
    return LocationLibrary(locations=_object_list(fields["locations"], _parse_location))


def _parse_location(value: object) -> Location:
    fields = _exact_object(value, _LOCATION_FIELDS)
    return Location(
        id=_string(fields["id"], "location.id"),
        name=_string(fields["name"], "location.name"),
        kind=LocationKind(_string(fields["kind"], "location.kind")),
        description=_string(fields["description"], "location.description"),
        fixtures=_object_list(fields["fixtures"], _parse_fixture),
        key_light=None if fields["key_light"] is None else _parse_key_light(fields["key_light"]),
        master=_parse_master(fields["master"]),
        calibrated_master_asset_id=_optional_string(
            fields["calibrated_master_asset_id"], "location.calibrated_master_asset_id"
        ),
        states=_object_list(fields["states"], _parse_state),
        views=_object_list(fields["views"], _parse_view),
    )


def _parse_fixture(value: object) -> LocationFixture:
    fields = _exact_object(value, _FIXTURE_FIELDS)
    return LocationFixture(
        id=_string(fields["id"], "location.fixture.id"),
        name=_string(fields["name"], "location.fixture.name"),
        description=_string(fields["description"], "location.fixture.description"),
        azimuth_deg=_optional_number(fields["azimuth_deg"], "location.fixture.azimuth_deg"),
    )


def _parse_key_light(value: object) -> LocationKeyLight:
    fields = _exact_object(value, _KEY_LIGHT_FIELDS)
    return LocationKeyLight(
        description=_string(fields["description"], "location.key_light.description"),
        azimuth_deg=_optional_number(fields["azimuth_deg"], "location.key_light.azimuth_deg"),
    )


def _parse_master(value: object) -> LocationMaster:
    fields = _exact_object(value, _MASTER_FIELDS)
    return LocationMaster(
        prompt_text=_string(fields["prompt_text"], "location.master.prompt_text"),
        reference_asset_ids=_string_list(
            fields["reference_asset_ids"], "location.master.reference_asset_ids"
        ),
        selected_asset_id=_optional_string(
            fields["selected_asset_id"], "location.master.selected_asset_id"
        ),
    )


def _parse_state(value: object) -> LocationState:
    fields = _exact_object(value, _STATE_FIELDS)
    return LocationState(
        id=_string(fields["id"], "location.state.id"),
        name=_string(fields["name"], "location.state.name"),
        description=_string(fields["description"], "location.state.description"),
    )


def _parse_view(value: object) -> LocationView:
    fields = _exact_object(value, _VIEW_FIELDS)
    return LocationView(
        id=_string(fields["id"], "location.view.id"),
        name=_string(fields["name"], "location.view.name"),
        purpose=_string(fields["purpose"], "location.view.purpose"),
        azimuth_deg=_optional_number(fields["azimuth_deg"], "location.view.azimuth_deg"),
        look_at_fixture_id=_optional_string(
            fields["look_at_fixture_id"], "location.view.look_at_fixture_id"
        ),
        yaw_offset_deg=_optional_number(fields["yaw_offset_deg"], "location.view.yaw_offset_deg"),
        pitch_deg=_number(fields["pitch_deg"], "location.view.pitch_deg"),
        hfov_deg=_number(fields["hfov_deg"], "location.view.hfov_deg"),
        state_id=_optional_string(fields["state_id"], "location.view.state_id"),
        refine_prompt_text=_string(
            fields["refine_prompt_text"], "location.view.refine_prompt_text"
        ),
        reference_view_ids=_string_list(
            fields["reference_view_ids"], "location.view.reference_view_ids"
        ),
        crop_asset_id=_optional_string(fields["crop_asset_id"], "location.view.crop_asset_id"),
        selected_asset_id=_optional_string(
            fields["selected_asset_id"], "location.view.selected_asset_id"
        ),
    )
