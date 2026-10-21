"""服务端授予 caller/project/capability；请求正文永远不是身份来源。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_PROJECT = re.compile(r"/api/projects/([0-9a-f]{32})(/.*)?")
_ASSET = re.compile(r"/structured-director/assets/[0-9a-f]{32}/content")
_CAPABILITIES = {
    "project.read",
    "project.mutate",
    "project.propose",
    "project.execute",
    "playground.use",
    "human.write",
    "workspace.manage",
    "diagnostics.read",
}
# 外部 proposal 生命周期的命令前缀：`<kind>.request/get/submit/reject/cancel_proposal`。
PROPOSAL_KINDS = ("script", "reference", "keyframe", "location")
READ_OPERATIONS = {
    "project.get_projection",
    "project.locate_story",
    "project.get_contract",
    "project.get_workset",
    "project.get_asset_manifest",
    "project.get_handoff",
    "project.get_workflow_state",
    "project.get_request",
    "project.list_candidates",
    "project.get_dependencies",
    "run.get_status",
    *(f"{kind}.get_proposal" for kind in PROPOSAL_KINDS),
}

# 与 core.playground.commands.ALL_COMMANDS 逐项相等；为了不让 core.application 依赖
# core.playground，这里复制一份字面量，由 tests/test_playground_access.py 守卫一致性。
PLAYGROUND_AGENT_OPERATIONS = frozenset(
    {
        "playground.list_capabilities",
        "playground.list_runs",
        "playground.get_runs",
        "playground.list_assets",
        "playground.wait_runs",
        "playground.submit_run",
        "playground.cancel_run",
        "playground.retry_run",
        "playground.dismiss_run",
        "playground.set_note",
    }
)

_AGENT_OPERATIONS = {
    "video.upscale",
    "generation.wait",
    "generation.cancel",
    "generation.retry",
    "generation.dismiss",
    "keyframe.generate_batch",
    "keyframe.continue_batch",
    "visual_production.unlock",
    "animatic.generate_scene",
    "final.assemble_scene",
    "final.assemble",
    "run.cancel",
    "script.apply_operations",
    "script.request_proposal",
    "reference.request_proposal",
    "keyframe.request_proposal",
    "keyframe.apply_operations",
    "location.request_proposal",
    "location.apply_operations",
    "location.generate_image",
    "location.capture_panorama",
    "location.generate_set",
    "narration.update_cue",
    "narration.clear_selection",
    "video.save_reference_image_plan",
    "video.generate_reference_image",
    "video.set_prompt",
    "video.set_recipe",
    "video.update_recipe_inputs",
    "keyframe.generate",
    "video.generate",
    "narration.generate",
    "dialogue.generate",
    "dialogue.set_timing",
    "reference.generate_look_sheet",
    "reference.apply_look_operations",
}


class AccessDenied(Exception):
    def __init__(self, code: str, message: str, status: int = 403):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class MutationGrant:
    id: str
    project_id: str
    command_digest: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class Caller:
    id: str
    role: str
    project_ids: frozenset[str]
    capabilities: frozenset[str]
    expires_at: int
    grants: tuple[MutationGrant, ...] = ()
    mutations_enabled: bool = False


current_caller: ContextVar[Caller | None] = ContextVar("storyrail_caller", default=None)


def strict_json(body: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("重复 JSON 字段。")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("非有限 JSON 数值。")

    value = json.loads(body, object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("请求必须是 JSON 对象。")
    return value


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    # 仅保存高熵 bearer 的摘要；repr 不携带 token/摘要。
    credentials: tuple[tuple[str, Caller], ...] = field(repr=False)

    @classmethod
    def parse(cls, body: bytes) -> AccessPolicy:
        value = strict_json(body)
        if (
            set(value) != {"version", "callers", "external_mutations"}
            or type(value["version"]) is not int
            or value["version"] != 2
            or type(value["external_mutations"]) is not bool
        ):
            raise ValueError("不支持的访问策略。")
        if not isinstance(value["callers"], list):
            raise ValueError("callers 必须是列表。")
        records, ids, hashes = [], set(), set()
        for item in value["callers"]:
            fields = {
                "id",
                "role",
                "project_ids",
                "capabilities",
                "expires_at",
                "token_sha256",
                "grants",
            }
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError("caller 字段不合法。")
            caller_id, role, digest = item["id"], item["role"], item["token_sha256"]
            if not isinstance(caller_id, str) or not re.fullmatch(
                r"[a-zA-Z0-9_-]{1,80}", caller_id
            ):
                raise ValueError("caller ID 不合法。")
            if role not in ("human", "agent") or type(item["expires_at"]) is not int:
                raise ValueError("caller 类型或有效期不合法。")
            projects, capabilities = item["project_ids"], item["capabilities"]
            if not isinstance(projects, list) or any(
                not isinstance(p, str) or not re.fullmatch(r"[0-9a-f]{32}", p) for p in projects
            ):
                raise ValueError("项目范围不合法。")
            if not isinstance(capabilities, list) or any(
                not isinstance(c, str) or c not in _CAPABILITIES for c in capabilities
            ):
                raise ValueError("capability 不合法。")
            if role == "agent" and set(capabilities) - {
                "project.read",
                "project.mutate",
                "project.propose",
                "project.execute",
                "playground.use",
            }:
                raise ValueError("外部 Agent 不能获得人类 capability。")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("凭据摘要不合法。")
            if caller_id in ids or digest in hashes:
                raise ValueError("caller 或凭据摘要重复。")
            grants = []
            if not isinstance(item["grants"], list):
                raise ValueError("grants 必须是列表。")
            for grant in item["grants"]:
                if not isinstance(grant, dict) or set(grant) != {
                    "id",
                    "project_id",
                    "command_digest",
                    "expires_at",
                }:
                    raise ValueError("grant 字段不合法。")
                if not isinstance(grant["id"], str) or not re.fullmatch(
                    r"[a-zA-Z0-9_-]{1,80}", grant["id"]
                ):
                    raise ValueError("grant ID 不合法。")
                if grant["project_id"] not in projects or type(grant["expires_at"]) is not int:
                    raise ValueError("grant 范围或有效期不合法。")
                if not isinstance(grant["command_digest"], str) or not re.fullmatch(
                    r"[0-9a-f]{64}", grant["command_digest"]
                ):
                    raise ValueError("grant 摘要不合法。")
                grants.append(MutationGrant(**grant))
            if len({g.id for g in grants}) != len(grants):
                raise ValueError("grant ID 不能重复。")
            ids.add(caller_id)
            hashes.add(digest)
            records.append(
                (
                    digest,
                    Caller(
                        caller_id,
                        role,
                        frozenset(projects),
                        frozenset(capabilities),
                        item["expires_at"],
                        tuple(grants),
                        value["external_mutations"],
                    ),
                )
            )
        return cls(tuple(records))

    def authenticate(self, authorization: str | None) -> Caller:
        if authorization is None or not authorization.startswith("Bearer "):
            raise AccessDenied("unauthenticated", "请求缺少有效身份。", 401)
        token = authorization[7:]
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
            raise AccessDenied("unauthenticated", "请求缺少有效身份。", 401)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        for expected, caller in self.credentials:
            if hmac.compare_digest(expected, digest) and caller.expires_at > time.time():
                return caller
        raise AccessDenied("unauthenticated", "请求缺少有效身份。", 401)

    def authorize(self, caller: Caller, method: str, path: str, body: bytes) -> None:
        target = urlsplit(path)
        route = target.path
        if target.scheme or target.netloc or target.fragment or "%" in route or "//" in route:
            raise AccessDenied("invalid_route", "请求路径不合法。")
        if route == "/api/settings/providers" or route.startswith("/api/settings/providers/"):
            if (
                caller.role == "human"
                and "workspace.manage" in caller.capabilities
                and method in {"GET", "PUT"}
            ):
                return
            raise AccessDenied("scope_denied", "请求超出项目范围。")
        if route == "/api/playground" or route.startswith("/api/playground/"):
            if caller.role == "human":
                if "human.write" not in caller.capabilities:
                    raise AccessDenied("capability_denied", "没有 Playground 操作权限。")
                if route == "/api/playground/assets/copy-from-project" and method == "POST":
                    try:
                        request = strict_json(body)
                    except (ValueError, UnicodeError):
                        raise AccessDenied("invalid_request", "请求 JSON 不合法。", 400) from None
                    if request.get("project_id") not in caller.project_ids:
                        raise AccessDenied("scope_denied", "请求超出项目范围。")
                return
            if "playground.use" not in caller.capabilities:
                raise AccessDenied("scope_denied", "请求超出 Playground 范围。")
            if route != "/api/playground/commands" or method != "POST":
                raise AccessDenied("capability_denied", "Agent 只能调用 Playground 命令入口。")
            try:
                command = strict_json(body)
            except (ValueError, UnicodeError):
                raise AccessDenied("invalid_request", "命令 JSON 不合法。", 400) from None
            if command.get("name") not in PLAYGROUND_AGENT_OPERATIONS:
                raise AccessDenied("capability_denied", "Agent 无权执行该操作。")
            return
        if route == "/api/projects":
            if (
                caller.role == "human"
                and "workspace.manage" in caller.capabilities
                and method in {"GET", "POST"}
            ):
                return
            raise AccessDenied("scope_denied", "请求超出项目范围。")
        match = _PROJECT.fullmatch(route)
        if match is None or match[1] not in caller.project_ids:
            raise AccessDenied("scope_denied", "请求超出项目范围。")
        suffix = match[2] or ""
        if "/debug/" in suffix:
            if (
                caller.role == "human"
                and method == "GET"
                and "diagnostics.read" in caller.capabilities
            ):
                return
            raise AccessDenied("capability_denied", "没有诊断读取权限。")
        if method == "GET":
            if "project.read" in caller.capabilities and (
                caller.role == "human" or _ASSET.fullmatch(suffix)
            ):
                return
            raise AccessDenied("capability_denied", "请通过语义投影读取授权项目。")
        # 外部 Agent 的唯一 POST 读取入口；其余旧路由也在同一处拒绝。
        if method == "POST" and suffix in {
            "/structured-director/commands",
            "/structured-director/application/commands",
        }:
            try:
                command = strict_json(body)
            except (ValueError, UnicodeError):
                raise AccessDenied("invalid_request", "命令 JSON 不合法。", 400) from None
            if command.get("name") in READ_OPERATIONS and "project.read" in caller.capabilities:
                # 投影的显式 scope 仍由 Core 校验，不能跨 project。
                return
            if caller.role == "agent":
                authorize_command(caller, match[1], command)
                return
        if caller.role == "agent":
            raise AccessDenied(
                "external_mutation_disabled", "Agent 写入必须经有明确授权的 application command。"
            )
        if "human.write" not in caller.capabilities:
            raise AccessDenied("capability_denied", "没有此项目的操作权限。")
        # 人类受信身份继续走原 Service/CAS/allowed_actions；不在此复制状态机。


def request_identity(
    caller: Caller,
    project_id: str,
    key: str,
    operation: str,
    arguments: dict,
    expected_revision: int,
) -> tuple[str, str]:
    """T01 规范化输入；仅计算身份，不是假称已持久化的幂等实现。"""
    if project_id not in caller.project_ids or not key or len(key) > 200:
        raise ValueError("请求作用域或幂等键不合法。")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("revision 不合法。")
    namespace = [caller.id, project_id, key]
    semantics = [
        operation,
        arguments,
        expected_revision,
        caller.role,
        sorted(caller.project_ids),
        sorted(caller.capabilities),
        [(g.id, g.project_id, g.command_digest) for g in caller.grants],
    ]

    def digest(value):
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest()

    return digest(namespace), digest(semantics)


def command_digest(command: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {key: command[key] for key in ("name", "arguments", "expected_revision")},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def authorize_command(caller: Caller, project_id: str, command: dict) -> None:
    if project_id not in caller.project_ids or caller.expires_at <= time.time():
        raise AccessDenied("scope_denied", "请求授权已失效或超出范围。")
    if command.get("name") in READ_OPERATIONS and "project.read" in caller.capabilities:
        return
    if caller.role == "human" and "human.write" in caller.capabilities:
        return
    if not caller.mutations_enabled or "project.mutate" not in caller.capabilities:
        raise AccessDenied("external_mutation_disabled", "外部写入尚未启用。")
    if (
        command.get("name")
        in {
            f"{kind}.{action}_proposal"
            for kind in PROPOSAL_KINDS
            for action in ("submit", "reject", "cancel")
        }
        and "project.propose" in caller.capabilities
    ):
        # Core 再验证原 request 的 caller、run identity 和冷启动 scope。
        return
    if command.get("name") not in _AGENT_OPERATIONS:
        raise AccessDenied("capability_denied", "Agent 无权执行该操作。")
    # 受信部署可委托当前项目的有限 Agent 操作；正文和 Agent 自报指令不能授予此能力。
    # 人类操作已被上面的 allowlist 拒绝，Core 继续校验类型、状态、目标与 revision。
    if "project.execute" in caller.capabilities:
        return
    try:
        digest = command_digest(command)
    except (KeyError, ValueError, TypeError):
        raise AccessDenied("invalid_request", "授权命令字段不合法。", 400) from None
    if not any(
        g.project_id == project_id and g.command_digest == digest and g.expires_at > time.time()
        for g in caller.grants
    ):
        raise AccessDenied("grant_required", "缺少受信用户授予的具体动作、目标与版本授权。")
