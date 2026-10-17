"""JSON Schema → TypeScript 类型与结构校验。"""

from __future__ import annotations

import json
from typing import Any

from core.web_contracts.proposal_schema import proposal_schemas
from core.web_contracts.snapshot_schema import TYPE_ALIASES, snapshot_schemas

_HEADER = "// 勿手改，由 scripts/gen_web_contracts.py 生成。\n"
_RUNTIME_KEYS = {
    "$ref",
    "type",
    "enum",
    "const",
    "anyOf",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "x-trimmed-nonempty",
    "x-datetime",
    "x-finite",
}


def render() -> tuple[str, str]:
    catalog = {**snapshot_schemas(), **proposal_schemas()}
    types = _render_types(catalog)
    validation = _render_validation(catalog)
    return types, validation


def _render_types(catalog: dict[str, dict]) -> str:
    parts = [_HEADER]
    for schema in catalog.values():
        alias = schema.get("x-ts-alias")
        if not alias:
            continue
        if "enum" in schema:
            values = ", ".join(_literal(item) for item in schema["enum"])
            parts.append(f"export const {alias} = [{values}] as const;")
            parts.append(f"export type {alias} = (typeof {alias})[number];")
        elif "anyOf" in schema:
            union = " | ".join(_ts_type(item, catalog) for item in schema["anyOf"])
            parts.append(f"export type {alias} = {union};")
        else:
            parts.append(f"export type {alias} = {_ts_type(schema, catalog)};")
    parts.append("")
    for name, schema in _interfaces(catalog):
        parts.append(_interface(name, schema, catalog))
        parts.append("")
    for alias, target in TYPE_ALIASES:
        parts.append(f"export type {alias} = {target};")
    parts.append("")
    return "\n".join(parts)


def _interfaces(catalog: dict[str, dict]) -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    seen: set[str] = set()

    def walk(schema: Any) -> None:
        if not isinstance(schema, dict) or "$ref" in schema:
            return
        name = schema.get("x-ts-name")
        if name and name not in seen and (schema.get("type") == "object" or "anyOf" in schema):
            seen.add(name)
            found.append((name, schema))
        for value in schema.values():
            if isinstance(value, dict):
                walk(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        walk(item)

    for schema in catalog.values():
        walk(schema)
    return found


def _interface(name: str, schema: dict, catalog: dict[str, dict]) -> str:
    properties, required, index = _object_view(schema)
    lines = [f"export interface {name} {{"]
    for key, prop in properties.items():
        optional = "?" if _optional(key, prop, required) else ""
        lines.append(f"  {key}{optional}: {_ts_type(prop, catalog)};")
    if index:
        lines.append("  [key: string]: unknown;")
    lines.append("}")
    return "\n".join(lines)


def _object_view(schema: dict) -> tuple[dict, set[str], bool]:
    if schema.get("type") == "object":
        return (
            schema.get("properties", {}),
            set(schema.get("required") or []),
            schema.get("additionalProperties") is True,
        )
    properties: dict = {}
    required: set[str] | None = None
    index = False
    for branch in schema.get("anyOf", []):
        if branch.get("type") != "object":
            continue
        properties.update(branch.get("properties", {}))
        branch_required = set(branch.get("required") or [])
        required = branch_required if required is None else required & branch_required
        index = index or branch.get("additionalProperties") is True
    return properties, required or set(), index


def _optional(key: str, prop: dict, required: set[str]) -> bool:
    if prop.get("x-ts-optional"):
        return True
    return key not in required


def _ts_type(schema: dict, catalog: dict[str, dict]) -> str:
    if schema.get("x-ts-type"):
        return schema["x-ts-type"]
    if "$ref" in schema:
        target = catalog[schema["$ref"]]
        if target.get("x-ts-alias"):
            return target["x-ts-alias"]
        if target.get("x-ts-name"):
            return target["x-ts-name"]
        return _ts_type(target, catalog)
    if schema.get("x-ts-name") and (schema.get("type") == "object" or "anyOf" in schema):
        return schema["x-ts-name"]
    if "const" in schema:
        return _literal(schema["const"])
    if "enum" in schema:
        return " | ".join(_literal(item) for item in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(dict.fromkeys(_ts_type(item, catalog) for item in schema["anyOf"]))
    kind = schema.get("type")
    if kind == "string":
        return "string"
    if kind in {"integer", "number"}:
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    if kind == "array":
        if schema.get("prefixItems"):
            inner = ", ".join(_ts_type(item, catalog) for item in schema["prefixItems"])
            return f"[{inner}]"
        item = schema.get("items")
        item_type = _ts_type(item, catalog) if isinstance(item, dict) else "unknown"
        if "|" in item_type or item_type.startswith("{"):
            return f"({item_type})[]"
        return f"{item_type}[]"
    if kind == "object":
        properties = schema.get("properties") or {}
        extra = schema.get("additionalProperties")
        if not properties and isinstance(extra, dict):
            return f"Record<string, {_ts_type(extra, catalog)}>"
        if not properties and extra is True:
            return "Record<string, unknown>"
        return _inline_object(schema, catalog)
    return "unknown"


def _inline_object(schema: dict, catalog: dict[str, dict]) -> str:
    required = set(schema.get("required") or [])
    fields = []
    for key, prop in schema.get("properties", {}).items():
        optional = "?" if _optional(key, prop, required) else ""
        fields.append(f"{key}{optional}: {_ts_type(prop, catalog)}")
    body = "; ".join(fields)
    if schema.get("additionalProperties") is True and schema.get("properties"):
        body = f"{body}; [key: string]: unknown" if body else "[key: string]: unknown"
    return "{ " + body + " }"


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_validation(catalog: dict[str, dict]) -> str:
    runtime = {
        name: _runtime_schema(schema)
        for name, schema in catalog.items()
        if not schema.get("x-ts-only")
    }
    schema_json = json.dumps(runtime, ensure_ascii=False, indent=2)
    type_names = sorted(
        {schema["x-ts-name"] for schema in catalog.values() if schema.get("x-ts-name")}
        | {schema["x-ts-alias"] for schema in catalog.values() if schema.get("x-ts-alias")}
        | {alias for alias, _target in TYPE_ALIASES}
    )
    imported = ",\n  ".join(type_names)
    guards = "\n".join(
        _guard(name, schema) for name, schema in catalog.items() if schema.get("x-guard")
    )
    proposals = "\n".join(
        _proposal_parser(name) for name, schema in catalog.items() if schema.get("x-proposal")
    )
    return (
        f"{_HEADER}// @ts-nocheck\n"
        "import {\n"
        "  checkSchema,\n"
        "  hasExactKeys,\n"
        "  isId,\n"
        "  isRecord,\n"
        "  type JsonSchema,\n"
        '} from "./schema_check";\n'
        "import {\n"
        "  refineActiveDirectorRun,\n"
        "  refineAsset,\n"
        "  refineDirectorScript,\n"
        "  refineFinalAssembly,\n"
        "  refineGeneration,\n"
        "  refineScene,\n"
        "  refineWorkflow,\n"
        "  refineWorkspaceLayers,\n"
        "  editableScenePayload,\n"
        "  snapshotConsistencyError,\n"
        '} from "./refine";\n'
        f'import type {{\n  {imported},\n}} from "./types";\n\n'
        "export {\n"
        "  hasExactKeys,\n"
        "  isId,\n"
        "  isIdArray,\n"
        "  isNonEmptyString,\n"
        "  isNonNegativeInteger,\n"
        "  isNullableNonNegativeInteger,\n"
        "  isPositiveInteger,\n"
        "  isRecord,\n"
        "  isStringFields,\n"
        "  isThreadId,\n"
        "  isVideoSeed,\n"
        '} from "./schema_check";\n'
        'export { editableScenePayload } from "./refine";\n\n'
        f"const schemas: Record<string, JsonSchema> = {schema_json};\n\n"
        f"{guards}\n\n"
        f"{_PARSERS}\n\n"
        f"{proposals}\n"
    )


def _guard(name: str, schema: dict) -> str:
    function = schema["x-guard"]
    type_name = schema.get("x-guard-type") or schema.get("x-ts-name") or schema.get("x-ts-alias")
    refine = schema.get("x-refine")
    refine_call = f" && {refine}(value)" if refine else ""
    return (
        f"export function {function}(value: unknown): value is {type_name} {{\n"
        f"  return checkSchema(schemas.{name}, value, schemas){refine_call};\n"
        "}"
    )


def _proposal_parser(name: str) -> str:
    return (
        f"export function parse{name}(value: unknown): {name} {{\n"
        f"  if (!checkSchema(schemas.{name}, value, schemas)) {{\n"
        f'    throw new Error("proposal 不符合 {name}。");\n'
        "  }\n"
        f"  return value as {name};\n"
        "}"
    )


def _runtime_schema(value: Any) -> Any:
    """只保留校验器认识的关键字；properties 的键是字段名，不能按关键字过滤。"""
    if not isinstance(value, dict):
        return value
    kept = {key: value[key] for key in value if key in _RUNTIME_KEYS}
    if isinstance(value.get("properties"), dict):
        kept["properties"] = {
            name: _runtime_schema(prop) for name, prop in value["properties"].items()
        }
    if isinstance(kept.get("additionalProperties"), dict):
        kept["additionalProperties"] = _runtime_schema(kept["additionalProperties"])
    if isinstance(kept.get("items"), dict):
        kept["items"] = _runtime_schema(kept["items"])
    if isinstance(kept.get("anyOf"), list):
        kept["anyOf"] = [_runtime_schema(item) for item in kept["anyOf"]]
    if isinstance(kept.get("prefixItems"), list):
        kept["prefixItems"] = [_runtime_schema(item) for item in kept["prefixItems"]]
    return kept


_PARSERS = r"""export function parseProjectList(value: unknown): ProjectSummary[] {
  return parseProjectBootstrap(value).projects;
}
export function parseProjectBootstrap(value: unknown): ProjectBootstrap {
  if (!isRecord(value) || !Array.isArray(value.projects) || !hasExactKeys(value, ["projects"])) {
    throw new Error("服务端返回了无法识别的项目列表。");
  }
  return { projects: value.projects.map(parseProject) };
}
export function parseProject(value: unknown): ProjectSummary {
  if (!isProjectSummary(value)) throw new Error("服务端返回的项目摘要不合法。");
  return value;
}
export function parseProviderSettings(value: unknown): ProviderSettingsView {
  if (!isProviderSettingsView(value)) throw new Error("服务端返回了无法识别的 Provider 设置。");
  return value;
}
export function parseProjectDetail(value: unknown): ProjectDetail {
  return parseDetail(value, "服务端返回了无法识别的项目状态。");
}
export function parseStructuredDirectorDetail(value: unknown): StructuredDirectorDetail {
  return parseDetail(value, "服务端返回了无法识别的结构化导演台状态。");
}
function parseDetail(value: unknown, message: string): ProjectDetail {
  if (!isRecord(value) || !hasExactKeys(value, ["project", "structured_director"])) {
    throw new Error(message);
  }
  return {
    project: parseProject(value.project),
    structured_director: parseStructuredDirectorSnapshot(value.structured_director),
  };
}
export function parseDeleteResult(value: unknown): string {
  if (!isRecord(value) || !hasExactKeys(value, ["deleted_project_id"]) ||
    !isId(value.deleted_project_id)) {
    throw new Error("服务端返回的删除结果不合法。");
  }
  return value.deleted_project_id;
}
export function parseAudioTranscription(value: unknown): string {
  if (!isRecord(value) || !hasExactKeys(value, ["transcript"]) ||
    typeof value.transcript !== "string" || value.transcript.trim().length === 0) {
    throw new Error("音频转写结果格式不合法。");
  }
  return value.transcript;
}
export function parseError(value: unknown): ApiErrorPayload {
  if (!isRecord(value) || !hasExactKeys(value, ["error"]) || !isRecord(value.error)) {
    throw new Error("服务端返回了无法识别的错误。");
  }
  if (!checkSchema(schemas.ApiErrorBody, value.error, schemas)) {
    throw new Error("服务端错误格式不合法。");
  }
  return value as unknown as ApiErrorPayload;
}
export function parseImageSubmissionPreview(
  value: unknown,
): ImageSubmissionPreview {
  if (!isImageSubmissionPreview(value)) {
    throw new Error("最终完整提示词预览格式不合法。");
  }
  return value;
}
export function parseStructuredDirectorSnapshot(value: unknown): StructuredDirectorSnapshot {
  const required = schemas.StructuredDirectorSnapshot.required ?? [];
  if (!isRecord(value) || !hasExactKeys(value, required)) {
    throw new Error("服务端返回了无法识别的结构化导演台状态。");
  }
  const snapshot = value;
  if (!isProductionAvailability(snapshot.production_availability)) {
    throw new Error("制作能力状态不合法。");
  }
  if (!checkSchema(schemas.StructuredDirectorStatus, snapshot.status, schemas)) {
    throw new Error("引用库准备状态不合法。");
  }
  if (snapshot.active_director_run !== null && !isActiveDirectorRun(snapshot.active_director_run)) {
    throw new Error("Director run 状态不合法。");
  }
  if (!checkSchema(snapshotProperty("revision"), snapshot.revision, schemas)) {
    throw new Error("结构化导演台 revision 不合法。");
  }
  if (!checkSchema(schemas.ProjectAspectRatio, snapshot.aspect_ratio, schemas)) {
    throw new Error("结构化导演台画面比例不合法。");
  }
  if (!checkSchema(
    snapshotProperty("director_plan_markdown"),
    snapshot.director_plan_markdown,
    schemas,
  )) {
    throw new Error("结构化导演台导演方案不合法。");
  }
  if (!isWorkspaceLayers(snapshot.workspace_layers)) {
    throw new Error("结构化导演台解锁状态不合法。");
  }
  if (!checkSchema(snapshotProperty("allowed_actions"), snapshot.allowed_actions, schemas)) {
    throw new Error("结构化导演台允许动作不合法。");
  }
  const library = snapshot.reference_library;
  if (!isReferenceLibraryView(library)) {
    throw new Error("引用库格式不合法。");
  }
  if (!Array.isArray(library.characters) || !library.characters.every(isCharacterCard) ||
    (library.narrator !== null && !isNarratorProfile(library.narrator))) {
    throw new Error("引用库卡片格式不合法。");
  }
  if (!isProviderAvailability(snapshot.provider_availability)) {
    throw new Error("模型服务可用性格式不合法。");
  }
  const assets = snapshot.assets;
  if (!Array.isArray(assets) || !assets.every(isProjectAsset)) {
    throw new Error("Asset 清单格式不合法。");
  }
  const generations = snapshot.generations;
  if (!Array.isArray(generations) || !generations.every(isReferenceGeneration)) {
    throw new Error("Generation 清单格式不合法。");
  }
  if (snapshot.director_script !== null && !isDirectorScript(snapshot.director_script)) {
    throw new Error("结构化导演脚本格式不合法。");
  }
  if (!isLocationLibrary(snapshot.location_library)) {
    throw new Error("地点库格式不合法。");
  }
  if (snapshot.keyframe_plan !== null && !isKeyframePlan(snapshot.keyframe_plan)) {
    throw new Error("Segment Keyframe 计划格式不合法。");
  }
  if (snapshot.video_plan !== null && !isVideoPlan(snapshot.video_plan)) {
    throw new Error("Segment 视频计划格式不合法。");
  }
  if (snapshot.final_assembly !== null && !isFinalAssemblyPlan(snapshot.final_assembly)) {
    throw new Error("最终成片装配计划格式不合法。");
  }
  if (snapshot.final_approval !== null && !isFinalApproval(snapshot.final_approval)) {
    throw new Error("最终 Approval 格式不合法。");
  }
  const capabilityGapAlerts = snapshot.capability_gap_alerts;
  if (!Array.isArray(capabilityGapAlerts) || !capabilityGapAlerts.every(isCapabilityGapAlert)) {
    throw new Error("能力缺口报警格式不合法。");
  }
  snapshot.workflow = parseWorkflowState(snapshot.workflow);
  const parsed = snapshot as unknown as StructuredDirectorSnapshot;
  const consistency = snapshotConsistencyError(parsed);
  if (consistency) throw new Error(consistency);
  return parsed;
}
function snapshotProperty(name: string): JsonSchema {
  const property = schemas.StructuredDirectorSnapshot.properties?.[name];
  if (!property) throw new Error("契约缺少字段。");
  return property;
}
function isReferenceLibraryView(value: unknown): value is ReferenceLibraryView {
  if (!isRecord(value)) return false;
  const withReviewed = ["characters", "narrator", "reviewed"];
  const withoutReviewed = ["characters", "narrator"];
  if (!(hasExactKeys(value, withReviewed) || hasExactKeys(value, withoutReviewed))) return false;
  if ("reviewed" in value && typeof value.reviewed !== "boolean") return false;
  return true;
}
function parseWorkflowState(value: unknown): WorkflowState {
  if (!isWorkflowEnvelope(value) || !refineWorkflow(value)) {
    throw new Error("主流程状态不合法。");
  }
  const workflow = value as WorkflowState;
  for (const action of workflow.required_next_actions) {
    if (!isWorkflowAction(action)) throw new Error("主流程动作不合法。");
  }
  return workflow;
}"""
