from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from core.project_settings import ProjectAspectRatio
from core.structured_director.models import NarrationLanguage, ReferenceGenerationPhase
from core.structured_director.store import StructuredDirectorStore

_PROJECT_ID = re.compile(r"[0-9a-f]{32}")
_PROJECT_DIRECTORY = re.compile(r"(?:.+-)?([0-9a-f]{32})")


def project_directory_name(title: str, project_id: str) -> str:
    """只编译磁盘显示名；完整 Project ID 保持 API 与对象身份不变。"""
    if not _PROJECT_ID.fullmatch(project_id):
        raise ValueError("项目 ID 无效。")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", title.strip())
    # 最坏情况下 48 个四字节字符加 ID 仍低于常见文件系统的 255 字节限制。
    name = name[:48].strip(" .") or "项目"
    return f"{name}-{project_id}"


class ProjectWorkspaceStatus(StrEnum):
    ACTIVE = "active"
    NEEDS_RECOVERY = "needs_recovery"


@dataclass(frozen=True, slots=True)
class ProjectWorkspace:
    id: str
    title: str
    aspect_ratio: ProjectAspectRatio
    updated_at: str
    status: ProjectWorkspaceStatus


class ProjectWorkspaceStore:
    """管理受控根目录下的项目工作区，不接受调用方提供的路径。"""

    def __init__(self, root_directory: Path) -> None:
        if root_directory.is_symlink():
            raise ValueError("项目根目录不能是符号链接。")
        self._root = root_directory.resolve(strict=False)
        if self._root.exists() and not self._root.is_dir():
            raise ValueError("项目根目录必须是目录。")
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root_directory(self) -> Path:
        return self._root

    def list(self) -> tuple[ProjectWorkspace, ...]:
        workspaces: list[ProjectWorkspace] = []
        for path in self._root.iterdir():
            match = _PROJECT_DIRECTORY.fullmatch(path.name)
            if match is None or path.is_symlink() or not path.is_dir():
                continue
            try:
                workspaces.append(self._summarize(match[1]))
            except (FileNotFoundError, ValueError):
                continue
        return tuple(sorted(workspaces, key=lambda item: item.updated_at, reverse=True))

    def create(
        self,
        title: str,
        director_plan_markdown: str,
        *,
        aspect_ratio: ProjectAspectRatio,
        narration_languages: tuple[NarrationLanguage, ...],
    ) -> ProjectWorkspace:
        if not isinstance(aspect_ratio, ProjectAspectRatio):
            raise ValueError("aspect_ratio 只允许 16:9、9:16 或 2:1。")
        project_id = uuid4().hex
        path = self._root / project_directory_name(title, project_id)
        path.mkdir()
        try:
            StructuredDirectorStore(path, project_id).create_project(
                title=title,
                aspect_ratio=aspect_ratio,
                director_plan_markdown=director_plan_markdown,
                narration_languages=narration_languages,
            )
        except Exception:
            candidate = path / StructuredDirectorStore.filename
            if candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
            if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()
            raise
        return self._summarize(project_id)

    def get(self, project_id: str) -> ProjectWorkspace:
        self._require_project_directory(project_id)
        return self._summarize(project_id)

    def structured_director_store(self, project_id: str) -> StructuredDirectorStore:
        project = self._require_project_directory(project_id)
        return StructuredDirectorStore(project, project_id)

    def move_to_trash(self, project_id: str) -> ProjectWorkspace:
        workspace = self.get(project_id)
        source = self._require_project_directory(project_id)
        trash = self._root / ".trash"
        if trash.is_symlink():
            raise ValueError("项目回收站不能是符号链接。")
        trash.mkdir(exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = trash / f"{source.name}-{timestamp}-{uuid4().hex[:8]}"
        os.replace(source, destination)
        return workspace

    def _summarize(self, project_id: str) -> ProjectWorkspace:
        path = self._require_project_directory(project_id)
        structured_store = StructuredDirectorStore(path, project_id)
        structured_snapshot = structured_store.read()
        needs_recovery = structured_snapshot.active_director_run is not None or any(
            item.phase is ReferenceGenerationPhase.SUBMITTING
            for item in structured_snapshot.generations
        )
        status = (
            ProjectWorkspaceStatus.NEEDS_RECOVERY
            if needs_recovery
            else ProjectWorkspaceStatus.ACTIVE
        )
        updated_at = (
            datetime.fromtimestamp(structured_store.path.stat().st_mtime, UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return ProjectWorkspace(
            project_id,
            structured_snapshot.title,
            structured_snapshot.aspect_ratio,
            updated_at,
            status,
        )

    def _require_project_directory(self, project_id: str) -> Path:
        if not _PROJECT_ID.fullmatch(project_id):
            raise KeyError("项目不存在。")
        matches = [
            path
            for path in self._root.iterdir()
            if (match := _PROJECT_DIRECTORY.fullmatch(path.name)) is not None
            and match[1] == project_id
            and not path.is_symlink()
            and path.is_dir()
        ]
        if not matches:
            raise KeyError("项目不存在。")
        if len(matches) != 1:
            raise ValueError("项目 ID 对应多个目录，请先处理重复副本。")
        return matches[0]
