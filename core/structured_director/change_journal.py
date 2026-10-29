"""按实体记录每次提交改动了哪些对象，供写入冲突判定使用；只在内存，不是项目 authority。

实体索引建立在 codec JSON 上：每个登记的实体集合按 ID 拆出，实体自身 digest 不含子实体内容，
有序子集合以 ID 列表计入父实体；派生与簿记字段剥离；其余部分合成一个 ``PROJECT_KEY``。
未登记的新字段自动落入 ``PROJECT_KEY``，宁可多报冲突也不漏检。键是裸 ID、不区分类型：
同一 ID 下的多个对象（例如 Segment、它的关键帧绑定与视频计划）合并为一个 digest。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_KEY = "__project__"
_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class _Collection:
    """一个实体集合：``key`` 是条目的 ID 字段；``ordered`` 的集合把 ID 列表计入所在父对象。"""

    key: str
    ordered: bool
    children: dict[str, _Collection] = field(default_factory=dict)


def _ordered(key: str = "id", **children: _Collection) -> _Collection:
    return _Collection(key, True, children)


def _unordered(key: str = "id", **children: _Collection) -> _Collection:
    return _Collection(key, False, children)


_SCENE = _ordered(
    shots=_ordered(),
    segments=_ordered(dialogue_lines=_ordered()),
    narration_cues=_ordered(),
)

# 路径 → 集合。值为 dict 的条目是普通对象（继续向下找集合），值为 _Collection 的条目是实体集合。
_LAYOUT: dict[str, object] = {
    "assets": _unordered(),
    "generations": _unordered(),
    "structured_director": {
        "reference_library": {"characters": _unordered(looks=_ordered())},
        "director_script": {"scenes": _SCENE},
        "dialogue_plan": {"items": _unordered("dialogue_line_id")},
        "location_library": {
            "locations": _unordered(fixtures=_ordered(), states=_ordered(), images=_ordered())
        },
        "keyframe_plan": {"keyframes": _unordered(), "segments": _unordered("segment_id")},
        "video_plan": {"segments": _unordered("segment_id", reference_images=_ordered())},
        "final_assembly": {"clips": _ordered("scene_id")},
        "capability_gap_alerts": _unordered("gap_id"),
        "director_runs": _unordered(),
        "director_directives": _unordered(),
    },
}

# 簿记与派生字段：命令总在当前文档上重新执行时会被正确重算，不代表调用方的决策依据。
_EXCLUDED: dict[str, object] = {
    "revision": True,
    "application_requests": True,
    "structured_director": {
        "director_script": {
            "revision": True,
            "production_baseline_revision": True,
            "production_baseline_scenes": True,
        },
        "dialogue_plan": {"source_script_revision": True},
        "keyframe_plan": {"source_script_revision": True},
        "video_plan": {"source_script_revision": True},
        "final_assembly": {"source_script_revision": True},
    },
}

# 旁白身份是单个带 ID 的对象而不是集合。
_SINGLE_ENTITIES = {("structured_director", "reference_library", "narrator")}


def _digest(value: object) -> bytes:
    return hashlib.blake2b(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        digest_size=16,
    ).digest()


def _combine(values: list[tuple[str, bytes]]) -> bytes:
    if len(values) == 1:
        return values[0][1]
    combined = hashlib.blake2b(digest_size=16)
    for kind, digest in sorted(values):
        combined.update(kind.encode("utf-8") + b"\0" + digest)
    return combined.digest()


def entity_index(serialized: dict) -> dict[str, bytes]:
    """把 codec JSON 拆成 ``{实体键: digest}``；``serialized`` 不被修改。"""
    parts: dict[str, list[tuple[str, bytes]]] = {}

    def add(key: str, kind: str, value: object) -> None:
        parts.setdefault(key, []).append((kind, _digest(value)))

    def collect(items: list, spec: _Collection, kind: str) -> list[str]:
        keys = []
        for item in items:
            own = dict(item)
            for name, child in spec.children.items():
                if name not in own:
                    continue
                child_keys = collect(own.pop(name) or [], child, f"{kind}.{name}")
                if child.ordered:
                    own[name] = child_keys
            key = str(item[spec.key])
            add(key, kind, own)
            keys.append(key)
        return keys

    def strip(value: dict, layout: dict, excluded: dict, path: tuple[str, ...]) -> dict:
        remainder = {}
        for name, item in value.items():
            rule = excluded.get(name)
            if rule is True:
                continue
            here = (*path, name)
            if here in _SINGLE_ENTITIES:
                if item is not None:
                    add(str(item["id"]), ".".join(here), item)
                    remainder[name] = item["id"]
                else:
                    remainder[name] = None
                continue
            spec = layout.get(name)
            if isinstance(spec, _Collection):
                keys = collect(item, spec, ".".join(here))
                if spec.ordered:
                    remainder[name] = keys
                continue
            if isinstance(item, dict) and (isinstance(spec, dict) or isinstance(rule, dict)):
                remainder[name] = strip(
                    item,
                    spec if isinstance(spec, dict) else {},
                    rule if isinstance(rule, dict) else {},
                    here,
                )
                continue
            remainder[name] = item
        return remainder

    project = strip(serialized, _LAYOUT, _EXCLUDED, ())
    index = {key: _combine(values) for key, values in parts.items()}
    index[PROJECT_KEY] = _digest(project)
    return index


def changed_keys(before: dict[str, bytes], after: dict[str, bytes]) -> frozenset[str]:
    """新增、删除或内容变化的实体键。"""
    return frozenset(
        key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
    )


class ChangeJournal:
    """最近若干 revision 的变化集合；只覆盖连续区间，出现断档就从断点重新开始。"""

    def __init__(self, capacity: int = 1024) -> None:
        self._capacity = capacity
        self._lock = threading.Lock()
        self._index: tuple[int, dict[str, bytes]] | None = None
        self._base_revision: int | None = None
        self._entries: OrderedDict[int, frozenset[str]] = OrderedDict()

    def index_for(self, revision: int) -> dict[str, bytes] | None:
        """返回已缓存的该 revision 实体索引，避免每次提交都重新拆分上一版文档。"""
        with self._lock:
            if self._index is not None and self._index[0] == revision:
                return self._index[1]
            return None

    def record(
        self,
        previous_revision: int | None,
        previous_index: dict[str, bytes] | None,
        revision: int,
        index: dict[str, bytes],
    ) -> None:
        with self._lock:
            if (
                previous_revision is None
                or previous_index is None
                or revision != previous_revision + 1
            ):
                # 新建项目或无法得知上一版：从这里重新开始覆盖。
                self._entries.clear()
                self._base_revision = revision
            else:
                if self.last_revision != previous_revision:
                    # 断档（进程外写入、日志被淘汰后重建）：丢弃旧区间，从上一版重新开始。
                    self._entries.clear()
                    self._base_revision = previous_revision
                self._entries[revision] = changed_keys(previous_index, index)
                while len(self._entries) > self._capacity:
                    dropped, _ = self._entries.popitem(last=False)
                    self._base_revision = dropped
            self._index = (revision, index)

    @property
    def last_revision(self) -> int | None:
        if self._entries:
            return next(reversed(self._entries))
        return self._base_revision

    def changed_since(self, revision: int, current: int) -> frozenset[str] | None:
        """``(revision, current]`` 区间内变化过的实体键；日志不能完整覆盖时返回 None。"""
        with self._lock:
            if self._base_revision is None or self.last_revision != current:
                return None
            if not self._base_revision <= revision <= current:
                return None
            changed: set[str] = set()
            for entry_revision, keys in self._entries.items():
                if entry_revision > revision:
                    changed |= keys
            return frozenset(changed)


_JOURNALS: OrderedDict[Path, ChangeJournal] = OrderedDict()
_JOURNALS_LOCK = threading.Lock()
_MAX_JOURNALS = 64


def journal_for(path: Path) -> ChangeJournal:
    """按 project.json 路径共享：同一进程内多个 Store 实例写同一项目时看到同一份日志。"""
    with _JOURNALS_LOCK:
        journal = _JOURNALS.get(path)
        if journal is None:
            journal = _JOURNALS[path] = ChangeJournal()
            while len(_JOURNALS) > _MAX_JOURNALS:
                _JOURNALS.popitem(last=False)
        else:
            _JOURNALS.move_to_end(path)
        return journal


def argument_ids(value: object) -> frozenset[str]:
    """命令参数里出现的全部实体 ID：调用方据以决策的对象。"""
    found: set[str] = set()

    def walk(item: object) -> None:
        if isinstance(item, str):
            if _ID.fullmatch(item):
                found.add(item)
        elif isinstance(item, dict):
            for nested in item.values():
                walk(nested)
        elif isinstance(item, list | tuple):
            for nested in item:
                walk(nested)

    walk(value)
    return frozenset(found)


@dataclass(slots=True)
class RebaseScope:
    """一次落后于当前 revision 的写请求：原 revision、判定时的 revision 与依赖的实体。

    判定失败时记录 ``reason``（``entities_changed`` / ``journal_unavailable``）与相交的实体键。
    """

    expected_revision: int
    accepted_revision: int
    dependencies: frozenset[str]
    reason: str | None = None
    conflicts: frozenset[str] = frozenset()


rebase_scope: ContextVar[RebaseScope | None] = ContextVar("storyrail_rebase_scope", default=None)
