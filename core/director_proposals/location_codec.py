"""地点规划 proposal 的严格 schema、parser 与编译。

编译把增补式 proposal 翻译成 `location.apply_operations` 的同一组类型化操作；落库、局部 key 映射与
失效级联全部复用地点库唯一 mutation，这里不另写写入或失效逻辑。
"""

from __future__ import annotations

from core.director_commands import (
    BindScene,
    BindShot,
    CreateLocation,
    CreateView,
    LocationKeyLightInput,
    LocationOperation,
    LocationOperationsPatch,
    UpdateLocation,
    UpdateView,
    UpsertFixture,
    UpsertState,
    is_location_key,
)
from core.director_proposals.location import (
    ExistingLocationInput,
    LocationPlanProposal,
    LocationProposal,
    LocationSceneInput,
    LocationViewProposal,
)
from core.director_proposals.schema_gen import ProposalError, generate_schema, parse_proposal

_ID_PATTERN = {"pattern": "^[0-9a-f]{32}$"}
_IDENTITY = {
    "description": "已有项给正式 id，新建项给局部 key（小写字母开头的 [a-z0-9_-]），二者恰好其一。"
}
_AZIMUTH = {
    "description": (
        "大致方位，0° 为全景正中、顺时针；已有项给 null 表示保持现值。"
        "已选主图的地点以标定为准，不能改动。"
    )
}
_OUTPUT_SCHEMA = generate_schema(
    LocationPlanProposal,
    {
        "locations[].id": {**_ID_PATTERN, **_IDENTITY},
        "locations[].fixtures[].azimuth_deg": _AZIMUTH,
        "locations[].key_light.azimuth_deg": _AZIMUTH,
        "locations[].master_prompt_text": {
            "description": "主图静态环境正文；不写图号、画幅、人物或剧情动作。"
        },
        "locations[].views[].azimuth_deg": {
            "description": (
                "视图朝向（标定前优先使用）；与 look_at_fixture_id + yaw_offset_deg 二选一。"
            )
        },
        "locations[].views[].refine_prompt_text": {
            "description": "室外转向的静态环境正文；室内细化只做清晰化，留空。不写图号与画幅。"
        },
        "scene_bindings[].scene_id": _ID_PATTERN,
        "shot_bindings[].shot_id": _ID_PATTERN,
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
    """按当前事实校验归属后编译为单个原子 patch；任何问题都在写入前拒绝。"""
    try:
        return _Compiler(scenes, existing).compile(proposal)
    except ValueError as exc:
        raise ProposalError("location", "invalid_proposal", str(exc)) from exc


class _Compiler:
    def __init__(
        self,
        scenes: tuple[LocationSceneInput, ...],
        existing: tuple[ExistingLocationInput, ...],
    ) -> None:
        self.scenes = {scene.id: scene for scene in scenes}
        self.shot_scene = {shot.id: scene for scene in scenes for shot in scene.shots}
        self.existing = {item.id: item for item in existing}
        self.operations: list[LocationOperation] = []

    def compile(self, proposal: LocationPlanProposal) -> LocationOperationsPatch:
        entries = {}
        for location in proposal.locations:
            ref = location.id or location.key
            entries[ref] = location
            self._location(location, ref)
        scene_targets: dict[str, str | None] = {}
        for binding in proposal.scene_bindings:
            if binding.scene_id not in self.scenes:
                raise ValueError(f"Scene 不存在：{binding.scene_id}。")
            location = binding.location_id
            if location is not None and not is_location_key(location):
                self._existing(location)
            state = binding.state_id
            if state is not None and not is_location_key(state):
                owner = None if is_location_key(location) else self.existing[location]
                if owner is None or state not in owner.state_ids:
                    raise ValueError(f"Scene 绑定的状态不属于所绑定的地点：{state}。")
            scene_targets[binding.scene_id] = location
            self.operations.append(BindScene(binding.scene_id, location, state))
        for binding in proposal.shot_bindings:
            scene = self.shot_scene.get(binding.shot_id)
            if scene is None:
                raise ValueError(f"Shot 不存在：{binding.shot_id}。")
            view = binding.view_id
            if view is not None:
                target = scene_targets.get(scene.id, scene.location_id)
                if target is None:
                    raise ValueError(
                        f"Shot {binding.shot_id} 所在 Scene 没有绑定地点，不能绑定视图。"
                    )
                if not self._view_in(view, target, entries):
                    raise ValueError(
                        f"Shot {binding.shot_id} 的视图必须属于所在 Scene 绑定的地点。"
                    )
            self.operations.append(BindShot(binding.shot_id, view))
        return LocationOperationsPatch(
            scope_location_ids=tuple(item.id for item in proposal.locations if item.id),
            scope_scene_ids=tuple(item.scene_id for item in proposal.scene_bindings),
            scope_shot_ids=tuple(item.shot_id for item in proposal.shot_bindings),
            operations=tuple(self.operations),
        )

    def _existing(self, location_id: str) -> ExistingLocationInput:
        found = self.existing.get(location_id)
        if found is None:
            raise ValueError(f"地点不存在：{location_id}。")
        return found

    def _view_in(self, view: str, location: str, entries: dict[str, LocationProposal]) -> bool:
        if is_location_key(view):
            entry = entries.get(location)
            return entry is not None and any(item.key == view for item in entry.views)
        current = self.existing.get(location)
        return current is not None and view in current.view_ids

    def _location(self, location: LocationProposal, ref: str) -> None:
        current = None if location.key else self._existing(location.id)
        fixture_azimuths = {} if current is None else dict(current.fixture_azimuths)
        owned = {
            "fixture": set(fixture_azimuths),
            "state": set(() if current is None else current.state_ids),
            "view": set(() if current is None else current.view_ids),
        }
        for items, kind in (
            (location.fixtures, "fixture"),
            (location.states, "state"),
            (location.views, "view"),
        ):
            for item in items:
                if item.id is not None and item.id not in owned[kind]:
                    raise ValueError(f"{_LABELS[kind]}不属于地点「{location.name}」：{item.id}。")
        master_selected = current is not None and current.master_selected
        key_light = None
        if location.key_light is not None:
            key_light = LocationKeyLightInput(
                location.key_light.description.strip(),
                _azimuth(
                    location.key_light.azimuth_deg,
                    None if current is None else current.key_light_azimuth_deg,
                    master_selected,
                    f"地点「{location.name}」的主光",
                ),
            )
        plan = {"key_light": key_light, "master_prompt_text": location.master_prompt_text.strip()}
        if current is None:
            self.operations.append(
                CreateLocation(
                    location.key,
                    location.name.strip(),
                    location.kind,
                    location.description.strip(),
                )
            )
            self.operations.append(UpdateLocation(location.key, plan))
        else:
            self.operations.append(
                UpdateLocation(
                    location.id,
                    {
                        "name": location.name.strip(),
                        "kind": location.kind,
                        "description": location.description.strip(),
                        **plan,
                    },
                )
            )
        for fixture in location.fixtures:
            self.operations.append(
                UpsertFixture(
                    ref,
                    fixture.id or fixture.key,
                    fixture.name.strip(),
                    fixture.description.strip(),
                    _azimuth(
                        fixture.azimuth_deg,
                        fixture_azimuths.get(fixture.id),
                        master_selected,
                        f"陈设「{fixture.name}」",
                    ),
                )
            )
        for state in location.states:
            self.operations.append(
                UpsertState(
                    ref, state.id or state.key, state.name.strip(), state.description.strip()
                )
            )
        for view in _ordered_views(location):
            for target, kind in (
                (view.look_at_fixture_id, "fixture"),
                (view.state_id, "state"),
                *((item, "view") for item in view.reference_view_ids),
            ):
                if target is not None and not is_location_key(target) and target not in owned[kind]:
                    raise ValueError(
                        f"视图「{view.name}」引用的{_LABELS[kind]}不属于地点「{location.name}」：{target}。"
                    )
            fields = _view_fields(view)
            if view.key is not None:
                self.operations.append(CreateView(ref, view.key, fields))
            else:
                self.operations.append(UpdateView(view.id, fields))


def _azimuth(
    proposed: float | None, current: float | None, master_selected: bool, label: str
) -> float | None:
    """已有项给 null 保持现值；已选主图的地点以标定方位为准，不接受规划改动。"""
    if proposed is None:
        return current
    if master_selected and proposed != current:
        raise ValueError(f"{label}所在地点已选主图，方位以标定为准，请通过标定修改。")
    return proposed


def _view_fields(view: LocationViewProposal) -> dict[str, object]:
    return {
        "name": view.name.strip(),
        "purpose": view.purpose.strip(),
        "azimuth_deg": view.azimuth_deg,
        "look_at_fixture_id": view.look_at_fixture_id,
        "yaw_offset_deg": view.yaw_offset_deg,
        "pitch_deg": view.pitch_deg,
        "hfov_deg": view.hfov_deg,
        "state_id": view.state_id,
        "refine_prompt_text": view.refine_prompt_text.strip(),
        "reference_view_ids": view.reference_view_ids,
    }


def _ordered_views(location: LocationProposal) -> list[LocationViewProposal]:
    """被参考的视图先落库，让同一 patch 内的 key 引用总能解析；成环直接拒绝。"""
    by_ref = {view.id or view.key: view for view in location.views}
    ordered: list[LocationViewProposal] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(ref: str) -> None:
        if ref in done:
            return
        if ref in visiting:
            raise ValueError(f"地点「{location.name}」的视图参考依赖不能形成环。")
        visiting.add(ref)
        for dependency in by_ref[ref].reference_view_ids:
            if dependency in by_ref:
                visit(dependency)
        visiting.remove(ref)
        done.add(ref)
        ordered.append(by_ref[ref])

    for ref in by_ref:
        visit(ref)
    return ordered


_LABELS = {"fixture": "陈设", "state": "状态", "view": "视图"}
