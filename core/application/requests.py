"""持久请求值对象与提交上下文；不持有文件或执行 Provider。"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from dataclasses import asdict, dataclass

from .caller import strict_json


@dataclass(frozen=True, slots=True)
class ApplicationRequest:
    request_id: str
    caller_id: str
    project_id: str
    idempotency_key: str
    request_digest: str
    operation: str
    expected_revision: int
    authorization_scope: str
    phase: str = "pending"
    result_revision: int | None = None
    receipt_json: str | None = None
    generation_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (self.request_id, self.request_digest):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("application request 摘要不合法。")
        for value, maximum in (
            (self.caller_id, 80),
            (self.idempotency_key, 200),
            (self.operation, 100),
            (self.authorization_scope, 200000),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError("application request 字段不合法。")
        if not isinstance(self.project_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", self.project_id
        ):
            raise ValueError("application request project 不合法。")
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise ValueError("application request revision 不合法。")
        if self.phase not in {"pending", "uncertain", "committed"}:
            raise ValueError("application request phase 不合法。")
        if self.result_revision is not None and (
            type(self.result_revision) is not int or self.result_revision < self.expected_revision
        ):
            raise ValueError("application request result revision 不合法。")
        if (self.receipt_json is None) != (self.result_revision is None):
            raise ValueError("application request 回执与 revision 必须同时存在。")
        if self.phase == "committed" and self.receipt_json is None:
            raise ValueError("committed request 必须有回执。")
        if self.receipt_json is not None:
            if not isinstance(self.receipt_json, str) or len(self.receipt_json) > 200000:
                raise ValueError("application request 回执不合法。")
            strict_json(self.receipt_json.encode())
        if (
            not isinstance(self.generation_ids, tuple)
            or any(
                not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{32}", item)
                for item in self.generation_ids
            )
            or len(set(self.generation_ids)) != len(self.generation_ids)
        ):
            raise ValueError("application request Generation 关联不合法。")

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("application request 含未知或缺少字段。")
        if not isinstance(value["generation_ids"], list):
            raise ValueError("application request generation_ids 必须是列表。")
        return cls(**{**value, "generation_ids": tuple(value["generation_ids"])})

    def to_dict(self):
        return {**asdict(self), "generation_ids": list(self.generation_ids)}


current_request: ContextVar[ApplicationRequest | None] = ContextVar(
    "application_request", default=None
)


def canonical(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
