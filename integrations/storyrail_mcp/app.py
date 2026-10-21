"""公开受控业务工具；MCP 协议生命周期交给官方 SDK。"""

import base64
import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import Server
from mcp.types import AudioContent, CallToolResult, ImageContent, ListToolsResult, TextContent, Tool
from pydantic import Field, model_validator

from .bridge import CoreBridge
from .playground_tools import (
    PLAYGROUND_DESCRIPTIONS,
    PLAYGROUND_MODELS,
    PLAYGROUND_TOOL_NAMES,
    translate_playground,
)
from .production_tools import (
    DESCRIPTIONS,
    ID,
    MODELS,
    ProjectRead,
    ReadRequest,
    Request,
    Strict,
    translate,
)


def _consistency_instruction() -> str:
    """与 skills/consistency_instruction.md 同一份说明，不在 MCP 里另写一份。"""
    path = (
        Path(__file__).resolve().parents[2]
        / "core/director_proposals/skills/consistency_instruction.md"
    )
    return path.read_text(encoding="utf-8").strip()


class MediaRead(ReadRequest):
    asset_id: ID


class Read(ReadRequest):
    level: Literal["outline", "scene", "shot", "segment"]
    scene_ids: list[ID] = Field(
        default_factory=list,
        max_length=100,
        description="scene/shot/segment 必填的 Scene scope；outline 不接受非空值。",
    )
    ids: list[ID] = Field(
        default_factory=list,
        max_length=100,
        description="只用于可选过滤 shot/segment ID；outline/scene 不接受非空值。",
    )
    extensions: list[Literal["text", "selection", "dependencies", "video_prompt", "keyframe"]] = (
        Field(
            default_factory=list,
            description="video_prompt/keyframe 专业扩展只允许 segment level；"
            "Segment 的 selection/keyframe/video_prompt 扩展同时给出 video_inputs，"
            "含其他图片规划与绑定。",
        )
    )
    cursor: str | None = None
    parent_id: ID | None = Field(
        default=None,
        description="只用于 segment level，值必须是 scene_ids scope 内的 Scene ID。",
    )
    limit: Annotated[int, Field(ge=1, le=100)] = 20

    @model_validator(mode="after")
    def level_contract(self):
        for values, label in (
            (self.scene_ids, "scene_ids"),
            (self.ids, "ids"),
            (self.extensions, "extensions"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"read_story {label} 不能重复。")
        if self.level == "outline":
            if self.scene_ids or self.ids or self.parent_id is not None:
                raise ValueError("outline 只接受项目 scope。")
        else:
            if not self.scene_ids:
                raise ValueError("详情层级必须指定非空 scene_ids。")
            if self.level == "scene" and self.ids:
                raise ValueError("scene level 只使用 scene_ids，不接受 ids。")
            if self.level != "segment" and self.parent_id is not None:
                raise ValueError("parent_id 只接受 Segment 的 Scene 父节点。")
        if self.level != "segment" and set(self.extensions) & {"video_prompt", "keyframe"}:
            raise ValueError("专业 Prompt 扩展只接受 segment level。")
        return self


class StoryLocationRead(ReadRequest):
    location: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            description=(
                "人类可读定位：“场景 3”“场景 3－镜头 2”或“场景 3－片段 4”（片段在场景内编号）。"
            ),
        ),
    ]


Capability = Literal[
    "reference_library", "script", "location", "narration", "keyframe", "video_prompt"
]
# 只接受当前项目 scope 的专业能力（不带 scene_ids / target_ids）。
PROJECT_CAPABILITIES = frozenset({"reference_library", "script", "location"})

ProposalAction = Literal["request", "get", "submit", "reject", "cancel"]
PROPOSAL_ACTION_FIELDS = {
    "request": frozenset({"raw_user_instruction"}),
    "get": frozenset({"request_id"}),
    "submit": frozenset({"request_id", "proposal"}),
    "reject": frozenset({"request_id", "reason"}),
    "cancel": frozenset({"request_id"}),
}
PROPOSAL_VALUE_FIELDS = frozenset({"raw_user_instruction", "request_id", "proposal", "reason"})
PLANNING_VALUE_FIELDS = frozenset({"scene_ids", "target_ids"})
ProposalText = Annotated[str, Field(min_length=1, max_length=20000, pattern=r"\S")]
_MAX_PROPOSAL_SOURCE_BYTES = 1024 * 1024


class ProposalSource(Strict):
    """固定工作区文件引用；路径由 request_id 推导，不接受模型提供路径。"""

    kind: Literal["workspace_json"]
    byte_count: Annotated[int, Field(ge=2, le=_MAX_PROPOSAL_SOURCE_BYTES)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def proposal_fields(name: str, action: ProposalAction) -> set[str]:
    expected = set(PROPOSAL_ACTION_FIELDS[action])
    if action == "request" and name == "keyframe_proposal":
        expected |= {"scene_ids", "target_ids"}
    return expected


def supplied_proposal_fields(request: "Proposal") -> set[str]:
    """Treat connector-inflated inactive nulls as omitted, never as action values."""
    candidates = request.model_fields_set & (PROPOSAL_VALUE_FIELDS | PLANNING_VALUE_FIELDS)
    return {field for field in candidates if getattr(request, field) is not None}


class ContractRead(ReadRequest):
    capability: Capability
    if_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="上次读取返回的契约 content hash；未变化时只返回 unchanged。",
    )
    include: list[Literal["consistency-review"]] = Field(
        default_factory=list,
        max_length=1,
        description="显式附带共享 consistency-review 资源；默认为空。",
    )
    cursor: str | None = Field(
        default=None,
        description="超过 Agent 响应预算时返回的 query/content-bound 续读游标。",
    )
    page_bytes: Annotated[int, Field(ge=4096, le=24576)] = 24576


class SubmitProposal(Request):
    """统一 proposal 入口；payload 按 action 提供字段，运行时按对应 Proposal 模型严格校验。"""

    capability: Literal["script", "reference_library", "location", "keyframe"]
    payload: dict[str, object]


class WorksetRead(ReadRequest):
    capability: Capability
    if_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="上次读取返回的 workset content hash；未变化时只返回 unchanged。",
    )
    cursor: str | None = Field(
        default=None,
        description="超过 Agent 响应预算时返回的 query/content-bound 续读游标。",
    )
    page_bytes: Annotated[int, Field(ge=4096, le=24576)] = 24576
    scene_ids: list[ID] = Field(default_factory=list, max_length=100)
    target_ids: list[ID] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def capability_contract(self):
        if len(self.scene_ids) != len(set(self.scene_ids)) or (
            self.target_ids is not None and len(self.target_ids) != len(set(self.target_ids))
        ):
            raise ValueError("workset scope/target_ids 不能重复。")
        if self.capability in PROJECT_CAPABILITIES:
            if self.scene_ids or self.target_ids is not None:
                raise ValueError("项目级专业能力不接受 scene_ids 或 target_ids。")
        elif not self.scene_ids:
            raise ValueError("旁白、Keyframe 和 H3 工作集必须指定 scene_ids。")
        if self.capability == "video_prompt" and (
            self.target_ids is None or len(self.target_ids) != 1
        ):
            raise ValueError("H3 工作集必须指定一个 Segment。")
        return self


class Proposal(Request):
    action: ProposalAction
    raw_user_instruction: ProposalText | None = None
    request_id: ID | None = None
    proposal: dict[str, object] | None = None
    reason: ProposalText | None = None

    @model_validator(mode="after")
    def exact_action_fields(self):
        expected = PROPOSAL_ACTION_FIELDS[self.action]
        supplied = supplied_proposal_fields(self) & PROPOSAL_VALUE_FIELDS
        if supplied != expected:
            raise ValueError("proposal 参数必须与 action 严格匹配。")
        return self


class PlanningProposal(Proposal):
    scene_ids: list[ID] | None = Field(default=None, min_length=1, max_length=100)
    target_ids: list[ID] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="规划的 Segment ID；可读取所属完整 Scene 作上下文，只合并目标 Segment。",
    )

    @model_validator(mode="after")
    def exact_action_fields(self):
        super().exact_action_fields()
        if self.action == "request":
            supplied = supplied_proposal_fields(self) & PLANNING_VALUE_FIELDS
            if supplied != frozenset({"scene_ids", "target_ids"}):
                raise ValueError("规划请求必须有 Scene scope 与对应规划选项。")
        elif supplied_proposal_fields(self) & PLANNING_VALUE_FIELDS:
            raise ValueError("后续动作只使用原始 request_id，不接受替换 scope。")
        return self


class VideoBinding(Strict):
    asset_id: ID
    description: Annotated[str, Field(max_length=2000)] | None


class VideoRecipeInputs(Strict):
    """当前 recipe 的完整输入簿：与工作集 recipe_inputs 同形，整体替换。"""

    bindings: dict[str, list[VideoBinding]]
    params: dict[str, object]


class VideoPrompt(Request):
    scene_ids: list[ID] = Field(min_length=1, max_length=100)
    segment_id: ID
    prompt_text: Annotated[str, Field(max_length=20000)]
    recipe_inputs: VideoRecipeInputs | None = None


class KeyframePrompt(Request):
    keyframe_id: ID
    prompt_text: Annotated[str, Field(max_length=10000)]


def _non_null_property(value: dict[str, object]) -> dict[str, object]:
    """Reuse the Pydantic field schema while removing its optional null branch."""
    result = copy.deepcopy(value)
    alternatives = result.pop("anyOf", None)
    if isinstance(alternatives, list):
        alternatives = [item for item in alternatives if item.get("type") != "null"]
        if len(alternatives) == 1:
            title = result.get("title")
            result = {**alternatives[0], **({"title": title} if title else {})}
        else:
            result["anyOf"] = alternatives
    result.pop("default", None)
    return result


def tool_schema(name, model):
    schema = model.model_json_schema()
    if issubclass(model, Proposal):
        fields = set(model.model_fields) - set(Request.model_fields) - {"action"}
        schema["oneOf"] = []
        for action in ("request", "get", "submit", "reject", "cancel"):
            expected = proposal_fields(name, action)
            schema["oneOf"].append(
                {
                    "properties": {
                        "action": {"const": action},
                        **{
                            key: _non_null_property(schema["properties"][key])
                            for key in sorted(expected)
                        },
                        # Some native connectors materialize optional fields as
                        # null.  Inactive action fields may therefore be null,
                        # but never carry a value or reach Core translation.
                        **{key: {"type": "null"} for key in sorted(fields - expected)},
                    },
                    "required": ["action", *sorted(expected)],
                }
            )
    elif name == "submit_proposal":
        schema["oneOf"] = _submit_proposal_branches()
    elif name == "save_video_prompt":
        # 形状随 video_prompt 工作集的 recipe_inputs 下发；运行时模型仍严格校验。
        schema.pop("$defs")
        schema["properties"]["recipe_inputs"] = {"type": "object"}
    elif name == "read_story":
        schema["oneOf"] = _read_story_branches(schema)
    elif name == "read_professional_workset":
        schema["oneOf"] = _workset_branches(schema)
    elif name == "manage_generation":
        many = _array_property(schema, "generation_ids", minimum=1, maximum=100)
        one = _array_property(schema, "generation_ids", minimum=1, maximum=1)
        schema["oneOf"] = [
            {"properties": {"action": {"const": "wait"}, "generation_ids": many}},
            {
                "properties": {
                    "action": {"enum": ["cancel", "retry", "dismiss"]},
                    "generation_ids": one,
                },
                "required": ["expected_revision", "idempotency_key"],
            },
        ]
    elif name == "media_batch":
        schema["oneOf"] = [
            {
                "properties": {
                    "action": {"const": "start"},
                    "target_ids": _array_property(schema, "target_ids", minimum=1, maximum=100),
                    "run_id": {"type": "null"},
                },
                "required": ["target_ids"],
            },
            {
                "properties": {
                    "action": {"const": "continue"},
                    "target_ids": {"type": "null"},
                    "run_id": _non_null_property(schema["properties"]["run_id"]),
                },
                "required": ["run_id"],
            },
        ]
    elif name == "assemble_media":
        schema["oneOf"] = [
            {
                "properties": {
                    "kind": {"enum": ["animatic", "scene"]},
                    "scene_id": _non_null_property(schema["properties"]["scene_id"]),
                },
                "required": ["scene_id"],
            },
            {"properties": {"kind": {"const": "final"}, "scene_id": {"type": "null"}}},
        ]
    return schema


def _submit_proposal_branches() -> list[dict[str, object]]:
    """按 capability × action 公开 payload 的完整字段，不引用未发布的旧工具。

    keyframe 的 request 必须带 scene_ids、target_ids；项目级 capability 不接受这两项。
    """
    schema = PlanningProposal.model_json_schema()
    source_schema = ProposalSource.model_json_schema()

    def payload(name: str) -> dict[str, object]:
        branches = []
        for action in ("request", "get", "submit", "reject", "cancel"):
            expected = sorted(proposal_fields(name, action))
            variants = [(expected, None)]
            if action == "submit":
                variants.append((["request_id", "proposal_source"], source_schema))
            for fields, proposal_source_schema in variants:
                properties: dict[str, object] = {"action": {"const": action}}
                for key in fields:
                    if key == "proposal_source":
                        properties[key] = proposal_source_schema
                        continue
                    value = _non_null_property(schema["properties"][key])
                    if key in PLANNING_VALUE_FIELDS:
                        value["uniqueItems"] = True
                    properties[key] = value
                if action == "submit":
                    inactive = "proposal_source" if proposal_source_schema is None else "proposal"
                    properties[inactive] = {"type": "null"}
                branches.append(
                    {
                        "additionalProperties": False,
                        "properties": properties,
                        "required": ["action", *fields],
                    }
                )
        return {"type": "object", "oneOf": branches}

    return [
        {
            "properties": {
                "capability": {"enum": sorted(PROJECT_CAPABILITIES)},
                "payload": payload("script_proposal"),
            }
        },
        {
            "properties": {
                "capability": {"const": "keyframe"},
                "payload": payload("keyframe_proposal"),
            }
        },
    ]


def _array_property(schema, name, *, minimum=None, maximum=None):
    value = _non_null_property(schema["properties"][name])
    value["uniqueItems"] = True
    if minimum is not None:
        value["minItems"] = minimum
    if maximum is not None:
        value["maxItems"] = maximum
    return value


def _extensions_property(schema, *, professional):
    value = _array_property(schema, "extensions")
    if not professional:
        value["items"]["enum"] = ["text", "selection", "dependencies"]
    return value


def _read_story_branches(schema):
    empty_scene_ids = _array_property(schema, "scene_ids", maximum=0)
    scoped_scene_ids = _array_property(schema, "scene_ids", minimum=1, maximum=100)
    empty_ids = _array_property(schema, "ids", maximum=0)
    optional_ids = _array_property(schema, "ids", maximum=100)
    base_extensions = _extensions_property(schema, professional=False)
    segment_extensions = _extensions_property(schema, professional=True)
    return [
        {
            "properties": {
                "level": {"const": "outline"},
                "scene_ids": empty_scene_ids,
                "ids": empty_ids,
                "parent_id": {"type": "null"},
                "extensions": base_extensions,
            }
        },
        {
            "properties": {
                "level": {"const": "scene"},
                "scene_ids": scoped_scene_ids,
                "ids": empty_ids,
                "parent_id": {"type": "null"},
                "extensions": base_extensions,
            },
            "required": ["scene_ids"],
        },
        {
            "properties": {
                "level": {"const": "shot"},
                "scene_ids": scoped_scene_ids,
                "ids": optional_ids,
                "parent_id": {"type": "null"},
                "extensions": base_extensions,
            },
            "required": ["scene_ids"],
        },
        {
            "properties": {
                "level": {"const": "segment"},
                "scene_ids": scoped_scene_ids,
                "ids": optional_ids,
                "extensions": segment_extensions,
            },
            "required": ["scene_ids"],
        },
    ]


def _workset_branches(schema):
    empty_scene_ids = _array_property(schema, "scene_ids", maximum=0)
    scoped_scene_ids = _array_property(schema, "scene_ids", minimum=1, maximum=100)
    target_ids = _array_property(schema, "target_ids", minimum=1, maximum=100)
    return [
        {
            "properties": {
                "capability": {"enum": sorted(PROJECT_CAPABILITIES)},
                "scene_ids": empty_scene_ids,
                "target_ids": {"type": "null"},
            }
        },
        {
            "properties": {
                "capability": {"enum": ["narration", "keyframe"]},
                "scene_ids": scoped_scene_ids,
                "target_ids": target_ids,
            },
            "required": ["scene_ids"],
        },
        {
            "properties": {
                "capability": {"const": "video_prompt"},
                "scene_ids": scoped_scene_ids,
                "target_ids": _array_property(schema, "target_ids", minimum=1, maximum=1),
            },
            "required": ["scene_ids", "target_ids"],
        },
    ]


def _response_text_blocks(result: dict[str, object]) -> list[TextContent]:
    """text 始终携带完整 JSON：只读 text 的客户端（如 AGY）不能退化成读不到数据。"""
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


def _arguments_error(message: str) -> tuple[int, dict[str, object]]:
    """把 MCP 侧严格 schema 拒绝翻译成与工具调用一致的错误信封。"""
    return (
        400,
        {
            "error": {
                "code": "invalid_arguments",
                "message": message,
                "recoverable": True,
                "origin": "mcp_schema",
                "state_changed": False,
                "retry_policy": "fix_arguments_and_retry",
                "automatic_retry_allowed": False,
            }
        },
    )


_COMPACT_OPERATION_TOOLS = frozenset(
    {"edit_script", "edit_keyframes", "edit_locations", "edit_looks"}
)
_PROPOSAL_CAPABILITY_TO_TOOL = {
    "script": "script_proposal",
    "reference_library": "reference_proposal",
    "location": "location_proposal",
    "keyframe": "keyframe_proposal",
}
_PROPOSAL_TOOL_PREFIX = {
    "script_proposal": "script",
    "reference_proposal": "reference",
    "location_proposal": "location",
}


def _prune_schema(value: object, *, property_names: bool = False) -> object:
    """去掉注解关键字；`properties` 下的键是字段名，即使叫 description 也必须保留。"""
    if isinstance(value, dict):
        return {
            key: _prune_schema(item, property_names=key == "properties" and not property_names)
            for key, item in value.items()
            if property_names or key not in {"title", "description", "default"}
        }
    if isinstance(value, list):
        return [_prune_schema(item) for item in value]
    return value


def _compact_operation_schema(schema: dict[str, object]) -> dict[str, object]:
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        return schema
    operations: dict[str, object] = {}
    for name, definition in definitions.items():
        if not isinstance(definition, dict):
            continue
        properties = definition.get("properties")
        if not isinstance(properties, dict) or "op" not in properties:
            continue
        op = properties.get("op")
        if not isinstance(op, dict) or "const" not in op:
            continue
        # const 已精确限定字符串取值，type 冗余。
        operation_properties: dict[str, object] = {"op": {"const": op["const"]}}
        for field, field_schema in properties.items():
            if field != "op":
                operation_properties[field] = field_schema
        operations[name] = {
            "type": "object",
            "additionalProperties": False,
            "properties": operation_properties,
            "required": definition.get("required", ["op"]),
        }
    if not operations:
        return schema
    compact = dict(schema)
    compact["$defs"] = {**definitions, **operations}
    return compact


def published_tool_schema(name: str, model: object) -> dict[str, object]:
    schema = tool_schema(name, model)
    if name in _COMPACT_OPERATION_TOOLS:
        schema = _compact_operation_schema(schema)
    return _prune_schema(schema)


def published_models() -> dict[str, object]:
    models = {
        key: value
        for key, value in MODELS.items()
        if key not in {"read_human_handoff", "read_workflow_state"}
    }
    models.update(
        {
            "read_media_input": MediaRead,
            "read_story": Read,
            "locate_story": StoryLocationRead,
            "read_professional_contract": ContractRead,
            "read_professional_workset": WorksetRead,
            "read_workflow": ProjectRead,
            "submit_proposal": SubmitProposal,
            "save_video_prompt": VideoPrompt,
            "save_keyframe_prompt": KeyframePrompt,
        }
    )
    return models


def project_models() -> dict[str, object]:
    """项目 scope 全部可调用工具的请求模型（含不发布 schema 的 proposal/读工具）。"""
    return {
        **MODELS,
        "read_media_input": MediaRead,
        "read_story": Read,
        "locate_story": StoryLocationRead,
        "read_professional_contract": ContractRead,
        "read_professional_workset": WorksetRead,
        "read_workflow": ProjectRead,
        "submit_proposal": SubmitProposal,
        "script_proposal": Proposal,
        "reference_proposal": Proposal,
        "location_proposal": Proposal,
        "keyframe_proposal": PlanningProposal,
        "save_video_prompt": VideoPrompt,
        "save_keyframe_prompt": KeyframePrompt,
    }


def _load_proposal_source(
    proposal_directory: Path | None,
    request_id: object,
    value: object,
) -> dict[str, object]:
    """读取 request_id 对应的固定 JSON；不接受任意路径且不回显内容。"""
    if proposal_directory is None:
        raise ValueError("当前 MCP 未配置 proposal 工作区。")
    if (
        not isinstance(request_id, str)
        or len(request_id) != 32
        or any(character not in "0123456789abcdef" for character in request_id)
    ):
        raise ValueError("proposal request_id 不合法。")
    try:
        source = ProposalSource.model_validate(value)
    except ValueError as exc:
        raise ValueError("proposal_source 不符合严格契约。") from exc
    try:
        directory_stat = proposal_directory.lstat()
        if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_ISLNK(directory_stat.st_mode):
            raise ValueError("proposal 工作区不可用。")
        path = proposal_directory / f"{request_id}.json"
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size != source.byte_count:
                raise ValueError("proposal 文件大小不一致。")
            content = bytearray()
            while len(content) <= _MAX_PROPOSAL_SOURCE_BYTES:
                remaining = _MAX_PROPOSAL_SOURCE_BYTES + 1 - len(content)
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                content.extend(chunk)
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise ValueError("proposal 工作区文件不可用或已变化。") from exc
    encoded = bytes(content)
    if len(encoded) != source.byte_count or hashlib.sha256(encoded).hexdigest() != source.sha256:
        raise ValueError("proposal 文件校验不一致。")

    def reject_non_finite(_value: str) -> None:
        raise ValueError("proposal JSON 不能包含非有限数字。")

    try:
        proposal = json.loads(encoded.decode("utf-8"), parse_constant=reject_non_finite)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("proposal 文件不是合法 UTF-8 JSON。") from exc
    if not isinstance(proposal, dict):
        raise ValueError("proposal 文件根必须是 object。")
    return proposal


def _resolve_submit_payload(
    payload: dict[str, object], proposal_directory: Path | None
) -> dict[str, object]:
    if payload.get("proposal_source") is None and "proposal_source" in payload:
        payload = {key: value for key, value in payload.items() if key != "proposal_source"}
    if payload.get("action") != "submit" or payload.get("proposal_source") is None:
        return payload
    supplied = {key for key, value in payload.items() if value is not None}
    if supplied != {"action", "request_id", "proposal_source"}:
        raise ValueError("submit 必须且只能提供 proposal 或 proposal_source。")
    return {
        "action": "submit",
        "request_id": payload.get("request_id"),
        "proposal": _load_proposal_source(
            proposal_directory,
            payload.get("request_id"),
            payload.get("proposal_source"),
        ),
    }


def create_server(bridge: CoreBridge, *, proposal_directory: Path | None = None):
    models = project_models()
    listed_models = published_models()
    descriptions = {
        **DESCRIPTIONS,
        "read_workflow": "读取 workflow、handoff 与 contract_hashes；不授予人类权限。",
        "submit_proposal": (
            "proposal 生命周期，payload 按 action 分支；"
            "submit 可内联 proposal，或引用固定工作区 proposals/<request_id>.json；"
            "keyframe 的 request 另需 scene_ids、target_ids。"
        ),
        "read_media_input": (
            "读取当前项目实际图片/音频Asset，校验SHA-256，最多8 MiB；不接受路径。"
            "返回的图片直接用原生视觉能力查看，不要再用 ffmpeg 等命令行工具处理；"
            "当前模型无视觉能力时直接拒绝看图任务。"
        ),
        "keyframe_proposal": (
            "Scene/Segment scope 的 Keyframe 规划生命周期；request 后由当前 Agent 编写并 submit。"
        ),
        "location_proposal": (
            "从完整脚本规划地点库与 Scene/Shot 绑定；request 后由当前 Agent 编写并 submit。"
        ),
        "read_professional_contract": (
            "按固定能力读取完整 Skill 与参考；支持 if_hash 内容协商，不接受文件路径。"
        ),
        "read_professional_workset": (
            "读取当前 revision 的专业事实与输出 schema；支持 if_hash 内容协商，不创建 run。"
        ),
        "read_story": (
            "按 level 的公开 oneOf 契约读取故事；outline 使用项目 scope，"
            "scene/shot/segment 必须给 scene_ids；Shot 与 Segment 都直接属于 Scene，"
            "shot 层给出覆盖它的 segment_ids，segment 层给出 shot_ids；"
            "video_prompt/keyframe 扩展只用于 segment；selection、keyframe 或 video_prompt 扩展"
            "同时返回 video_inputs：其他图片规划 ID、slot_index、正文、选图状态及显式媒体绑定。"
        ),
        "locate_story": (
            "按“场景 N”“场景 N－镜头 N”或“场景 N－片段 N”（片段在场景内编号）"
            "解析当前脚本的稳定 ID；只读，不修改项目。"
        ),
        "script_proposal": (
            "请求后由当前 Agent 编写并提交首次脚本草稿；支持读取/拒绝/取消，不替代人类审核。"
        ),
        "reference_proposal": (
            "请求后由当前 Agent 编写并提交首次引用库；Core分配ID，人类审核后才能显式开始脚本。"
        ),
        "save_video_prompt": "保存单Segment正文与可选recipe_inputs；不生成或选择。",
        "save_keyframe_prompt": "只更新单个Keyframe正文，Core失效相关选择；不生成。",
    }

    async def list_tools(_context, _params):
        return ListToolsResult(
            tools=[
                Tool(
                    name=name,
                    description=descriptions[name],
                    input_schema=published_tool_schema(name, model),
                )
                for name, model in listed_models.items()
            ]
        )

    async def call_tool(_context, params):
        dispatch_name = params.name
        try:
            if params.name not in models:
                raise ValueError("未开放该工具。")
            dispatch_name = params.name
            request = models[params.name].model_validate(params.arguments or {})
            if isinstance(request, SubmitProposal):
                dispatch_name = _PROPOSAL_CAPABILITY_TO_TOOL[request.capability]
                payload = _resolve_submit_payload(request.payload, proposal_directory)
                request = models[dispatch_name].model_validate(
                    {
                        "project_id": request.project_id,
                        "expected_revision": request.expected_revision,
                        "idempotency_key": request.idempotency_key,
                        **payload,
                    }
                )
            if isinstance(request, Proposal):
                supplied = supplied_proposal_fields(request)
                if supplied != proposal_fields(dispatch_name, request.action):
                    raise ValueError("proposal 参数必须与工具 action 严格匹配。")
            if isinstance(request, MediaRead):
                status, value, content = await bridge.read_media(
                    request.project_id,
                    request.asset_id,
                    request.expected_revision,
                    request.idempotency_key,
                )
                result = {"http_status": status, **value}
                blocks = _response_text_blocks(result)
                if status == 200 and content is not None:
                    media = (
                        ImageContent if value["media_type"].startswith("image/") else AudioContent
                    )
                    blocks.append(
                        media(
                            type="image" if media is ImageContent else "audio",
                            data=base64.b64encode(content).decode("ascii"),
                            mime_type=value["media_type"],
                        )
                    )
                return CallToolResult(
                    content=blocks,
                    structured_content=result,
                    is_error=status != 200,
                )
            if isinstance(request, StoryLocationRead):
                name = "project.locate_story"
                arguments = {"location": request.location}
            elif isinstance(request, ProjectRead) and dispatch_name == "read_workflow":
                name = "project.get_workflow_state"
                arguments = request.model_dump(
                    exclude={"project_id", "expected_revision", "idempotency_key"},
                    exclude_none=True,
                )
            elif dispatch_name in MODELS:
                name, arguments = translate(dispatch_name, request)
            elif isinstance(request, WorksetRead):
                project_scope = request.capability in PROJECT_CAPABILITIES
                if project_scope and request.scene_ids:
                    raise ValueError("此能力只接受项目 scope。")
                name = "project.get_workset"
                arguments = {
                    "capability": request.capability,
                    "scope": {"project_id": request.project_id}
                    if project_scope
                    else {"scene_ids": request.scene_ids},
                    "page_bytes": request.page_bytes,
                }
                if request.target_ids is not None:
                    arguments["target_ids"] = request.target_ids
                if request.if_hash is not None:
                    arguments["if_hash"] = request.if_hash
                if request.cursor is not None:
                    arguments["cursor"] = request.cursor
            elif isinstance(request, ContractRead):
                name = "project.get_contract"
                arguments = {
                    "capability": request.capability,
                    "page_bytes": request.page_bytes,
                }
                if request.if_hash is not None:
                    arguments["if_hash"] = request.if_hash
                if request.include:
                    arguments["include"] = request.include
                if request.cursor is not None:
                    arguments["cursor"] = request.cursor
            elif isinstance(request, Read):
                if request.level == "outline" and (
                    request.scene_ids or request.ids or request.parent_id
                ):
                    raise ValueError("outline 只接受项目 scope。")
                name = "project.get_projection"
                arguments = {
                    "level": request.level,
                    "scope": {"project_id": request.project_id}
                    if request.level == "outline"
                    else {"scene_ids": request.scene_ids},
                    "extensions": request.extensions,
                    "limit": request.limit,
                }
                if request.parent_id is not None:
                    arguments["parent_id"] = request.parent_id
                if request.ids:
                    arguments["ids"] = request.ids
                if request.cursor is not None:
                    arguments["cursor"] = request.cursor
            elif isinstance(request, PlanningProposal):
                name = f"keyframe.{request.action}_proposal"
                arguments = request.model_dump(
                    exclude={
                        "project_id",
                        "expected_revision",
                        "idempotency_key",
                        "action",
                        "scene_ids",
                    },
                    exclude_none=True,
                )
                if request.action == "request":
                    arguments["scope"] = {"scene_ids": request.scene_ids}
            elif isinstance(request, Proposal):
                name = f"{_PROPOSAL_TOOL_PREFIX[dispatch_name]}.{request.action}_proposal"
                arguments = request.model_dump(
                    exclude={"project_id", "expected_revision", "idempotency_key", "action"},
                    exclude_none=True,
                )
            elif isinstance(request, KeyframePrompt):
                name = "keyframe.apply_operations"
                arguments = {
                    "operations": [
                        {
                            "op": "update_frame_fields",
                            "keyframe_id": request.keyframe_id,
                            "fields": {"prompt_text": request.prompt_text},
                        }
                    ]
                }
            else:
                name = "video.set_prompt"
                arguments = {
                    "scope": {"scene_ids": request.scene_ids},
                    "segment_id": request.segment_id,
                    "prompt_text": request.prompt_text,
                }
                if request.recipe_inputs is not None:
                    name = "video.update_recipe_inputs"
                    arguments.update(request.recipe_inputs.model_dump())
            status, value = await bridge.call(
                request.project_id,
                name,
                request.expected_revision,
                request.idempotency_key,
                arguments,
            )
        except ValueError:
            # 不回显任意工具参数或本机异常路径。
            message = "参数不符合此工具的严格契约。请读取 tools/list 中的完整 schema。"
            if params.name == "submit_proposal":
                message = (
                    "submit_proposal 的 capability 必须是 script、reference_library、"
                    "location 或 keyframe；payload 除 action 外只能提供："
                    "request→raw_user_instruction（keyframe 另需 scene_ids、target_ids），"
                    "get/cancel→request_id，submit→request_id 加 proposal 或 proposal_source，"
                    "reject→request_id、reason。"
                )
            elif dispatch_name in models and issubclass(models[dispatch_name], Proposal):
                action = (params.arguments or {}).get("action")
                if isinstance(action, str) and action in {
                    "request",
                    "get",
                    "submit",
                    "reject",
                    "cancel",
                }:
                    fields = "、".join(sorted(proposal_fields(dispatch_name, action)))
                    message = f"{action} 除通用字段外必须且仅能提供：{fields}。"
            status, value = _arguments_error(message)
        result = {"http_status": status, **value}
        return CallToolResult(
            content=_response_text_blocks(result),
            structured_content=result,
            is_error=status != 200,
        )

    return Server(
        "StoryRail",
        version="0.1.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        instructions=(
            "有限语义工具连接同一 Core；断连后保留原参数/revision/key 重试。"
            "遇到 HTTP 401、unauthenticated 或凭据过期时，不要让用户去 UI 寻找刷新按钮；"
            "当前没有 UI 内的刷新凭据功能。应让用户停止当前 Agent 启动终端，"
            "重新执行同一项目的启动命令；"
            "只重启 Core、gateway 或 MCP 不会刷新项目连接。写请求保留原参数、revision 和幂等键，"
            "不自动重提。"
            "查看项目图片时用 read_media_input 读取，直接以原生多模态视觉能力判读；"
            "不要调用 ffmpeg、ImageMagick、Python/PIL 等命令行工具抽取、转码或分析图片；"
            "读取被拒绝时如实报告原因，不自行绕道。"
            "当前模型没有多模态视觉能力时，直接拒绝需要看图的任务并建议用户切换多模态模型；"
            "不要用命令行工具、文件名、元数据或提示词推测画面来冒充看图。"
            "proposal request 只建立不可变工作集，随后由当前外部 Agent 编写并显式 submit；"
            "没有后台模型任务可轮询。"
            "大型 proposal 写入 /workspace/proposals/<request_id>.json 后，"
            "用 proposal_source 的 byte_count 与 sha256 提交，不要内联或传任意路径；"
            "工作区文件只是不受信传输缓冲，Core 仍完整校验并原子落库。"
            "取消 proposal 使用显式 cancel；传输取消不表示业务回滚。"
            "读取专业契约前先调用 read_workflow 获取 contract_hashes[capability]，"
            "再带 if_hash 调用 read_professional_contract；"
            "返回 unchanged 时复用本地已读 resources。"
            "契约读取与 consistency-review 的规则以 core/director_proposals/skills/README.md "
            "为单一事实源；默认契约不含 consistency-review，需要时显式 "
            'include=["consistency-review"]。' + _consistency_instruction()
        ),
    )


def _playground_runs_branches(schema):
    """playground_runs 按 action 的严格 oneOf；get/wait 不接受列表分页字段。"""
    return [
        {
            "properties": {
                "action": {"const": "list"},
                "run_ids": {"type": "null"},
            }
        },
        {
            "properties": {
                "action": {"const": "get"},
                "limit": {"type": "null"},
                "cursor": {"type": "null"},
                "capability": {"type": "null"},
                "include_dismissed": {"type": "null"},
                "run_ids": _array_property(schema, "run_ids", minimum=1, maximum=20),
            },
            "required": ["run_ids"],
        },
        {
            "properties": {
                "action": {"const": "wait"},
                "limit": {"type": "null"},
                "cursor": {"type": "null"},
                "capability": {"type": "null"},
                "include_dismissed": {"type": "null"},
                "run_ids": _array_property(schema, "run_ids", minimum=1, maximum=8),
            },
            "required": ["run_ids"],
        },
    ]


def playground_tool_schema(name: str, model: object) -> dict[str, object]:
    schema = model.model_json_schema()
    if name == "playground_runs":
        schema["oneOf"] = _playground_runs_branches(schema)
    return _prune_schema(schema)


def create_playground_server(bridge: CoreBridge):
    """Playground scope 只发布 5 个工具，全部翻译成 playground.* 命令。"""
    models = dict(PLAYGROUND_MODELS)

    async def list_tools(_context, _params):
        return ListToolsResult(
            tools=[
                Tool(
                    name=name,
                    description=PLAYGROUND_DESCRIPTIONS[name],
                    input_schema=playground_tool_schema(name, models[name]),
                )
                for name in PLAYGROUND_TOOL_NAMES
            ]
        )

    async def call_tool(_context, params):
        try:
            if params.name not in models:
                raise ValueError("未开放该工具。")
            request = models[params.name].model_validate(params.arguments or {})
            name, key, arguments = translate_playground(params.name, request)
            status, value = await bridge.call_playground(name, key, arguments)
        except ValueError:
            status, value = _arguments_error(
                "参数不符合此工具的严格契约。请读取 tools/list 中的完整 schema。"
            )
        result = {"http_status": status, **value}
        return CallToolResult(
            content=_response_text_blocks(result),
            structured_content=result,
            is_error=status != 200,
        )

    return Server(
        "StoryRail",
        version="0.1.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        instructions=(
            "当前是 StoryRail Playground scope：不涉及任何项目，也不能跨域复制 Asset。"
            "先用 playground_capabilities 读取能力与参数 schema，再调用 playground_submit；"
            "视频类任务耗时长，提交后用 playground_runs 的 wait 有界等待。"
            "写工具由模型提供 idempotency_key，同一请求重放才复用原 key。"
            "遇到 HTTP 401 或凭据过期时，让用户从 Playground 页面重新复制启动命令。"
        ),
    )
