"""地点语义与独立图片条目的纯领域变换。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from core.director_commands import (
    BindScene,
    ClearLocationImageSelection,
    CreateLocation,
    CreateLocationImage,
    DeleteFixture,
    DeleteLocation,
    DeleteLocationImage,
    DeleteState,
    LocationImageSelection,
    LocationKeyLightInput,
    LocationOperationsPatch,
    PanoramaCaptureSourceInput,
    UpdateLocation,
    UpdateLocationImage,
    UpsertFixture,
    UpsertState,
    is_location_key,
)

from .models import (
    Location,
    LocationFixture,
    LocationImage,
    LocationImageKind,
    LocationKeyLight,
    LocationLibrary,
    LocationState,
    PanoramaCaptureSource,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    Scene,
    StructuredDirectorDocument,
)

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
    created_ids: dict[str, str]


class LocationActionIndex:
    """一次读取所需的候选、任务与 Scene 语义引用索引。"""

    def __init__(self, document, *, locations=None, scenes=None):
        locations = document.location_library.locations if locations is None else tuple(locations)
        scenes = (
            (() if document.director_script is None else document.director_script.scenes)
            if scenes is None
            else tuple(scenes)
        )
        self.assets = {asset.id: asset for asset in document.assets}
        self.generations: dict[str, list[object]] = {}
        self.candidates: set[tuple[ReferenceGenerationKind, str, str]] = set()
        self.active_targets: set[str] = set()
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
        self.scene_locations: dict[str | None, list[str]] = {}
        self.scene_states: dict[str | None, list[str]] = {}
        for scene in scenes:
            label = f"Scene「{scene.title}」({scene.id})"
            self.scene_locations.setdefault(scene.location_id, []).append(label)
            self.scene_states.setdefault(scene.state_id, []).append(label)
        self.image_ids = {image.id for location in locations for image in location.images}


def require_idle_location_targets(index: LocationActionIndex, targets) -> None:
    if index.active_targets.intersection(targets):
        raise ValueError("相关地点图片仍有进行中或结果不确定的任务，请先处理后再修改。")


def require_location_selection_idle(index, image: LocationImage, asset_id: str | None) -> None:
    if image.selected_asset_id == asset_id:
        return
    require_idle_location_targets(index, {image.id})


def require_location_candidate(index, kind, target_id, asset_id, message):
    if (kind, target_id, asset_id) not in index.candidates:
        raise ValueError(message)


def require_location_deletion(index, location, kind, item_id=None, *, check_tasks=True):
    if kind == "location":
        refs = list(index.scene_locations.get(location.id, ()))
        if refs:
            raise ValueError(
                f"不能删除地点「{location.name}」：仍被 {'、'.join(refs)} 引用，请先解除引用。"
            )
        targets = {location.id, *(image.id for image in location.images)}
    elif kind == "state":
        state = next((item for item in location.states if item.id == item_id), None)
        if state is None:
            raise ValueError(f"状态不属于该地点：{item_id}。")
        refs = list(index.scene_states.get(item_id, ()))
        if refs:
            raise ValueError(
                f"不能删除状态「{state.name}」：仍被 {'、'.join(refs)} 引用，请先解除引用。"
            )
        targets = {item_id}
    elif kind == "fixture":
        if location.fixture(item_id) is None:
            raise ValueError(f"陈设不属于该地点：{item_id}。")
        targets = {item_id}
    elif kind == "image":
        if location.image(item_id) is None:
            raise ValueError(f"图片不属于该地点：{item_id}。")
        targets = {item_id}
    else:
        raise ValueError("未知地点删除类型。")
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


def select_location_image(
    document: StructuredDirectorDocument, selection: LocationImageSelection
) -> LocationMutation:
    work = _Workspace(document)
    location, image = work.image_owner(selection.image_id)
    index = LocationActionIndex(document)
    asset = index.assets.get(selection.asset_id)
    if asset is None or not asset.media_type.startswith("image/"):
        raise ValueError("地点图片只能选择项目资产库中的图片 Asset。")
    if image.source is not None:
        require_location_candidate(
            index,
            ReferenceGenerationKind.PANORAMA_CAPTURE,
            image.id,
            selection.asset_id,
            "全景取景子图只能选择该条目成功且未隐藏的裁切候选。",
        )
    require_location_selection_idle(index, image, selection.asset_id)
    work.replace_image(location.id, replace(image, selected_asset_id=selection.asset_id))
    return _commit(document, work)


class _Workspace:
    def __init__(self, document: StructuredDirectorDocument) -> None:
        self.document = document
        self.locations = {item.id: item for item in document.location_library.locations}
        script = document.director_script
        self.scenes: dict[str, Scene] = (
            {} if script is None else {scene.id: scene for scene in script.scenes}
        )
        self.keys: dict[str, tuple[str, str]] = {}
        self.created_locations: set[str] = set()

    def check_scope(self, patch: LocationOperationsPatch) -> None:
        if not set(patch.scope_location_ids) <= self.locations.keys():
            raise ValueError("location scope 包含未知地点。")
        if not set(patch.scope_scene_ids) <= self.scenes.keys():
            raise ValueError("location scope 包含未知 Scene。")

    def location(self, location_id: str) -> Location:
        location = self.locations.get(location_id)
        if location is None:
            raise ValueError(f"地点不存在：{location_id}。")
        return location

    def image_owner(self, image_id: str) -> tuple[Location, LocationImage]:
        for location in self.locations.values():
            image = location.image(image_id)
            if image is not None:
                return location, image
        raise ValueError(f"地点图片不存在：{image_id}。")

    def resolve(self, ref: str, kind: str) -> str:
        if not is_location_key(ref):
            return ref
        found = self.keys.get(ref)
        if found is None or found[0] != kind:
            raise ValueError(f"key「{ref}」没有在本 patch 中先创建为{kind}。")
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

    def scoped_image(
        self, ref: str, patch: LocationOperationsPatch
    ) -> tuple[Location, LocationImage]:
        location, image = self.image_owner(self.resolve(ref, "image"))
        if (
            location.id not in patch.scope_location_ids
            and location.id not in self.created_locations
        ):
            raise ValueError(f"图片所属地点超出 scope：{location.id}。")
        return location, image

    def replace_image(self, location_id: str, image: LocationImage) -> None:
        location = self.locations[location_id]
        self.locations[location_id] = replace(
            location,
            images=tuple(image if item.id == image.id else item for item in location.images),
        )

    def apply(self, operation: object, patch: LocationOperationsPatch) -> None:
        if isinstance(operation, CreateLocation):
            item_id = self.register_key(operation.key, "location")
            self.locations[item_id] = Location(item_id, operation.name, operation.description)
            self.created_locations.add(item_id)
        elif isinstance(operation, UpdateLocation):
            location = self.scoped_location(operation.location_id, patch)
            fields = dict(operation.fields)
            if "key_light" in fields:
                light = fields["key_light"]
                fields["key_light"] = (
                    None
                    if light is None
                    else LocationKeyLight(light.description)
                    if isinstance(light, LocationKeyLightInput)
                    else light
                )
            self.locations[location.id] = replace(location, **fields)
        elif isinstance(operation, DeleteLocation):
            location = self.scoped_location(operation.location_id, patch)
            require_location_deletion(self.action_index(), location, "location", check_tasks=False)
            del self.locations[location.id]
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
        elif isinstance(operation, CreateLocationImage):
            location = self.scoped_location(operation.location_id, patch)
            item_id = self.register_key(operation.key, "image")
            image = LocationImage(id=item_id, **self._image_fields(location, operation.fields))
            self.locations[location.id] = replace(location, images=(*location.images, image))
        elif isinstance(operation, UpdateLocationImage):
            location, image = self.scoped_image(operation.image_id, patch)
            fields = self._image_fields(location, operation.fields)
            # prompt/reference/source 描述下一次生成或冻结 provenance；编辑它们不能让
            # 已经由人选择的实际图片消失。只有切换普通图/全景图语义时清空选择，避免
            # 把项目画幅图片冒充 2:1 全景。
            if "kind" in fields and fields["kind"] != image.kind:
                fields["selected_asset_id"] = None
            self.replace_image(location.id, replace(image, **fields))
        elif isinstance(operation, DeleteLocationImage):
            location, image = self.scoped_image(operation.image_id, patch)
            require_location_deletion(self.action_index(), location, "image", image.id)
            self.locations[location.id] = replace(
                location, images=tuple(item for item in location.images if item.id != image.id)
            )
        elif isinstance(operation, BindScene):
            if operation.scene_id not in patch.scope_scene_ids:
                raise ValueError("Scene 绑定超出 scope。")
            location_id = (
                None
                if operation.location_id is None
                else self.resolve(operation.location_id, "location")
            )
            state_id = (
                None if operation.state_id is None else self.resolve(operation.state_id, "state")
            )
            if location_id is not None:
                location = self.location(location_id)
                if state_id is not None and state_id not in {item.id for item in location.states}:
                    raise ValueError("Scene 状态不属于所选地点。")
            elif state_id is not None:
                raise ValueError("Scene 未选择地点时不能指定状态。")
            self.scenes[operation.scene_id] = replace(
                self.scenes[operation.scene_id], location_id=location_id, state_id=state_id
            )
        elif isinstance(operation, ClearLocationImageSelection):
            location, image = self.scoped_image(operation.image_id, patch)
            require_location_selection_idle(self.action_index(), image, None)
            self.replace_image(location.id, replace(image, selected_asset_id=None))
        else:
            raise TypeError("未知地点操作。")

    def _upsert_fixture(self, location, operation) -> None:
        items = list(location.fixtures)
        item_id = self._upsert_id(operation.fixture, "fixture", {item.id for item in items})
        value = LocationFixture(item_id, operation.name, operation.description)
        index = next((i for i, item in enumerate(items) if item.id == item_id), None)
        if index is None:
            items.append(value)
        else:
            items[index] = value
        self.locations[location.id] = replace(location, fixtures=tuple(items))

    def _delete_fixture(self, location, item_id) -> None:
        require_location_deletion(
            self.action_index(), location, "fixture", item_id, check_tasks=False
        )
        self.locations[location.id] = replace(
            location, fixtures=tuple(item for item in location.fixtures if item.id != item_id)
        )

    def _upsert_state(self, location, operation) -> None:
        items = list(location.states)
        item_id = self._upsert_id(operation.state, "state", {item.id for item in items})
        value = LocationState(item_id, operation.name, operation.description)
        index = next((i for i, item in enumerate(items) if item.id == item_id), None)
        if index is None:
            items.append(value)
        else:
            items[index] = value
        self.locations[location.id] = replace(location, states=tuple(items))

    def _delete_state(self, location, item_id) -> None:
        require_location_deletion(
            self.action_index(), location, "state", item_id, check_tasks=False
        )
        self.locations[location.id] = replace(
            location, states=tuple(item for item in location.states if item.id != item_id)
        )

    def _upsert_id(self, ref: str, kind: str, existing: set[str]) -> str:
        if is_location_key(ref):
            return self.register_key(ref, kind)
        if ref not in existing:
            raise ValueError(f"{kind} 不属于该地点：{ref}。")
        return ref

    def _image_fields(self, location: Location, fields: dict[str, object]) -> dict[str, object]:
        result = dict(fields)
        if "kind" in result:
            result["kind"] = LocationImageKind(result["kind"])
        source = result.get("source")
        if isinstance(source, PanoramaCaptureSourceInput):
            panorama_id = self.resolve(source.panorama_image_id, "image")
            panorama = location.image(panorama_id)
            if panorama is None or panorama.kind is not LocationImageKind.PANORAMA:
                raise ValueError("取景来源必须是当前地点的全景图。")
            result["source"] = PanoramaCaptureSource(
                panorama_id, source.yaw_deg, source.pitch_deg, source.hfov_deg
            )
        return result

    def action_index(self):
        return LocationActionIndex(
            self.document, locations=self.locations.values(), scenes=self.scenes.values()
        )


def _commit(document: StructuredDirectorDocument, work: _Workspace) -> LocationMutation:
    library = LocationLibrary(tuple(work.locations.values()))
    script = document.director_script
    if script is not None:
        scenes = tuple(work.scenes[scene.id] for scene in script.scenes)
        baseline = _sync_baseline(script.production_baseline_scenes, scenes)
        if scenes != script.scenes or baseline != script.production_baseline_scenes:
            script = replace(script, scenes=scenes, production_baseline_scenes=baseline)
    candidate = replace(document, location_library=library, director_script=script)
    created = {key: item_id for key, (_kind, item_id) in work.keys.items()}
    if candidate == document:
        return LocationMutation(document, frozenset(), created)
    changed = _changed_ids(document, candidate)
    return LocationMutation(
        replace(candidate, revision=document.revision + 1), frozenset(changed), created
    )


def _sync_baseline(
    baseline: tuple[Scene, ...] | None, scenes: tuple[Scene, ...]
) -> tuple[Scene, ...] | None:
    if baseline is None:
        return None
    current = {scene.id: scene for scene in scenes}
    return tuple(
        replace(
            scene,
            location_id=current[scene.id].location_id,
            state_id=current[scene.id].state_id,
        )
        if scene.id in current
        else scene
        for scene in baseline
    )


def cleared_shot_views(
    previous: StructuredDirectorDocument, current: StructuredDirectorDocument
) -> list[dict[str, str]]:
    del previous, current
    return []


def _changed_ids(previous, current) -> set[str]:
    def entities(document):
        result: dict[str, object] = {}
        for location in document.location_library.locations:
            result[location.id] = (location.name, location.description, location.key_light)
            for item in (*location.fixtures, *location.states, *location.images):
                result[item.id] = item
        for scene in () if document.director_script is None else document.director_script.scenes:
            result[scene.id] = (scene.location_id, scene.state_id)
        return result

    before, after = entities(previous), entities(current)
    return {
        item_id
        for item_id in before.keys() | after.keys()
        if before.get(item_id) != after.get(item_id)
    }
