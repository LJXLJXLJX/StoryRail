from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    kind: str
    state: str
    progress: float
    message: str
    task_dir: str
    artifact_name: str | None = None
    artifact_media_type: str | None = None
    artifact_size: int | None = None
    artifact_sha256: str | None = None
    error_code: str | None = None
    retryable: bool = False
    cancel_requested: bool = False


class TaskStore:
    """默认实现自己的运行事实；不会被 Core 或 project.json 读取。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.tasks_root = self.root / "tasks"
        self.state_path = self.root / "runtime-state.json"
        self.tasks_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: dict[str, TaskRecord] = {}
        self._load()

    def create(self, kind: str) -> TaskRecord:
        with self._lock:
            task_id = uuid.uuid4().hex
            task_dir = self.tasks_root / task_id
            task_dir.mkdir(parents=False)
            record = TaskRecord(task_id, kind, "queued", 0.0, "等待模型资源。", str(task_dir))
            self._records[task_id] = record
            self._save()
            return _copy(record)

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._records.get(task_id)
            return _copy(record) if record else None

    def list_recoverable(self) -> list[TaskRecord]:
        with self._lock:
            return [
                _copy(item) for item in self._records.values() if item.state not in TERMINAL_STATES
            ]

    def update(self, task_id: str, **changes: Any) -> TaskRecord:
        with self._lock:
            record = self._records[task_id]
            for name, value in changes.items():
                if not hasattr(record, name):
                    raise ValueError(f"未知 TaskRecord 字段：{name}")
                setattr(record, name, value)
            self._save()
            return _copy(record)

    def request_cancel(
        self,
        task_id: str,
        *,
        message: str = "已在取得资源前取消。",
        error_code: str | None = None,
    ) -> TaskRecord:
        with self._lock:
            record = self._records[task_id]
            if record.state not in TERMINAL_STATES:
                record.cancel_requested = True
                record.error_code = error_code
                if record.state == "queued":
                    record.state = "cancelled"
                    record.message = message
            self._save()
            return _copy(record)

    def artifact_path(self, record: TaskRecord) -> Path | None:
        if not record.artifact_name:
            return None
        root = Path(record.task_dir).resolve()
        candidate = (root / record.artifact_name).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"schema_version", "tasks"}
            or data["schema_version"] != 1
        ):
            raise RuntimeError("默认 Provider runtime-state.json schema 不受支持。")
        if not isinstance(data["tasks"], list):
            raise RuntimeError("默认 Provider runtime-state.json tasks 不合法。")
        for item in data["tasks"]:
            if not isinstance(item, dict) or set(item) != set(TaskRecord.__dataclass_fields__):
                raise RuntimeError("默认 Provider runtime-state.json TaskRecord 字段不合法。")
            record = TaskRecord(**item)
            if record.task_id in self._records:
                raise RuntimeError("默认 Provider runtime-state.json 存在重复 task_id。")
            if record.state == "running":
                artifact = self.artifact_path(record)
                if artifact is None:
                    # 进程消失时无法证明模型调用是否产生过外部副作用，也不能从任意
                    # 中间 tensor 安全续算。自动重跑长视频可能形成重启/蓝屏循环，
                    # 因此保留失败事实，交给 Core 创建新的 retry generation。
                    record.state = "failed"
                    record.message = "模型服务在执行期间重启；任务已终止，请人工重试。"
                    record.error_code = "runtime_interrupted"
                    record.retryable = True
                    record.cancel_requested = False
                else:
                    record.state = "succeeded"
                    record.progress = 1.0
                    record.message = "服务重启后确认产物已完成。"
            self._records[record.task_id] = record
        self._save()

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        value = {
            "schema_version": 1,
            "tasks": [asdict(self._records[key]) for key in sorted(self._records)],
        }
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.state_path)


def _copy(record: TaskRecord) -> TaskRecord:
    return TaskRecord(**asdict(record))
