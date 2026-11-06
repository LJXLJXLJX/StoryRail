"""地点 proposal 的严格 schema、parser 与命令编译。"""

from __future__ import annotations

from core.director_commands import (
    BindScene,
    CreateLocation,
    CreateLocationImage,
    LocationKeyLightInput,
    LocationOperation,
    LocationOperationsPatch,
    PanoramaCaptureSourceInput,
    UpdateLocation,
    UpdateLocationImage,
    UpsertFixture,
    UpsertState,
    is_location_key,
)
from core.director_proposals.location import (
    ExistingLocationInput,
    LocationImageProposal,
    LocationPlanProposal,
    LocationSceneInput,
)
from core.director_proposals.schema_gen import ProposalError, generate_schema, parse_proposal

_ID_PATTERN = {"pattern": "^[0-9a-f]{32}$"}
_OUTPUT_SCHEMA = generate_schema(
    LocationPlanProposal,
    {
        "locations[].id": _ID_PATTERN,
        "locations[].images[].id": _ID_PATTERN,
        "locations[].images[].description": {
            "description": "根据实际画面填写的强制纯文本说明；不得只复制生成提示词。"
        },
        "locations[].images[].prompt_text": {
            "description": "生成正文；不写图号与画幅。全景图片明确描述空间，不派生 Shot 视图。"
        },
        "scene_bindings[].scene_id": _ID_PATTERN,
    },
)


def output_schema() -> dict:
    return _OUTPUT_SCHEMA


def parse_location_plan(raw_response: str) -> LocationPlanProposal:
    try:
        return parse_proposal(raw_response, _OUTPUT_SCHEMA, LocationPlanProposal, domain="location")
    except ProposalError as exc:
        raise ProposalError("location", exc.code, exc.message) from exc
    except ValueError as exc:
        raise ProposalError("location", "invalid_value", str(exc)) from exc


def compile_location_proposal(
    proposal: LocationPlanProposal,
    scenes: tuple[LocationSceneInput, ...],
    existing: tuple[ExistingLocationInput, ...],
) -> LocationOperationsPatch:
    try:
        return _Compiler(scenes, existing).compile(proposal)
    except ValueError as exc:
        raise ProposalError("location", "invalid_proposal", str(exc)) from exc


class _Compiler:
    def __init__(self, scenes, existing) -> None:
        self.scenes = {scene.id: scene for scene in scenes}
        self.existing = {item.id: item for item in existing}
        self.operations: list[LocationOperation] = []

    def compile(self, proposal: LocationPlanProposal) -> LocationOperationsPatch:
        for location in proposal.locations:
            self._location(location)
        for binding in proposal.scene_bindings:
            if binding.scene_id not in self.scenes:
                raise ValueError(f"Scene 不存在：{binding.scene_id}。")
            if binding.location_id is not None and not is_location_key(binding.location_id):
                if binding.location_id not in self.existing:
                    raise ValueError(f"地点不存在：{binding.location_id}。")
                if (
                    binding.state_id is not None
                    and not is_location_key(binding.state_id)
                    and binding.state_id not in self.existing[binding.location_id].state_ids
                ):
                    raise ValueError("Scene 状态不属于所选地点。")
            self.operations.append(
                BindScene(binding.scene_id, binding.location_id, binding.state_id)
            )
        return LocationOperationsPatch(
            scope_location_ids=tuple(item.id for item in proposal.locations if item.id),
            scope_scene_ids=tuple(item.scene_id for item in proposal.scene_bindings),
            operations=tuple(self.operations),
        )

    def _location(self, location) -> None:
        current = None if location.key else self.existing.get(location.id)
        if location.id is not None and current is None:
            raise ValueError(f"地点不存在：{location.id}。")
        ref = location.id or location.key
        if current is None:
            self.operations.append(
                CreateLocation(location.key, location.name.strip(), location.description.strip())
            )
        else:
            self.operations.append(
                UpdateLocation(
                    location.id,
                    {
                        "name": location.name.strip(),
                        "description": location.description.strip(),
                        "key_light": (
                            None
                            if location.key_light is None
                            else LocationKeyLightInput(location.key_light.description.strip())
                        ),
                    },
                )
            )
        if current is None and location.key_light is not None:
            self.operations.append(
                UpdateLocation(
                    location.key,
                    {"key_light": LocationKeyLightInput(location.key_light.description.strip())},
                )
            )
        owned_fixtures = set() if current is None else set(current.fixture_ids)
        owned_states = set() if current is None else set(current.state_ids)
        owned_images = set() if current is None else set(current.image_ids)
        for fixture in location.fixtures:
            if fixture.id is not None and fixture.id not in owned_fixtures:
                raise ValueError("陈设不属于指定地点。")
            self.operations.append(
                UpsertFixture(
                    ref,
                    fixture.id or fixture.key,
                    fixture.name.strip(),
                    fixture.description.strip(),
                )
            )
        for state in location.states:
            if state.id is not None and state.id not in owned_states:
                raise ValueError("状态不属于指定地点。")
            self.operations.append(
                UpsertState(
                    ref, state.id or state.key, state.name.strip(), state.description.strip()
                )
            )
        for image in location.images:
            if image.id is not None and image.id not in owned_images:
                raise ValueError("图片不属于指定地点。")
            fields = _image_fields(image)
            if image.key is not None:
                self.operations.append(CreateLocationImage(ref, image.key, fields))
            else:
                self.operations.append(UpdateLocationImage(image.id, fields))


def _image_fields(image: LocationImageProposal) -> dict[str, object]:
    return {
        "name": image.name.strip(),
        "kind": image.kind,
        "description": image.description.strip(),
        "prompt_text": image.prompt_text.strip(),
        "reference_asset_ids": image.reference_asset_ids,
        "source": (
            None
            if image.source is None
            else PanoramaCaptureSourceInput(
                image.source.panorama_image_id,
                image.source.yaw_deg,
                image.source.pitch_deg,
                image.source.hfov_deg,
            )
        ),
    }
