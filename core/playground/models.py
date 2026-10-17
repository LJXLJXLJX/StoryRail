"""领域模型：Playground 全局实验工作区（schema v2：run 记录 provider_snapshot）。

这里是 L0：只做不依赖其它对象的自洽校验，不访问磁盘、不认识 Asset 实体是否存在，
也不解析逐能力参数（那属于 ``core/playground/parameters.py``）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Literal

from core.model_providers.manifest import Capability, ProviderSnapshot, Recipe

PLAYGROUND_SCHEMA_VERSION = 2

_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ASSET_PATH = re.compile(
    r"assets/(images|audio|videos)/(imported|runs|from-projects)/[^/\\\x00-\x1f]+"
    r"\.(png|jpg|webp|wav|mp4)"
)

_MEDIA_DIRECTORY = {
    "image/png": "images",
    "image/jpeg": "images",
    "image/webp": "images",
    "audio/wav": "audio",
    "video/mp4": "videos",
}

_MEDIA_EXTENSION = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "audio/wav": "wav",
    "video/mp4": "mp4",
}

MEDIA_TYPES = frozenset(_MEDIA_EXTENSION)

_TIMED_MEDIA_TYPES = frozenset({"audio/wav", "video/mp4"})


def canonical_json(value: object) -> str:
    """Playground 持久化与摘要统一使用的规范化 JSON 文本。"""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class PlaygroundCapability(StrEnum):
    """Core 确定性工具；模型入口直接使用已安装插件的 recipe ID。"""

    VIDEO_EXTRACT_FRAME = "video.extract_frame"
    IMAGE_PANO_VIEW = "image.pano_view"
    AUDIO_REMIX = "audio.remix"
    AUDIO_EFFECT = "audio.effect"
    AUDIO_TRIM = "audio.trim"


class RunPhase(StrEnum):
    SUBMITTING = "submitting"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


SYNC_CAPABILITIES = frozenset(
    {
        PlaygroundCapability.AUDIO_EFFECT,
        PlaygroundCapability.AUDIO_TRIM,
    }
)

# 不经过任何 Provider、完全在 Core 本地执行的能力。
LOCAL_CAPABILITIES = frozenset(
    {
        PlaygroundCapability.AUDIO_EFFECT,
        PlaygroundCapability.AUDIO_TRIM,
    }
)

TERMINAL_PHASES = frozenset(
    {
        RunPhase.SUCCEEDED,
        RunPhase.FAILED,
        RunPhase.CANCELLED,
        RunPhase.SUBMISSION_UNCERTAIN,
    }
)

# 需要占用输入 Asset、不允许被删除的阶段。
UNFINISHED_PHASES = frozenset(
    {
        RunPhase.SUBMITTING,
        RunPhase.QUEUED,
        RunPhase.RUNNING,
        RunPhase.SUBMISSION_UNCERTAIN,
    }
)


def _require_id(value: str, field: str) -> None:
    if not _ID.fullmatch(value):
        raise ValueError(f"{field} 不合法。")


def _validate_timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 不合法。") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须是带时区的 ISO 8601 时间。")


def _coerce(enum_type, value: object, field: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field} 不受支持。") from exc


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是数字。")
    if not isfinite(value):
        raise ValueError(f"{field} 必须是有限数字。")
    return float(value)


@dataclass(frozen=True, slots=True)
class AssetOrigin:
    kind: Literal["imported", "run_output", "copied_from_project"]
    run_id: str | None = None
    project_id: str | None = None
    asset_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "imported":
            if self.run_id is not None or self.project_id is not None or self.asset_id is not None:
                raise ValueError("asset.origin 的 imported 形状不合法。")
            return
        if self.kind == "run_output":
            if self.project_id is not None or self.asset_id is not None or self.run_id is None:
                raise ValueError("asset.origin 的 run_output 形状不合法。")
            _require_id(self.run_id, "asset.origin.run_id")
            return
        if self.kind == "copied_from_project":
            if self.run_id is not None or self.project_id is None or self.asset_id is None:
                raise ValueError("asset.origin 的 copied_from_project 形状不合法。")
            _require_id(self.project_id, "asset.origin.project_id")
            _require_id(self.asset_id, "asset.origin.asset_id")
            return
        raise ValueError("asset.origin.kind 不受支持。")


_MEDIA_EXTENSION_KIND = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "audio/wav": "audio",
    "video/mp4": "video",
}


@dataclass(frozen=True, slots=True)
class PlaygroundAsset:
    id: str
    media_type: str
    byte_count: int
    sha256: str
    relative_path: str
    duration_seconds: float | None
    origin: AssetOrigin
    created_at: str

    @property
    def display_name(self) -> str:
        """去掉末尾的 ``-<10 hex>`` 与扩展名后的可读名；项目侧 filename 会补回扩展名。"""
        filename = self.relative_path.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        return re.sub(r"-[0-9a-f]{10}$", "", stem)

    @property
    def media_kind(self) -> Literal["image", "audio", "video"]:
        return _MEDIA_EXTENSION_KIND[self.media_type]

    def __post_init__(self) -> None:
        _require_id(self.id, "asset.id")
        if self.media_type not in _MEDIA_EXTENSION:
            raise ValueError("asset.media_type 不受支持。")
        if self.id != self.sha256[:32]:
            raise ValueError("asset.id 必须等于 sha256 的前 32 位。")
        maximum = 2 * 1024 * 1024 * 1024 if self.media_type == "video/mp4" else 64 * 1024 * 1024
        if isinstance(self.byte_count, bool) or not 1 <= self.byte_count <= maximum:
            raise ValueError("asset.byte_count 不合法。")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError("asset.sha256 不合法。")
        matched = _ASSET_PATH.fullmatch(self.relative_path)
        if matched is None:
            raise ValueError("asset.relative_path 不合法。")
        if matched.group(1) != _MEDIA_DIRECTORY[self.media_type]:
            raise ValueError("asset.relative_path 的媒体目录与 media_type 不一致。")
        if matched.group(3) != _MEDIA_EXTENSION[self.media_type]:
            raise ValueError("asset.relative_path 的扩展名与 media_type 不一致。")
        if self.media_type in _TIMED_MEDIA_TYPES:
            if self.duration_seconds is None:
                raise ValueError("asset.duration_seconds 不能为空。")
            if _finite_number(self.duration_seconds, "asset.duration_seconds") <= 0:
                raise ValueError("asset.duration_seconds 必须大于 0。")
        elif self.duration_seconds is not None:
            raise ValueError("图片 Asset 的 duration_seconds 必须为空。")
        if not isinstance(self.origin, AssetOrigin):
            raise ValueError("asset.origin 不合法。")
        _validate_timestamp(self.created_at, "asset.created_at")


@dataclass(frozen=True, slots=True)
class PlaygroundRun:
    id: str
    capability: str
    phase: RunPhase
    progress: float
    message: str
    parameters_json: str
    input_asset_ids: tuple[str, ...]
    seed: int | None
    plugin_id: str | None
    plugin_version: int | None
    external_id: str | None
    output_asset_id: str | None
    result_json: str | None
    error_code: str | None
    cancellation_requested: bool
    retry_of: str | None
    note: str | None
    dismissed: bool
    created_at: str
    updated_at: str
    # 提交时实际使用的插件、recipe 与生效设置；本地确定性能力为 None。
    provider_snapshot: ProviderSnapshot | None = None
    recipe: Recipe | None = None

    @property
    def parameters(self) -> dict[str, object]:
        return json.loads(self.parameters_json)

    @property
    def result(self) -> dict[str, object] | None:
        return None if self.result_json is None else json.loads(self.result_json)

    def __post_init__(self) -> None:
        _require_id(self.id, "run.id")
        if self.recipe is not None and not isinstance(self.recipe, Recipe):
            raise ValueError("run.recipe 必须是提交时 recipe 声明。")
        if self.recipe is None:
            object.__setattr__(
                self, "capability", _coerce(PlaygroundCapability, self.capability, "run.capability")
            )
        elif self.capability != self.recipe.id:
            raise ValueError("run.capability 与提交时 recipe 不一致。")
        object.__setattr__(self, "phase", _coerce(RunPhase, self.phase, "run.phase"))
        progress = _finite_number(self.progress, "run.progress")
        if not 0 <= progress <= 1:
            raise ValueError("run.progress 必须在 0 到 1 之间。")
        if not isinstance(self.message, str) or len(self.message) > 2000:
            raise ValueError("run.message 不能为空或超过 2000 字符。")
        if not isinstance(self.parameters_json, str):
            raise ValueError("run.parameters 必须是 JSON 对象。")
        try:
            parameters = json.loads(self.parameters_json)
        except ValueError as exc:
            raise ValueError("run.parameters 必须是 JSON 对象。") from exc
        if not isinstance(parameters, dict):
            raise ValueError("run.parameters 必须是 JSON 对象。")
        for asset_id in self.input_asset_ids:
            _require_id(asset_id, "run.input_asset_ids")
        if len(set(self.input_asset_ids)) != len(self.input_asset_ids):
            raise ValueError("run.input_asset_ids 不能重复。")
        if self.seed is not None:
            if isinstance(self.seed, bool) or not isinstance(self.seed, int):
                raise ValueError("run.seed 必须是整数。")
            if not 0 <= self.seed <= 2**63 - 1:
                raise ValueError("run.seed 超出范围。")
        if (self.plugin_id is None) != (self.plugin_version is None):
            raise ValueError("run.plugin_id 与 run.plugin_version 必须同时存在或同时为空。")
        if self.plugin_version is not None and (
            isinstance(self.plugin_version, bool) or not isinstance(self.plugin_version, int)
        ):
            raise ValueError("run.plugin_version 必须是整数。")
        if self.phase in {RunPhase.QUEUED, RunPhase.RUNNING} and not self.external_id:
            raise ValueError("排队或运行中的实验必须有 external_id。")
        if (
            self.capability in SYNC_CAPABILITIES
            or (self.recipe is not None and self.recipe.capability is Capability.SPEECH_RECOGNIZE)
        ) and self.external_id is not None:
            raise ValueError("同步能力不能有 external_id。")
        if self.output_asset_id is not None:
            _require_id(self.output_asset_id, "run.output_asset_id")
            if self.phase is not RunPhase.SUCCEEDED:
                raise ValueError("只有成功的实验才能有产物。")
        if self.result_json is not None:
            if len(self.result_json) > 20000:
                raise ValueError("run.result 超过 20000 字符。")
            try:
                parsed = json.loads(self.result_json)
            except ValueError as exc:
                raise ValueError("run.result 必须是 JSON 对象。") from exc
            if not isinstance(parsed, dict):
                raise ValueError("run.result 必须是 JSON 对象。")
            if self.phase is not RunPhase.SUCCEEDED:
                raise ValueError("只有成功的实验才能有 result。")
        if self.phase is RunPhase.FAILED and not self.error_code:
            raise ValueError("失败的实验必须有 error_code。")
        if self.phase is RunPhase.SUCCEEDED:
            self._validate_success()
        if self.dismissed and self.phase not in TERMINAL_PHASES:
            raise ValueError("只有已结束的实验可以被隐藏。")
        if self.cancellation_requested is not True and self.cancellation_requested is not False:
            raise ValueError("run.cancellation_requested 必须是布尔值。")
        if self.retry_of is not None:
            _require_id(self.retry_of, "run.retry_of")
        if self.note is not None and (
            not isinstance(self.note, str) or not 1 <= len(self.note.strip()) <= 200
        ):
            raise ValueError("run.note 必须是 1 到 200 字符的文本。")
        _validate_timestamp(self.created_at, "run.created_at")
        _validate_timestamp(self.updated_at, "run.updated_at")

    def _validate_success(self) -> None:
        if self.recipe is not None and self.recipe.capability is Capability.SPEECH_RECOGNIZE:
            if self.output_asset_id is not None:
                raise ValueError("语音转写不产生 Asset 产物。")
            if self.result_json is None or "transcript" not in json.loads(self.result_json):
                raise ValueError("成功的语音转写必须有 transcript。")
            return
        if self.output_asset_id is None:
            raise ValueError("成功的实验必须有产物。")
        if self.capability in LOCAL_CAPABILITIES:
            if self.result_json is None:
                raise ValueError("成功的本地音频处理必须有 result。")
            return
        if self.result_json is not None:
            raise ValueError("异步能力不能有 result。")


@dataclass(frozen=True, slots=True)
class PlaygroundRequestRecord:
    request_id: str
    caller_id: str
    idempotency_key: str
    request_digest: str
    operation: str
    receipt_json: str
    created_at: str

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.request_id):
            raise ValueError("request.request_id 不合法。")
        if not isinstance(self.caller_id, str) or not 1 <= len(self.caller_id) <= 80:
            raise ValueError("request.caller_id 必须是 1 到 80 字符的文本。")
        if not isinstance(self.idempotency_key, str) or not 1 <= len(self.idempotency_key) <= 200:
            raise ValueError("request.idempotency_key 必须是 1 到 200 字符的文本。")
        if not _SHA256.fullmatch(self.request_digest):
            raise ValueError("request.request_digest 不合法。")
        if not isinstance(self.operation, str) or not self.operation:
            raise ValueError("request.operation 不能为空。")
        if not isinstance(self.receipt_json, str) or len(self.receipt_json) > 200000:
            raise ValueError("request.receipt_json 不能为空或超过 200000 字符。")
        _validate_timestamp(self.created_at, "request.created_at")


@dataclass(frozen=True, slots=True)
class PlaygroundDocument:
    schema_version: int
    revision: int
    assets: tuple[PlaygroundAsset, ...] = ()
    runs: tuple[PlaygroundRun, ...] = ()
    application_requests: tuple[PlaygroundRequestRecord, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise ValueError("document.schema_version 必须是整数。")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("document.revision 必须是大于 0 的整数。")
        asset_ids = [asset.id for asset in self.assets]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("document.assets 的 id 不能重复。")
        paths = [asset.relative_path for asset in self.assets]
        if len(set(paths)) != len(paths):
            raise ValueError("document.assets 的 relative_path 不能重复。")
        run_ids = [run.id for run in self.runs]
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("document.runs 的 id 不能重复。")
        known = set(run_ids)
        for run in self.runs:
            if run.retry_of is not None and run.retry_of not in known:
                raise ValueError("run.retry_of 必须指向已存在的实验。")
        if len(self.application_requests) > 1000:
            raise ValueError("document.application_requests 最多保留 1000 条。")
        request_ids = [record.request_id for record in self.application_requests]
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("document.application_requests 的 request_id 不能重复。")
