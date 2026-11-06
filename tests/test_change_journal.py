"""变更日志：实体索引粒度、叶子完整性、日志连续性与 Store 接入。"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace

from test_director_commands import _location_project, _visual_project

from core.structured_director.change_journal import (
    PROJECT_KEY,
    ChangeJournal,
    changed_keys,
    entity_index,
)
from core.structured_director.codec import serialize_document

# 簿记与派生字段：改动它们不应产生任何变化键。
_EXCLUDED_PATHS = (
    ("revision",),
    ("application_requests",),
    ("structured_director", "director_script", "revision"),
    ("structured_director", "director_script", "production_baseline_revision"),
    ("structured_director", "director_script", "production_baseline_scenes"),
    ("structured_director", "dialogue_plan", "source_script_revision"),
    ("structured_director", "keyframe_plan", "source_script_revision"),
    ("structured_director", "video_plan", "source_script_revision"),
    ("structured_director", "final_assembly", "source_script_revision"),
)


def _visual(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    _, _, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    return document


def _location(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_location_project(str(tmp_path)))[2]


def _diff(document, mutate):
    before = serialize_document(document)
    after = copy.deepcopy(before)
    mutate(after)
    return changed_keys(entity_index(before), entity_index(after))


def _leaves(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, (*path, key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, (*path, index))
    else:
        yield path


def _set(value, path, mutate):
    for part in path[:-1]:
        value = value[part]
    value[path[-1]] = mutate(value[path[-1]])


def _bump(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    if value is None:
        return "x"
    return ["x"]


_ID_FIELDS = ("id", "segment_id", "dialogue_line_id", "scene_id", "gap_id")


def _excluded(path):
    names = tuple(item for item in path if isinstance(item, str))
    return any(names[: len(rule)] == rule for rule in _EXCLUDED_PATHS)


def test_every_leaf_is_classified_and_excluded_paths_never_conflict(tmp_path):
    """改动任一叶子都必须体现为某个键的变化；只有登记的簿记/派生字段例外。"""
    for document in (
        _visual(tmp_path / "visual"),
        _location(tmp_path / "location"),
    ):
        serialized = serialize_document(document)
        baseline = entity_index(serialized)
        leaves = list(_leaves(serialized))
        assert len(leaves) > 50
        for path in leaves:
            changed = copy.deepcopy(serialized)
            _set(changed, path, _bump)
            index = None
            # 空的实体集合或缺省的单个实体：依次换成带全部可能 ID 字段的条目或对象。
            for replacement in (None, [dict.fromkeys(_ID_FIELDS, "f" * 32)]):
                if replacement is not None:
                    _set(changed, path, lambda _, value=replacement: value)
                try:
                    index = entity_index(changed)
                    break
                except (TypeError, ValueError, KeyError):
                    continue
            if index is None:
                _set(changed, path, lambda _: dict.fromkeys(_ID_FIELDS, "f" * 32))
                index = entity_index(changed)
            keys = changed_keys(baseline, index)
            if _excluded(path):
                assert not keys, path
            else:
                assert keys, path


def test_selection_on_one_segment_changes_only_that_keyframe(tmp_path):
    document = _visual(tmp_path)
    keyframe = document.keyframe_plan.keyframes[0]

    def select(value):
        for item in value["structured_director"]["keyframe_plan"]["keyframes"]:
            if item["id"] == keyframe.id:
                item["selected_asset_id"] = "b" * 32

    assert _diff(document, select) == {keyframe.id}


def test_segment_bindings_share_the_segment_key(tmp_path):
    document = _visual(tmp_path)
    segment_id = document.keyframe_plan.segments[0].segment_id

    def enable_end(value):
        for item in value["structured_director"]["keyframe_plan"]["segments"]:
            if item["segment_id"] == segment_id:
                item["end_enabled"] = not item["end_enabled"]

    assert _diff(document, enable_end) == {segment_id}


def test_new_entities_and_bookkeeping_do_not_touch_the_project_key(tmp_path):
    document = _visual(tmp_path)

    def add_generation(value):
        generation = copy.deepcopy(value["generations"][0]) if value["generations"] else None
        if generation is None:
            value["assets"].append(
                {
                    "id": "d" * 32,
                    "media_type": "image/png",
                    "byte_count": 1,
                    "sha256": "0" * 64,
                    "relative_path": "assets/x.png",
                    "duration_seconds": None,
                }
            )
            return
        generation["id"] = "d" * 32
        value["generations"].append(generation)

    assert _diff(document, add_generation) == {"d" * 32}
    assert not changed_keys(
        entity_index(serialize_document(document)),
        entity_index(serialize_document(replace(document, revision=document.revision + 7))),
    )


def test_container_order_is_part_of_the_parent(tmp_path):
    document = _visual(tmp_path)
    scene = document.director_script.scenes[0]
    assert len(scene.shots) >= 2

    def swap(value):
        shots = value["structured_director"]["director_script"]["scenes"][0]["shots"]
        shots[0], shots[1] = shots[1], shots[0]

    assert _diff(document, swap) == {scene.id}


def test_global_fields_fall_into_the_project_key(tmp_path):
    document = _visual(tmp_path)

    def retitle(value):
        value["title"] += "改"

    def lock_layer(value):
        value["structured_director"]["workspace_layers"]["videos_unlocked"] = False

    assert _diff(document, retitle) == {PROJECT_KEY}
    assert _diff(document, lock_layer) == {PROJECT_KEY}


def test_journal_covers_only_a_continuous_range():
    journal = ChangeJournal(capacity=3)
    first = {"a": b"1", "b": b"1"}
    journal.record(None, None, 10, first)
    assert journal.changed_since(10, 10) == frozenset()
    assert journal.changed_since(9, 10) is None

    second = {"a": b"2", "b": b"1"}
    journal.record(10, first, 11, second)
    third = {"a": b"2", "b": b"2", "c": b"1"}
    journal.record(11, second, 12, third)
    assert journal.index_for(12) is third
    assert journal.changed_since(10, 12) == {"a", "b", "c"}
    assert journal.changed_since(11, 12) == {"b", "c"}
    assert journal.changed_since(12, 12) == frozenset()
    assert journal.changed_since(11, 13) is None

    # 超出容量：最早的条目被淘汰，覆盖起点后移。
    fourth = {"a": b"3", "b": b"2", "c": b"1"}
    journal.record(12, third, 13, fourth)
    fifth = {"a": b"3", "b": b"2", "c": b"2"}
    journal.record(13, fourth, 14, fifth)
    assert journal.changed_since(10, 14) is None
    assert journal.changed_since(11, 14) == {"a", "b", "c"}

    # 断档（例如进程外写入）：丢弃旧区间，从上一版重新开始。
    journal.record(20, fifth, 21, first)
    assert journal.changed_since(14, 21) is None
    assert journal.changed_since(20, 21) == {"a", "b", "c"}


def test_store_writes_feed_the_shared_journal(tmp_path):
    from core.structured_director.store import StructuredDirectorStore

    store, _, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    journal = store.change_journal
    assert journal.changed_since(document.revision, document.revision) == frozenset()

    keyframe = document.keyframe_plan.keyframes[0]
    updated = replace(
        document,
        revision=document.revision + 1,
        keyframe_plan=replace(
            document.keyframe_plan,
            keyframes=tuple(
                replace(item, prompt_text="新的画面") if item.id == keyframe.id else item
                for item in document.keyframe_plan.keyframes
            ),
        ),
    )
    # 另一个 Store 实例写同一项目，日志按项目路径共享。
    other = StructuredDirectorStore(store.path.parent, document.project_id)
    other._atomic_write(updated)
    assert store.change_journal is journal
    assert journal.changed_since(document.revision, updated.revision) == {keyframe.id}
