"""Playground 权威文件的原子持久化与 Asset 文件管理。

Store 自身不加锁：串行化写入由 ``PlaygroundService`` 的 ``asyncio.Lock`` 保证。
``commit`` 校验「新 revision = 旧 revision + 1」后原子替换 ``playground.json``。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from core.media_assets import (
    MEDIA_EXTENSION,
    asset_filename,
    mp4_duration,
    validate_media_bytes,
    wav_duration,
)
from core.model_providers.contracts import validate_pano_source

from .codec import parse_document, serialize_document
from .lifecycle import recover_interrupted, utc_timestamp
from .models import (
    PLAYGROUND_SCHEMA_VERSION,
    AssetOrigin,
    PlaygroundAsset,
    PlaygroundDocument,
    PlaygroundRun,
)

_MEDIA_DIRECTORY = {"image": "images", "audio": "audio", "video": "videos"}

_ORIGIN_DIRECTORIES = frozenset({"imported", "runs", "from-projects"})

StagedAssetFiles = tuple[tuple[Path, Path], ...]


class PlaygroundStore:
    filename = "playground.json"

    def __init__(self, root_directory: Path) -> None:
        if root_directory.is_symlink():
            raise ValueError("Playground 目录不能是符号链接。")
        # 父目录 .stories 由 ProjectWorkspaceStore 保证存在。
        root_directory.mkdir(exist_ok=True)
        self._root_directory = root_directory
        self._path = root_directory / self.filename
        self._assets_directory = root_directory / "assets"
        self._observations: dict[str, PlaygroundRun] = {}
        # Asset 字节不可变，按 SHA-256 缓存“能否作为全景裁切输入”，快照不必重复解码。
        self._pano_sources: dict[str, bool] = {}

    @property
    def path(self) -> Path:
        return self._path

    @property
    def root_directory(self) -> Path:
        return self._root_directory

    @property
    def assets_directory(self) -> Path:
        return self._assets_directory

    def ensure_created(self) -> PlaygroundDocument:
        if self._path.is_symlink():
            raise ValueError("playground.json 不能是符号链接。")
        if self._path.is_file():
            return self.read()
        document = PlaygroundDocument(schema_version=PLAYGROUND_SCHEMA_VERSION, revision=1)
        self._atomic_write(document, exclusive=True)
        return document

    def read(self) -> PlaygroundDocument:
        if self._path.is_symlink() or not self._path.is_file():
            raise FileNotFoundError("Playground 尚未建立。")
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("playground.json 不是合法 JSON。") from exc
        return parse_document(value)

    def commit(
        self, mutate: Callable[[PlaygroundDocument], PlaygroundDocument]
    ) -> PlaygroundDocument:
        previous = self.read()
        updated = mutate(previous)
        if updated is previous:
            return previous
        if updated.revision != previous.revision + 1:
            raise RuntimeError("Playground revision 提交不一致。")
        self._atomic_write(updated)
        return updated

    def read_asset(self, asset_id: str) -> tuple[PlaygroundAsset, bytes]:
        document = self.read()
        asset = next((item for item in document.assets if item.id == asset_id), None)
        if asset is None:
            raise FileNotFoundError("Asset 不存在。")
        path = self._root_directory / asset.relative_path
        if path.is_symlink() or not path.is_file():
            raise ValueError("Asset 文件不存在或类型不合法。")
        content = path.read_bytes()
        if len(content) != asset.byte_count or hashlib.sha256(content).hexdigest() != asset.sha256:
            raise ValueError("Asset 内容校验失败。")
        return asset, content

    def is_pano_source(self, asset: PlaygroundAsset) -> bool:
        """该 Asset 是否满足全景裁切输入契约（2:1 PNG/JPEG、宽 1024–16384、≤64 MiB）。"""
        if asset.media_type not in {"image/png", "image/jpeg"}:
            return False
        cached = self._pano_sources.get(asset.sha256)
        if cached is None:
            path = self._root_directory / asset.relative_path
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Asset 文件不存在。")
                validate_pano_source(path.read_bytes())
                cached = True
            except (OSError, ValueError):
                cached = False
            self._pano_sources[asset.sha256] = cached
        return cached

    def ingest_asset(
        self,
        document: PlaygroundDocument,
        *,
        media_type: str,
        content: bytes,
        origin_dir: str,
        label: str,
        origin: AssetOrigin,
        created_at: str,
        duration_seconds: float | None = None,
    ) -> tuple[PlaygroundDocument, PlaygroundAsset]:
        if origin_dir not in _ORIGIN_DIRECTORIES:
            raise ValueError("Asset 来源目录不合法。")
        validate_media_bytes(media_type, content)
        sha256 = hashlib.sha256(content).hexdigest()
        asset_id = sha256[:32]
        existing = next((item for item in document.assets if item.id == asset_id), None)
        if existing is not None:
            return document, existing
        extension = MEDIA_EXTENSION[media_type]
        directory = _MEDIA_DIRECTORY[media_type.split("/", 1)[0]]
        relative_path = (
            f"assets/{directory}/{origin_dir}/{asset_filename(label)}-{sha256[:10]}.{extension}"
        )
        if media_type == "audio/wav":
            duration = wav_duration(content)
        elif media_type == "video/mp4":
            duration = duration_seconds if duration_seconds is not None else mp4_duration(content)
        else:
            duration = None
        asset = PlaygroundAsset(
            id=asset_id,
            media_type=media_type,
            byte_count=len(content),
            sha256=sha256,
            relative_path=relative_path,
            duration_seconds=duration,
            origin=origin,
            created_at=created_at,
        )
        self._write_asset(asset, content)
        return replace(document, assets=(*document.assets, asset)), asset

    def stage_asset_files(self, assets: tuple[PlaygroundAsset, ...]) -> StagedAssetFiles:
        """把 Asset 文件移到 ``assets/.deleting-*``；失败时回滚已经移动的文件。"""
        sources = tuple((item, self._root_directory / item.relative_path) for item in assets)
        for _, source in sources:
            if source.is_symlink() or not source.is_file():
                raise ValueError("Asset 文件不存在或类型不合法。")
        staged_files: list[tuple[Path, Path]] = []
        try:
            for item, source in sources:
                staged = self._assets_directory / f".deleting-{item.sha256}-{uuid4().hex}"
                os.replace(source, staged)
                staged_files.append((staged, source))
        except Exception:
            self.restore_staged_asset_files(tuple(staged_files))
            raise
        return tuple(staged_files)

    def restore_staged_asset_files(self, staged_files: StagedAssetFiles) -> None:
        for staged, source in reversed(staged_files):
            os.replace(staged, source)

    def unlink_staged_asset_files(self, staged_files: StagedAssetFiles) -> None:
        for staged, _source in staged_files:
            staged.unlink(missing_ok=True)

    def remove_asset_files(self, assets: tuple[PlaygroundAsset, ...]) -> None:
        """移动后立即删除；只用于之后不会再失败的路径。"""
        self.unlink_staged_asset_files(self.stage_asset_files(assets))

    def recover_interrupted_submissions(self) -> PlaygroundDocument:
        def mutate(document: PlaygroundDocument) -> PlaygroundDocument:
            updated, changed = recover_interrupted(document, timestamp=utc_timestamp())
            return updated if changed else document

        return self.commit(mutate)

    def record_observation(self, run: PlaygroundRun) -> None:
        self._observations[run.id] = run

    def observed_run(self, run: PlaygroundRun) -> PlaygroundRun:
        """仅供 UI 展示的临时观察值，绝不回写领域决策。"""
        observed = self._observations.get(run.id)
        if observed is not None and observed.phase == run.phase:
            return replace(run, progress=observed.progress, message=observed.message)
        return run

    def _write_asset(self, asset: PlaygroundAsset, content: bytes) -> None:
        if self._assets_directory.is_symlink() or (
            self._assets_directory.exists() and not self._assets_directory.is_dir()
        ):
            raise ValueError("assets 必须是普通目录。")
        self._assets_directory.mkdir(exist_ok=True)
        destination = self._root_directory / asset.relative_path
        self._ensure_asset_directory(destination.parent)
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise ValueError("Asset 目标不是普通文件。")
            existing = destination.read_bytes()
            if hashlib.sha256(existing).hexdigest() != asset.sha256:
                raise ValueError("Asset 文件与内容哈希不一致。")
            return
        temporary = destination.parent / f".{asset.sha256}.{uuid4().hex}.tmp"
        try:
            with temporary.open("x+b") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _ensure_asset_directory(self, directory: Path) -> None:
        current = self._assets_directory
        for component in directory.relative_to(self._assets_directory).parts:
            current = current / component
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise ValueError("Asset 子目录必须是普通目录。")
            current.mkdir(exist_ok=True)

    def _atomic_write(self, document: PlaygroundDocument, *, exclusive: bool = False) -> None:
        serialized = json.dumps(serialize_document(document), ensure_ascii=False, indent=2) + "\n"
        temporary = self._root_directory / f".{self.filename}.{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as target:
                target.write(serialized)
                target.flush()
                os.fsync(target.fileno())
            if exclusive and (self._path.exists() or self._path.is_symlink()):
                raise FileExistsError("Playground 已经建立。")
            os.replace(temporary, self._path)
        finally:
            if temporary.exists():
                temporary.unlink()
