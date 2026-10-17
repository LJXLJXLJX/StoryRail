"""地点库唯一 mutation：类型化操作、人类候选选择与按实际使用关系传播的失效。

失效规则（docs/data-model.md「失效规则」）：
- 改名、purpose、不进入几何的文字字段不失效；
- 主图改选或清除（含 kind 变化）清空标定、该地点全部视图的裁切与选择；
- 陈设方位变化清空朝向该陈设的视图的裁切与选择；
- 视图几何变化清空裁切与选择，细化计划、参考视图或所属状态（含状态描述）变化清空选择；
- 视图失效沿 `reference_view_ids` 传给依赖它的视图，再传给使用这些视图的 Keyframe，
  沿用 Keyframe → Segment 视频/超分 → 最终装配的级联；
- Scene/Shot 改绑不改写已规划 Keyframe；历史 Asset/Generation 永远保留。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from core.director_commands import (
    BindScene,
    BindShot,
    CalibrateLocation,
    ClearMasterSelection,
    ClearViewSelection,
    CreateLocation,
    CreateView,
    DeleteFixture,
    DeleteLocation,
    DeleteState,
    DeleteView,
    LocationKeyLightInput,
    LocationMasterSelection,
    LocationOperationsPatch,
    LocationViewSelection,
    UpdateLocation,
    UpdateView,
    UpsertFixture,
    UpsertState,
    is_location_key,
)

from .models import (
    Location,
    LocationFixture,
    LocationKeyLight,
    LocationKind,
    LocationLibrary,
    LocationState,
    LocationView,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    Scene,
    StructuredDirectorDocument,
)
from .script_index import shot_segments

_TERMINAL_PHASES = frozenset(
    {
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.FAILED,
        ReferenceGenerationPhase.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class LocationMutation:
    document: StructuredDirectorDocument
    changed_ids: frozenset[str]
    # 本 patch 内局部 key → Core 分配的正式 ID。
    created_ids: dict[str, str]


class LocationActionIndex:
    """一次读取的资源、候选、引用者和使用关系索引；不修改 document。"""

    def __init__(self, document, *, locations=None, scenes=None):
        locations = document.location_library.locations if locations is None else locations
        scenes = (
            (() if document.director_script is None else document.director_script.scenes)
            if scenes is None
            else scenes
        )
        self.project_id = document.project_id
        self.assets = {asset.id: asset for asset in document.assets}
        self.generations = {}
        self.candidates = set()
        self.active_targets = set()
        for generation in document.generations:
            self.generations.setdefault(generation.target_id, []).append(generation)
            if generation.phase not in _TERMINAL_PHASES:
                self.active_targets.add(generation.target_id)
            asset = self.assets.get(generation.output_asset_id)
            if (
                generation.phase is ReferenceGenerationPhase.SUCCEEDED
                and not generation.dismissed
                and asset is not None
                and asset.media_type.startswith("image/")
            ):
                self.candidates.add((generation.kind, generation.target_id, asset.id))
        self.scene_locations, self.scene_states, self.shot_views = {}, {}, {}
        self.view_frames, self.view_dependents, self.fixture_views, self.state_views = (
            {},
            {},
            {},
            {},
        )
        self.frame_successors, self.frame_segments, self.segment_scenes = {}, {}, {}
        for scene in scenes:
            label = f"Scene「{scene.title}」({scene.id})"
            self.scene_locations.setdefault(scene.location_id, []).append(label)
            self.scene_states.setdefault(scene.state_id, []).append(label)
            for shot in scene.shots:
                self.shot_views.setdefault(shot.view_id, []).append(
                    f"Shot {shot.id}（Scene「{scene.title}」）"
                )
                for segment in shot_segments(scene, shot.id):
                    self.segment_scenes[segment.id] = scene.id
        for location in locations:
            for view in location.views:
                label = f"视图「{view.name}」({view.id})"
                self.fixture_views.setdefault(view.look_at_fixture_id, []).append(label)
                self.state_views.setdefault(view.state_id, []).append(label)
                for reference in view.reference_view_ids:
                    self.view_dependents.setdefault(reference, []).append(view.id)
        self.view_labels = {
            view.id: f"视图「{view.name}」({view.id})"
            for location in locations
            for view in location.views
        }
        plan = document.keyframe_plan
        self.frame_order = {}
        if plan is not None:
            bindings = {binding.segment_id: binding for binding in plan.segments}
            self.frame_order = {frame.id: i for i, frame in enumerate(plan.keyframes)}
            for frame in plan.keyframes:
                self.view_frames.setdefault(frame.environment_view_id, []).append(frame.id)
                if bindings[frame.owner_segment_id].start_enabled:
                    self.frame_successors.setdefault(frame.predecessor_keyframe_id, []).append(
                        frame.id
                    )
            for binding in plan.segments:
                for enabled, frame_id in (
                    (binding.start_enabled, binding.start_keyframe_id),
                    (binding.end_enabled, binding.end_keyframe_id),
                ):
                    if enabled:
                        self.frame_segments.setdefault(frame_id, set()).add(binding.segment_id)

    def keyframe_referrers(self, view_ids):
        return sorted(
            (frame for view in view_ids for frame in self.view_frames.get(view, ())),
            key=self.frame_order.__getitem__,
        )


def _closure(seeds, successors):
    result = set(seeds)
    pending = list(result)
    while pending:
        for target in successors.get(pending.pop(), ()):
            if target not in result:
                result.add(target)
                pending.append(target)
    return result


def location_usage(index: LocationActionIndex, view_ids):
    """视图依赖 → 全部使用帧及启用的后继 → 启用 Segment → Scene 的纯依赖闭包。"""
    views = _closure(view_ids, index.view_dependents)
    frames = _closure(
        (frame for view in views for frame in index.view_frames.get(view, ())),
        index.frame_successors,
    )
    segments = {segment for frame in frames for segment in index.frame_segments.get(frame, ())}
    scenes = {
        index.segment_scenes[segment] for segment in segments if segment in index.segment_scenes
    }
    return views, frames, segments, scenes


def require_idle_location_targets(index: LocationActionIndex, targets) -> None:
    if index.active_targets.intersection(targets):
        raise ValueError("实际使用者仍有进行中或结果不确定的任务，请先处理任务后再修改地点。")


def require_location_selection_idle(index, location, view, asset_id):
    """同一选择是 no-op；改选/清除才检查实际失效使用者。"""
    selected = location.master.selected_asset_id if view is None else view.selected_asset_id
    if selected == asset_id:
        return
    targets = {location.id} if view is None else set()
    views, frames, segments, scenes = location_usage(
        index, (v.id for v in location.views) if view is None else (view.id,)
    )
    targets.update(views | frames | segments | scenes)
    if segments:
        targets.add(index.project_id)
    require_idle_location_targets(index, targets)


def require_location_candidate(index, kind, target_id, asset_id, message):
    """候选必须属于目标、成功、未隐藏且产物仍为项目图片；字节验证留在 Store。"""
    if (kind, target_id, asset_id) not in index.candidates:
        raise ValueError(message)


def require_location_deletion(index, location, kind, item_id=None, *, check_tasks=True):
    """删除引用者判定；事务可先解引用再删除，进行中任务在最终提交时检查。"""
    if kind == "location":
        view_ids = {view.id for view in location.views}
        label = f"地点「{location.name}」"
        refs = list(index.scene_locations.get(location.id, ()))
        # 与写入原顺序一致：Keyframe 按计划顺序，而不是视图顺序。
        refs += [f"Keyframe {frame}" for frame in index.keyframe_referrers(view_ids)]
        targets = {
            location.id,
            *view_ids,
            *(f.id for f in location.fixtures),
            *(s.id for s in location.states),
        }
    elif kind == "view":
        view = location.view(item_id)
        if view is None:
            raise ValueError(f"地点视图不存在：{item_id}。")
        label = f"视图「{view.name}」"
        refs = list(index.shot_views.get(item_id, ()))
        refs += [f"Keyframe {frame}" for frame in index.keyframe_referrers({item_id})]
        refs += [index.view_labels[v] for v in index.view_dependents.get(item_id, ())]
        targets = {item_id}
    elif kind == "fixture":
        fixture = location.fixture(item_id)
        if fixture is None:
            raise ValueError(f"陈设不属于该地点：{item_id}。")
        label = f"陈设「{fixture.name}」"
        refs = list(index.fixture_views.get(item_id, ()))
        targets = {item_id}
    else:
        state = next((s for s in location.states if s.id == item_id), None)
        if state is None:
            raise ValueError(f"状态不属于该地点：{item_id}。")
        label = f"状态「{state.name}」"
        refs = [*index.scene_states.get(item_id, ()), *index.state_views.get(item_id, ())]
        targets = {item_id}
    _reject_referenced(label, refs)
    if check_tasks:
        require_idle_location_targets(index, targets)


def apply_location_operations(
    document: StructuredDirectorDocument, patch: LocationOperationsPatch
) -> LocationMutation:
    work = _Workspace(document)
    work.check_scope(patch)
    for operation in patch.operations:
        work.apply(operation, patch)
    return _commit(document, work)


def select_location_master(
    document: StructuredDirectorDocument, selection: LocationMasterSelection
) -> LocationMutation:
    """人类选择主图；Agent 只能清除选择。"""
    work = _Workspace(document)
    location = work.location(selection.location_id)
    index = LocationActionIndex(document)
    require_location_candidate(
        index,
        ReferenceGenerationKind.LOCATION_MASTER_IMAGE,
        location.id,
        selection.asset_id,
        "地点主图只能选择该地点成功且未隐藏的主图候选。",
    )
    require_location_selection_idle(index, location, None, selection.asset_id)
    work.locations[location.id] = replace(
        location, master=replace(location.master, selected_asset_id=selection.asset_id)
    )
    return _commit(document, work)


def select_location_view(
    document: StructuredDirectorDocument, selection: LocationViewSelection
) -> LocationMutation:
    work = _Workspace(document)
    location, view = work.view_owner(selection.view_id)
    index = LocationActionIndex(document)
    require_location_candidate(
        index,
        ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
        view.id,
        selection.asset_id,
        "地点视图只能选择该视图成功且未隐藏的细化或转向候选。",
    )
    require_location_selection_idle(index, location, view, selection.asset_id)
    work.replace_view(location.id, replace(view, selected_asset_id=selection.asset_id))
    return _commit(document, work)


class _Workspace:
    """单事务内的可变工作副本；只有 `_commit` 才产出新文档。"""

    def __init__(self, document: StructuredDirectorDocument) -> None:
        self.document = document
        self.locations: dict[str, Location] = {
            item.id: item for item in document.location_library.locations
        }
        script = document.director_script
        self.scenes: dict[str, Scene] = (
            {} if script is None else {scene.id: scene for scene in script.scenes}
        )
        self.keys: dict[str, tuple[str, str]] = {}
        self.created_locations: set[str] = set()
        self.deleted_ids: set[str] = set()

    # --- 查找与引用解析 ---

    def location(self, location_id: str) -> Location:
        location = self.locations.get(location_id)
        if location is None:
            raise ValueError(f"地点不存在：{location_id}。")
        return location

    def view_owner(self, view_id: str) -> tuple[Location, LocationView]:
        for location in self.locations.values():
            view = location.view(view_id)
            if view is not None:
                return location, view
        raise ValueError(f"地点视图不存在：{view_id}。")

    def shot_scene(self, shot_id: str) -> Scene:
        for scene in self.scenes.values():
            if any(shot.id == shot_id for shot in scene.shots):
                return scene
        raise ValueError(f"Shot 不存在：{shot_id}。")

    def resolve(self, ref: str, kind: str) -> str:
        if not is_location_key(ref):
            return ref
        found = self.keys.get(ref)
        if found is None or found[0] != kind:
            raise ValueError(f"key「{ref}」没有在本 patch 中先创建为{_KIND_LABELS[kind]}。")
        return found[1]

    def register_key(self, key: str, kind: str) -> str:
        if key in self.keys:
            raise ValueError(f"key「{key}」在同一 patch 中重复创建。")
        item_id = uuid4().hex
        self.keys[key] = (kind, item_id)
        return item_id

    def scoped_location(self, ref: str, patch: LocationOperationsPatch) -> Location:
        location = self.location(self.resolve(ref, "location"))
        if (
            location.id not in patch.scope_location_ids
            and location.id not in self.created_locations
        ):
            raise ValueError(f"地点操作超出 scope：{location.id}。")
        return location

    def scoped_view(
        self, ref: str, patch: LocationOperationsPatch
    ) -> tuple[Location, LocationView]:
        location, view = self.view_owner(self.resolve(ref, "view"))
        if (
            location.id not in patch.scope_location_ids
            and location.id not in self.created_locations
        ):
            raise ValueError(f"视图所属地点超出 scope：{location.id}。")
        return location, view

    def replace_view(self, location_id: str, view: LocationView) -> None:
        location = self.locations[location_id]
        self.locations[location_id] = replace(
            location, views=tuple(view if item.id == view.id else item for item in location.views)
        )

    def check_scope(self, patch: LocationOperationsPatch) -> None:
        if not set(patch.scope_location_ids) <= self.locations.keys():
            raise ValueError("location scope 包含未知地点。")
        if not set(patch.scope_scene_ids) <= self.scenes.keys():
            raise ValueError("location scope 包含未知 Scene。")
        shot_ids = {shot.id for scene in self.scenes.values() for shot in scene.shots}
        if not set(patch.scope_shot_ids) <= shot_ids:
            raise ValueError("location scope 包含未知 Shot。")

    # --- 操作 ---

    def apply(self, operation: object, patch: LocationOperationsPatch) -> None:
        if isinstance(operation, CreateLocation):
            location_id = self.register_key(operation.key, "location")
            self.locations[location_id] = Location(
                location_id,
                operation.name,
                LocationKind(operation.kind),
                description=operation.description,
            )
            self.created_locations.add(location_id)
        elif isinstance(operation, UpdateLocation):
            self._update_location(self.scoped_location(operation.location_id, patch), operation)
        elif isinstance(operation, DeleteLocation):
            self._delete_location(self.scoped_location(operation.location_id, patch))
        elif isinstance(operation, UpsertFixture):
            self._upsert_fixture(self.scoped_location(operation.location_id, patch), operation)
        elif isinstance(operation, DeleteFixture):
            self._delete_fixture(
                self.scoped_location(operation.location_id, patch), operation.fixture_id
            )
        elif isinstance(operation, UpsertState):
            self._upsert_state(self.scoped_location(operation.location_id, patch), operation)
        elif isinstance(operation, DeleteState):
            self._delete_state(
                self.scoped_location(operation.location_id, patch), operation.state_id
            )
        elif isinstance(operation, CreateView):
            location = self.scoped_location(operation.location_id, patch)
            view_id = self.register_key(operation.key, "view")
            view = LocationView(id=view_id, **self._view_fields(location, operation.fields))
            self.locations[location.id] = replace(location, views=(*location.views, view))
        elif isinstance(operation, UpdateView):
            location, view = self.scoped_view(operation.view_id, patch)
            self.replace_view(
                location.id, replace(view, **self._view_fields(location, operation.fields))
            )
        elif isinstance(operation, DeleteView):
            self._delete_view(*self.scoped_view(operation.view_id, patch))
        elif isinstance(operation, CalibrateLocation):
            self._calibrate(self.scoped_location(operation.location_id, patch), operation)
        elif isinstance(operation, BindScene):
            self._bind_scene(operation, patch)
        elif isinstance(operation, BindShot):
            self._bind_shot(operation, patch)
        elif isinstance(operation, ClearMasterSelection):
            location = self.scoped_location(operation.location_id, patch)
            self.locations[location.id] = replace(
                location, master=replace(location.master, selected_asset_id=None)
            )
        elif isinstance(operation, ClearViewSelection):
            location, view = self.scoped_view(operation.view_id, patch)
            self.replace_view(location.id, replace(view, selected_asset_id=None))
        else:
            raise TypeError("未知地点操作。")

    def _update_location(self, location: Location, operation: UpdateLocation) -> None:
        fields = dict(operation.fields)
        master = location.master
        if "master_prompt_text" in fields:
            master = replace(master, prompt_text=fields.pop("master_prompt_text"))
        if "master_reference_asset_ids" in fields:
            master = replace(master, reference_asset_ids=fields.pop("master_reference_asset_ids"))
        if "kind" in fields:
            fields["kind"] = LocationKind(fields["kind"])
            if fields["kind"] is LocationKind.EXTERIOR:
                # 室外视图没有全景裁切；kind 变化本身按主图改选失效。
                fields["views"] = tuple(
                    replace(view, crop_asset_id=None) for view in location.views
                )
        if "key_light" in fields:
            light = fields["key_light"]
            fields["key_light"] = (
                None
                if light is None
                else LocationKeyLight(light.description, light.azimuth_deg)
                if isinstance(light, LocationKeyLightInput)
                else light
            )
        self.locations[location.id] = replace(location, master=master, **fields)

    def _delete_location(self, location: Location) -> None:
        view_ids = {view.id for view in location.views}
        require_location_deletion(self.action_index(), location, "location", check_tasks=False)
        del self.locations[location.id]
        self.deleted_ids.update(
            (
                location.id,
                *view_ids,
                *(item.id for item in location.fixtures),
                *(item.id for item in location.states),
            )
        )

    def _upsert_fixture(self, location: Location, operation: UpsertFixture) -> None:
        fixtures = list(location.fixtures)
        fixture_id = self._upsert_id(operation.fixture, "fixture", {x.id for x in fixtures})
        fixture = LocationFixture(
            fixture_id, operation.name, operation.description, operation.azimuth_deg
        )
        index = next((i for i, x in enumerate(fixtures) if x.id == fixture_id), None)
        if index is None:
            fixtures.append(fixture)
        else:
            fixtures[index] = fixture
        self.locations[location.id] = replace(location, fixtures=tuple(fixtures))

    def _delete_fixture(self, location: Location, fixture_id: str) -> None:
        require_location_deletion(
            self.action_index(), location, "fixture", fixture_id, check_tasks=False
        )
        self.locations[location.id] = replace(
            location, fixtures=tuple(x for x in location.fixtures if x.id != fixture_id)
        )
        self.deleted_ids.add(fixture_id)

    def _upsert_state(self, location: Location, operation: UpsertState) -> None:
        states = list(location.states)
        state_id = self._upsert_id(operation.state, "state", {x.id for x in states})
        state = LocationState(state_id, operation.name, operation.description)
        index = next((i for i, x in enumerate(states) if x.id == state_id), None)
        if index is None:
            states.append(state)
        else:
            states[index] = state
        self.locations[location.id] = replace(location, states=tuple(states))

    def _delete_state(self, location: Location, state_id: str) -> None:
        require_location_deletion(
            self.action_index(), location, "state", state_id, check_tasks=False
        )
        self.locations[location.id] = replace(
            location, states=tuple(x for x in location.states if x.id != state_id)
        )
        self.deleted_ids.add(state_id)

    def _delete_view(self, location: Location, view: LocationView) -> None:
        require_location_deletion(self.action_index(), location, "view", view.id, check_tasks=False)
        self.locations[location.id] = replace(
            location, views=tuple(x for x in location.views if x.id != view.id)
        )
        self.deleted_ids.add(view.id)

    def _calibrate(self, location: Location, operation: CalibrateLocation) -> None:
        master_asset_id = location.master.selected_asset_id
        if master_asset_id is None:
            raise ValueError(f"地点「{location.name}」尚未选择主图，请先选择主图再标定陈设方位。")
        azimuths: dict[str, float] = {}
        for ref, degrees in operation.fixture_azimuths:
            fixture_id = self.resolve(ref, "fixture")
            if all(x.id != fixture_id for x in location.fixtures):
                raise ValueError(f"陈设不属于该地点：{fixture_id}。")
            azimuths[fixture_id] = degrees
        key_light = location.key_light
        if operation.key_light_azimuth_deg is not None:
            if key_light is None:
                raise ValueError("请先填写主光描述，再标定主光方位。")
            key_light = replace(key_light, azimuth_deg=operation.key_light_azimuth_deg)
        self.locations[location.id] = replace(
            location,
            fixtures=tuple(
                replace(x, azimuth_deg=azimuths[x.id]) if x.id in azimuths else x
                for x in location.fixtures
            ),
            key_light=key_light,
            calibrated_master_asset_id=master_asset_id,
        )

    def _bind_scene(self, operation: BindScene, patch: LocationOperationsPatch) -> None:
        if operation.scene_id not in patch.scope_scene_ids:
            raise ValueError(f"Scene 绑定超出 scope：{operation.scene_id}。")
        scene = self.scenes[operation.scene_id]
        location_id = (
            None
            if operation.location_id is None
            else self.location(self.resolve(operation.location_id, "location")).id
        )
        state_id = None if operation.state_id is None else self.resolve(operation.state_id, "state")
        if state_id is not None and (
            location_id is None
            or all(state.id != state_id for state in self.locations[location_id].states)
        ):
            raise ValueError("Scene 的地点状态必须属于所绑定的地点。")
        shots = scene.shots
        if location_id != scene.location_id:
            # 换地点时视图必然不属于新地点：清空 Shot 视图；已规划 Keyframe 不改写。
            shots = tuple(replace(shot, view_id=None) for shot in shots)
        self.scenes[scene.id] = replace(
            scene, location_id=location_id, state_id=state_id, shots=shots
        )

    def _bind_shot(self, operation: BindShot, patch: LocationOperationsPatch) -> None:
        if operation.shot_id not in patch.scope_shot_ids:
            raise ValueError(f"Shot 绑定超出 scope：{operation.shot_id}。")
        scene = self.shot_scene(operation.shot_id)
        view_id = None if operation.view_id is None else self.resolve(operation.view_id, "view")
        if view_id is not None:
            owner, _view = self.view_owner(view_id)
            if scene.location_id != owner.id:
                raise ValueError("Shot 的视图必须属于所在 Scene 已绑定的地点。")
        self.scenes[scene.id] = replace(
            scene,
            shots=tuple(
                replace(shot, view_id=view_id) if shot.id == operation.shot_id else shot
                for shot in scene.shots
            ),
        )

    # --- 辅助 ---

    def _upsert_id(self, ref: str, kind: str, existing: set[str]) -> str:
        if not is_location_key(ref):
            if ref not in existing:
                raise ValueError(f"{_KIND_LABELS[kind]}不属于该地点：{ref}。")
            return ref
        found = self.keys.get(ref)
        if found is None:
            return self.register_key(ref, kind)
        if found[0] != kind or found[1] not in existing:
            raise ValueError(f"key「{ref}」不是该地点的{_KIND_LABELS[kind]}。")
        return found[1]

    def _view_fields(self, location: Location, fields: dict[str, object]) -> dict[str, object]:
        resolved = dict(fields)
        if resolved.get("look_at_fixture_id") is not None:
            resolved["look_at_fixture_id"] = self.resolve(resolved["look_at_fixture_id"], "fixture")
        if resolved.get("state_id") is not None:
            resolved["state_id"] = self.resolve(resolved["state_id"], "state")
        if "reference_view_ids" in resolved:
            resolved["reference_view_ids"] = tuple(
                self.resolve(ref, "view") for ref in resolved["reference_view_ids"]
            )
        return resolved

    def action_index(self):
        return LocationActionIndex(
            self.document, locations=self.locations.values(), scenes=self.scenes.values()
        )


_KIND_LABELS = {"location": "地点", "fixture": "陈设", "state": "状态", "view": "视图"}


def _reject_referenced(label: str, referrers: list[str]) -> None:
    if referrers:
        raise ValueError(f"不能删除{label}：仍被 {'、'.join(referrers)} 引用，请先解除引用。")


def _commit(document: StructuredDirectorDocument, work: _Workspace) -> LocationMutation:
    library = LocationLibrary(tuple(work.locations.values()))
    script = document.director_script
    if script is not None:
        scenes = tuple(work.scenes[scene.id] for scene in script.scenes)
        if scenes != script.scenes:
            script = replace(
                script,
                scenes=scenes,
                production_baseline_scenes=_sync_baseline(
                    script.production_baseline_scenes, scenes
                ),
            )
    updated = _cascade(document, library, script, frozenset(work.deleted_ids))
    created = {key: item_id for key, (_kind, item_id) in work.keys.items()}
    if updated == document:
        return LocationMutation(document, frozenset(), created)
    return LocationMutation(
        replace(updated, revision=document.revision + 1),
        frozenset(_changed_ids(document, updated)),
        created,
    )


def _sync_baseline(
    baseline: tuple[Scene, ...] | None, scenes: tuple[Scene, ...]
) -> tuple[Scene, ...] | None:
    """绑定独立于创作正文和时序；基线同 ID 的使用事实保持一致，避免回改恢复旧绑定。"""
    if baseline is None:
        return None
    current = {scene.id: scene for scene in scenes}
    shot_views = {shot.id: (scene.id, shot.view_id) for scene in scenes for shot in scene.shots}
    synced = []
    for scene in baseline:
        source = current.get(scene.id)
        if source is None:
            synced.append(scene)
            continue
        relocated = source.location_id != scene.location_id
        shots = tuple(
            replace(
                shot,
                view_id=shot_views[shot.id][1]
                if shot_views.get(shot.id, (None,))[0] == scene.id
                else None
                if relocated
                else shot.view_id,
            )
            for shot in scene.shots
        )
        synced.append(
            replace(scene, location_id=source.location_id, state_id=source.state_id, shots=shots)
        )
    return tuple(synced)


def _geometry(view: LocationView) -> tuple[object, ...]:
    return (
        view.azimuth_deg,
        view.look_at_fixture_id,
        view.yaw_offset_deg,
        view.pitch_deg,
        view.hfov_deg,
    )


def _refine_plan(view: LocationView) -> tuple[object, ...]:
    return (view.refine_prompt_text, view.reference_view_ids, view.state_id)


def _cascade(
    document: StructuredDirectorDocument,
    library: LocationLibrary,
    script,
    deleted_ids: frozenset[str],
) -> StructuredDirectorDocument:
    """按实际使用关系清除失效选择；使用者有未结束任务时拒绝整笔修改。"""
    previous = {item.id: item for item in document.location_library.locations}
    affected_locations: set[str] = set()
    affected_views: set[str] = set()
    locations = []
    for location in library.locations:
        old = previous.get(location.id)
        if old is None:
            locations.append(location)
            continue
        views = {view.id: view for view in location.views}
        old_views = {view.id: view for view in old.views}
        if old.master.selected_asset_id != location.master.selected_asset_id or (
            old.kind is not location.kind
        ):
            affected_locations.add(location.id)
            location = replace(location, calibrated_master_asset_id=None)
            views = {
                key: replace(view, crop_asset_id=None, selected_asset_id=None)
                for key, view in views.items()
            }
            affected_views.update(views)
        else:
            old_azimuths = {item.id: item.azimuth_deg for item in old.fixtures}
            moved = {
                item.id
                for item in location.fixtures
                if item.id in old_azimuths and old_azimuths[item.id] != item.azimuth_deg
            }
            old_states = {item.id: item.description for item in old.states}
            redescribed = {
                item.id
                for item in location.states
                if item.id in old_states and old_states[item.id] != item.description
            }
            for key, view in views.items():
                old_view = old_views.get(key)
                if old_view is None:
                    continue
                geometry = _geometry(view) != _geometry(old_view) or (
                    view.look_at_fixture_id in moved
                )
                plan = _refine_plan(view) != _refine_plan(old_view) or (
                    view.state_id in redescribed
                )
                if geometry:
                    views[key] = replace(view, crop_asset_id=None, selected_asset_id=None)
                elif plan:
                    views[key] = replace(view, selected_asset_id=None)
                if geometry or plan or view.selected_asset_id != old_view.selected_asset_id:
                    affected_views.add(key)
        while True:
            downstream = {
                key
                for key, view in views.items()
                if key not in affected_views and set(view.reference_view_ids) & affected_views
            }
            if not downstream:
                break
            for key in downstream:
                views[key] = replace(views[key], selected_asset_id=None)
            affected_views.update(downstream)
        locations.append(replace(location, views=tuple(views[view.id] for view in location.views)))
    library = LocationLibrary(tuple(locations))

    keyframes = document.keyframe_plan
    videos = document.video_plan
    final = document.final_assembly
    index = LocationActionIndex(
        document,
        locations=library.locations,
        scenes=() if script is None else script.scenes,
    )
    affected_targets = set(affected_locations) | affected_views | deleted_ids
    if keyframes is not None and affected_views:
        _views, frame_ids, segment_ids, scene_ids = location_usage(index, affected_views)
        affected_targets.update(frame_ids | segment_ids | scene_ids)
        if segment_ids:
            affected_targets.add(document.project_id)
        keyframes = replace(
            keyframes,
            keyframes=tuple(
                replace(frame, selected_asset_id=None) if frame.id in frame_ids else frame
                for frame in keyframes.keyframes
            ),
        )
        if videos is not None and segment_ids:
            videos = replace(
                videos,
                segments=tuple(
                    replace(item, selected_asset_id=None, upscaled_asset_id=None)
                    if item.segment_id in segment_ids
                    else item
                    for item in videos.segments
                ),
            )
        if final is not None and any(clip.scene_id in scene_ids for clip in final.clips):
            # 最终成片引用 Scene 成片，受影响 Segment 所属 Scene 在计划里就作废。
            final = None
    candidate = replace(
        document,
        location_library=library,
        director_script=script,
        keyframe_plan=keyframes,
        video_plan=videos,
        final_assembly=final,
    )
    if candidate != document:
        require_idle_location_targets(index, affected_targets)
    return candidate


def _changed_ids(
    previous: StructuredDirectorDocument, current: StructuredDirectorDocument
) -> set[str]:
    def entities(document: StructuredDirectorDocument) -> dict[str, object]:
        result: dict[str, object] = {}
        for location in document.location_library.locations:
            result[location.id] = (
                location.name,
                location.kind,
                location.description,
                location.key_light,
                location.master,
                location.calibrated_master_asset_id,
            )
            for item in (*location.fixtures, *location.states, *location.views):
                result[item.id] = item
        script = document.director_script
        for scene in () if script is None else script.scenes:
            result[scene.id] = (scene.location_id, scene.state_id)
            for shot in scene.shots:
                result[shot.id] = shot.view_id
        plan = document.keyframe_plan
        for frame in () if plan is None else plan.keyframes:
            result[frame.id] = frame.selected_asset_id
        videos = document.video_plan
        for item in () if videos is None else videos.segments:
            result[item.segment_id] = (item.selected_asset_id, item.upscaled_asset_id)
        return result

    before = entities(previous)
    after = entities(current)
    return {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
