"""把 MCP 侧参数校验失败翻译成可定位的问题列表；不回显参数值、正文或异常堆栈。"""

from __future__ import annotations

from pydantic import ValidationError

_ID_PATTERN = "^[0-9a-f]{32}$"
_MAX_ISSUES = 20
_TYPE_NAMES = {
    "string_type": "字符串",
    "int_type": "整数",
    "int_parsing": "整数",
    "float_type": "数字",
    "bool_type": "布尔值",
    "list_type": "数组",
    "tuple_type": "数组",
    "dict_type": "对象",
    "model_type": "对象",
    "model_attributes_type": "对象",
    "none_required": "null",
}


def validation_issues(exc: ValidationError, arguments: object) -> list[dict[str, object]]:
    """Pydantic 错误 → ``[{path, reason, message, expected?}]``，按出现顺序去重，至多 20 项。"""
    issues: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for error in exc.errors(include_url=False, include_input=False):
        path = _json_path(error["loc"], arguments, missing=error["type"] == "missing")
        issue = _issue(error, path)
        identity = (issue["path"], issue["reason"])
        if identity in seen:
            continue
        seen.add(identity)
        issues.append(issue)
        if len(issues) >= _MAX_ISSUES:
            break
    return issues


def rule_issue(message: str) -> dict[str, object]:
    """自定义校验规则（不对应单个字段）的原因原样透出。"""
    return {"path": "", "reason": "invalid_combination", "message": message[:300]}


def summary(issues: list[dict[str, object]]) -> str:
    if not issues:
        return "参数不符合此工具的严格契约。"
    first = issues[0]
    location = f"{first['path']}：" if first["path"] and first["reason"] != "missing" else ""
    more = f"（另有 {len(issues) - 1} 处问题见 issues）" if len(issues) > 1 else ""
    return f"参数错误：{location}{first['message']}{more}"


def _json_path(loc: tuple, arguments: object, *, missing: bool) -> str:
    """沿实际参数走 loc。

    不在实际参数里的字符串是 Pydantic 的联合分支标签（如 ``insert_shot``），跳过。
    """
    parts: list[str] = []
    current = arguments
    for index, item in enumerate(loc):
        if isinstance(item, int):
            parts.append(f"[{item}]")
            current = current[item] if isinstance(current, list) and item < len(current) else None
        elif isinstance(current, dict) and item in current:
            parts.append(f".{item}" if parts else item)
            current = current[item]
        elif missing and index == len(loc) - 1:
            parts.append(f".{item}" if parts else item)
    return "".join(parts)


def _issue(error: dict, path: str) -> dict[str, object]:
    kind = error["type"]
    ctx = error.get("ctx") or {}
    name = path.rsplit(".", 1)[-1] if path else ""
    if kind == "missing":
        return {"path": path, "reason": "missing", "message": f"缺少必填字段 {path or name}。"}
    if kind == "extra_forbidden":
        return {"path": path, "reason": "unknown_field", "message": f"不接受字段 {name}。"}
    if kind in _TYPE_NAMES:
        expected = _TYPE_NAMES[kind]
        return {
            "path": path,
            "reason": "wrong_type",
            "message": f"应为{expected}。",
            "expected": expected,
        }
    if kind == "string_pattern_mismatch":
        pattern = str(ctx.get("pattern", ""))
        if pattern == _ID_PATTERN:
            return {
                "path": path,
                "reason": "invalid_id",
                "message": "应为 32 位小写十六进制 ID。",
                "expected": pattern,
            }
        return {"path": path, "reason": "pattern", "message": "格式不符。", "expected": pattern}
    if kind in {"string_too_short", "too_short"}:
        limit = ctx.get("min_length")
        unit = "字符" if kind.startswith("string") else "项"
        return {
            "path": path,
            "reason": "too_short",
            "message": f"至少 {limit} {unit}。",
            "expected": {"min": limit},
        }
    if kind in {"string_too_long", "too_long"}:
        limit = ctx.get("max_length")
        unit = "字符" if kind.startswith("string") else "项"
        return {
            "path": path,
            "reason": "too_long",
            "message": f"至多 {limit} {unit}。",
            "expected": {"max": limit},
        }
    bounds = {
        "greater_than_equal": ("ge", "≥"),
        "greater_than": ("gt", ">"),
        "less_than_equal": ("le", "≤"),
        "less_than": ("lt", "<"),
    }
    if kind in bounds:
        key, symbol = bounds[kind]
        limit = ctx.get(key)
        return {
            "path": path,
            "reason": "out_of_range",
            "message": f"应 {symbol} {limit}。",
            "expected": {key: limit},
        }
    if kind in {"literal_error", "enum"}:
        expected = str(ctx.get("expected", ""))
        return {
            "path": path,
            "reason": "invalid_value",
            "message": f"取值应为 {expected}。",
            "expected": expected,
        }
    if kind == "union_tag_invalid":
        expected = str(ctx.get("expected_tags", ""))
        field = ctx.get("discriminator", "op").strip("'")
        return {
            "path": f"{path}.{field}" if path else field,
            "reason": "invalid_value",
            "message": f"{field} 取值应为 {expected}。",
            "expected": expected,
        }
    if kind == "union_tag_not_found":
        field = str(ctx.get("discriminator", "op")).strip("'")
        return {
            "path": f"{path}.{field}" if path else field,
            "reason": "missing",
            "message": f"缺少必填字段 {field}。",
        }
    if kind == "value_error":
        message = str(ctx.get("error") or error.get("msg", "")).removeprefix("Value error, ")
        return {"path": path, "reason": "invalid_combination", "message": message[:300]}
    return {"path": path, "reason": kind, "message": str(error.get("msg", ""))[:200]}
