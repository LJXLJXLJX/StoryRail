"""地点库严格 JSON 编解码。"""

from __future__ import annotations

from typing import Any

from ..models import (
    Location,
    LocationFixture,
    LocationImage,
    LocationImageKind,
    LocationKeyLight,
    LocationLibrary,
    LocationState,
    PanoramaCaptureSource,
)
from ._shared import (
    _exact_object,
    _number,
    _object_list,
    _optional_string,
    _string,
    _string_list,
)

_LIBRARY_FIELDS = {"locations"}
_LOCATION_FIELDS = {"id", "name", "description", "fixtures", "key_light", "states", "images"}
_FIXTURE_FIELDS = {"id", "name", "description"}
_KEY_LIGHT_FIELDS = {"description"}
_STATE_FIELDS = {"id", "name", "description"}
_IMAGE_FIELDS = {
    "id",
    "name",
    "kind",
    "description",
    "prompt_text",
    "reference_asset_ids",
    "selected_asset_id",
    "source",
}
_SOURCE_FIELDS = {"panorama_image_id", "yaw_deg", "pitch_deg", "hfov_deg"}


def serialize_location(location: Location) -> dict[str, Any]:
    return {
        "id": location.id,
        "name": location.name,
        "description": location.description,
        "fixtures": [
            {"id": item.id, "name": item.name, "description": item.description}
            for item in location.fixtures
        ],
        "key_light": (
            None if location.key_light is None else {"description": location.key_light.description}
        ),
        "states": [
            {"id": item.id, "name": item.name, "description": item.description}
            for item in location.states
        ],
        "images": [serialize_location_image(item) for item in location.images],
    }


def serialize_location_image(image: LocationImage) -> dict[str, Any]:
    return {
        "id": image.id,
        "name": image.name,
        "kind": image.kind.value,
        "description": image.description,
        "prompt_text": image.prompt_text,
        "reference_asset_ids": list(image.reference_asset_ids),
        "selected_asset_id": image.selected_asset_id,
        "source": (
            None
            if image.source is None
            else {
                "panorama_image_id": image.source.panorama_image_id,
                "yaw_deg": image.source.yaw_deg,
                "pitch_deg": image.source.pitch_deg,
                "hfov_deg": image.source.hfov_deg,
            }
        ),
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
        description=_string(fields["description"], "location.description"),
        fixtures=_object_list(fields["fixtures"], _parse_fixture),
        key_light=None if fields["key_light"] is None else _parse_key_light(fields["key_light"]),
        states=_object_list(fields["states"], _parse_state),
        images=_object_list(fields["images"], _parse_image),
    )


def _parse_fixture(value: object) -> LocationFixture:
    fields = _exact_object(value, _FIXTURE_FIELDS)
    return LocationFixture(
        id=_string(fields["id"], "location.fixture.id"),
        name=_string(fields["name"], "location.fixture.name"),
        description=_string(fields["description"], "location.fixture.description"),
    )


def _parse_key_light(value: object) -> LocationKeyLight:
    fields = _exact_object(value, _KEY_LIGHT_FIELDS)
    return LocationKeyLight(
        description=_string(fields["description"], "location.key_light.description")
    )


def _parse_state(value: object) -> LocationState:
    fields = _exact_object(value, _STATE_FIELDS)
    return LocationState(
        id=_string(fields["id"], "location.state.id"),
        name=_string(fields["name"], "location.state.name"),
        description=_string(fields["description"], "location.state.description"),
    )


def _parse_image(value: object) -> LocationImage:
    fields = _exact_object(value, _IMAGE_FIELDS)
    return LocationImage(
        id=_string(fields["id"], "location.image.id"),
        name=_string(fields["name"], "location.image.name"),
        kind=LocationImageKind(_string(fields["kind"], "location.image.kind")),
        description=_string(fields["description"], "location.image.description"),
        prompt_text=_string(fields["prompt_text"], "location.image.prompt_text"),
        reference_asset_ids=_string_list(
            fields["reference_asset_ids"], "location.image.reference_asset_ids"
        ),
        selected_asset_id=_optional_string(
            fields["selected_asset_id"], "location.image.selected_asset_id"
        ),
        source=None if fields["source"] is None else _parse_source(fields["source"]),
    )


def _parse_source(value: object) -> PanoramaCaptureSource:
    fields = _exact_object(value, _SOURCE_FIELDS)
    return PanoramaCaptureSource(
        panorama_image_id=_string(
            fields["panorama_image_id"], "location.image.source.panorama_image_id"
        ),
        yaw_deg=_number(fields["yaw_deg"], "location.image.source.yaw_deg"),
        pitch_deg=_number(fields["pitch_deg"], "location.image.source.pitch_deg"),
        hfov_deg=_number(fields["hfov_deg"], "location.image.source.hfov_deg"),
    )
