"""全局 Provider 设置：能力绑定与插件实例设置的唯一持久化位置。

文件是 ``.runtime/providers.json``（被忽略的本机状态目录），原子替换。这里只做结构校验；
设置值是否合法由插件 manifest 判断，因此卸载插件或 manifest 升级后旧值原样保留，
由注册表在读取时决定是否生效。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProviderSettingsState:
    bindings: dict[str, str] = field(default_factory=dict)
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "bindings": dict(sorted(self.bindings.items())),
            "settings": {key: dict(value) for key, value in sorted(self.settings.items())},
        }

    @classmethod
    def from_json(cls, value: object) -> ProviderSettingsState:
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "bindings", "settings"}
            or value["schema_version"] != SCHEMA_VERSION
        ):
            raise ValueError("全局 Provider 设置文件不合法。")
        bindings, settings = value["bindings"], value["settings"]
        if not isinstance(bindings, dict) or any(
            not isinstance(key, str) or not isinstance(item, str) for key, item in bindings.items()
        ):
            raise ValueError("全局 Provider 能力绑定不合法。")
        if not isinstance(settings, dict) or any(
            not isinstance(key, str) or not isinstance(item, dict) for key, item in settings.items()
        ):
            raise ValueError("全局 Provider 插件设置不合法。")
        return cls(dict(bindings), {key: dict(item) for key, item in settings.items()})


class ProviderSettingsStore:
    """进程级设置；``path`` 为 None 时只在内存中保存（测试与未配置状态目录时）。"""

    def __init__(self, path: Path | None = None) -> None:
        self._path = None if path is None else path.resolve(strict=False)
        self._lock = threading.RLock()
        self._state = self._load()

    def read(self) -> ProviderSettingsState:
        with self._lock:
            return self._state

    def write(self, state: ProviderSettingsState) -> ProviderSettingsState:
        with self._lock:
            if state != self._state:
                self._save(state)
                self._state = state
            return self._state

    def _load(self) -> ProviderSettingsState:
        if self._path is None or not self._path.exists():
            return ProviderSettingsState()
        return ProviderSettingsState.from_json(json.loads(self._path.read_text(encoding="utf-8")))

    def _save(self, state: ProviderSettingsState) -> None:
        if self._path is None:
            return
        root = self._path.parent
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / f".{uuid.uuid4().hex}.tmp"
        with temporary.open("x", encoding="utf-8") as target:
            json.dump(state.to_json(), target, ensure_ascii=False, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, self._path)
