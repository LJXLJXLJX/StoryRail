"""Playground scope 的 5 个 MCP 工具：只翻译成 playground.* 命令，不导入 Core。"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
IdempotencyKey = Annotated[str, Field(min_length=1, max_length=200)]
READ_KEY_PREFIX = "mcp-read:"


class PlaygroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlaygroundCapabilitiesRead(PlaygroundRequest):
    """playground_capabilities：无参数。"""


class PlaygroundSubmit(PlaygroundRequest):
    """playground_submit：capability 不在 MCP 侧枚举，交给 Core 校验。"""

    capability: Annotated[str, Field(min_length=1, max_length=120)]
    parameters: dict
    note: str | None = None
    idempotency_key: IdempotencyKey


class PlaygroundRuns(PlaygroundRequest):
    """playground_runs：按 action 严格分支，不接受混合字段。"""

    action: Literal["list", "get", "wait"]
    limit: Annotated[int, Field(ge=1, le=100)] = 30
    cursor: str | None = None
    capability: str | None = None
    include_dismissed: bool = False
    run_ids: Annotated[list[ID], Field(max_length=20)] | None = None

    @model_validator(mode="after")
    def exact_action_fields(self):
        supplied = self.model_fields_set - {"action"}
        if self.action == "list":
            if "run_ids" in supplied:
                raise ValueError("list 不接受 run_ids。")
            return self
        if supplied & {"limit", "cursor", "capability", "include_dismissed"}:
            raise ValueError("get/wait 只接受 run_ids。")
        if not self.run_ids:
            raise ValueError("get/wait 必须提供 run_ids。")
        if len(self.run_ids) != len(set(self.run_ids)):
            raise ValueError("run_ids 不能重复。")
        upper = 20 if self.action == "get" else 8
        if len(self.run_ids) > upper:
            raise ValueError(f"{self.action} 最多接受 {upper} 个 run_id。")
        return self


class PlaygroundManageRun(PlaygroundRequest):
    """playground_manage_run：note 只在 set_note 时允许并且必填。"""

    action: Literal["cancel", "retry", "dismiss", "set_note"]
    run_id: ID
    note: str | None = None
    idempotency_key: IdempotencyKey

    @model_validator(mode="after")
    def note_only_for_set_note(self):
        if self.action == "set_note":
            if "note" not in self.model_fields_set:
                raise ValueError("set_note 必须提供 note。")
        elif "note" in self.model_fields_set:
            raise ValueError("note 只用于 set_note。")
        return self


class PlaygroundAssets(PlaygroundRequest):
    """playground_assets：只返回元数据，不提供媒体字节。"""

    limit: Annotated[int, Field(ge=1, le=100)] = 30
    cursor: str | None = None
    media_kind: Literal["image", "audio", "video"] | None = None


PLAYGROUND_MODELS = {
    "playground_capabilities": PlaygroundCapabilitiesRead,
    "playground_submit": PlaygroundSubmit,
    "playground_runs": PlaygroundRuns,
    "playground_manage_run": PlaygroundManageRun,
    "playground_assets": PlaygroundAssets,
}
PLAYGROUND_TOOL_NAMES = tuple(PLAYGROUND_MODELS)

PLAYGROUND_DESCRIPTIONS = {
    "playground_capabilities": (
        "读取 Playground 实验能力与参数 schema；不涉及任何项目，提交前先读这份 schema。"
    ),
    "playground_submit": (
        "提交一次 Playground 实验 run；不涉及任何项目，视频类任务耗时长，提交后用 "
        "playground_runs 的 wait 有界等待。"
    ),
    "playground_runs": (
        "列出、读取或有界等待 Playground run；不涉及任何项目，视频类任务耗时长要用 wait。"
    ),
    "playground_manage_run": "取消、重试、隐藏 Playground run 或设置备注；不涉及任何项目。",
    "playground_assets": "只读列出 Playground 资产元数据，不返回媒体字节；不涉及任何项目。",
}


def generate_read_key() -> str:
    """读工具的内部幂等键；不暴露给模型，也不代表业务写入。"""
    return READ_KEY_PREFIX + str(uuid.uuid4())


def translate_playground(name: str, request: PlaygroundRequest):
    """把单个 MCP 工具调用翻译成 (命令名, 幂等键, arguments)。"""
    if name == "playground_submit":
        assert isinstance(request, PlaygroundSubmit)
        return (
            "playground.submit_run",
            request.idempotency_key,
            {
                "capability": request.capability,
                "parameters": request.parameters,
                "note": request.note,
            },
        )
    if name == "playground_manage_run":
        assert isinstance(request, PlaygroundManageRun)
        if request.action == "set_note":
            return (
                "playground.set_note",
                request.idempotency_key,
                {"run_id": request.run_id, "note": request.note},
            )
        return (
            f"playground.{request.action}_run",
            request.idempotency_key,
            {"run_id": request.run_id},
        )
    key = generate_read_key()
    if name == "playground_runs":
        assert isinstance(request, PlaygroundRuns)
        if request.action == "list":
            return (
                "playground.list_runs",
                key,
                {
                    "limit": request.limit,
                    "cursor": request.cursor,
                    "capability": request.capability,
                    "include_dismissed": request.include_dismissed,
                },
            )
        return (
            "playground.get_runs" if request.action == "get" else "playground.wait_runs",
            key,
            {"run_ids": list(request.run_ids or ())},
        )
    if name == "playground_assets":
        assert isinstance(request, PlaygroundAssets)
        return (
            "playground.list_assets",
            key,
            {
                "limit": request.limit,
                "cursor": request.cursor,
                "media_kind": request.media_kind,
            },
        )
    assert isinstance(request, PlaygroundCapabilitiesRead)
    return "playground.list_capabilities", key, {}


__all__ = [
    "PLAYGROUND_DESCRIPTIONS",
    "PLAYGROUND_MODELS",
    "PLAYGROUND_TOOL_NAMES",
    "PlaygroundAssets",
    "PlaygroundCapabilitiesRead",
    "PlaygroundManageRun",
    "PlaygroundRequest",
    "PlaygroundRuns",
    "PlaygroundSubmit",
    "generate_read_key",
    "translate_playground",
]
