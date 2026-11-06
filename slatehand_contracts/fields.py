"""严格对象的字段集合问题：点名缺失与多余字段，并列出允许的字段；不回显字段值。"""

from __future__ import annotations

from collections.abc import Iterable

_MAX_NAMES = 12
_MAX_NAME_LENGTH = 60


def field_mismatch(
    label: str,
    value: object,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> str | None:
    """返回 ``label`` 的字段集合问题说明；字段集合合法时返回 None。"""
    if not isinstance(value, dict):
        return f"{label} 必须是 JSON 对象。"
    required = set(required)
    allowed = required | set(optional)
    keys = {str(key) for key in value}
    missing = sorted(required - keys)
    unknown = sorted(keys - allowed)
    if not missing and not unknown:
        return None
    parts = []
    if missing:
        parts.append(f"缺少字段 {_names(missing)}")
    if unknown:
        parts.append(f"不接受字段 {_names(unknown)}")
    return f"{label} {'；'.join(parts)}（允许的字段：{_names(sorted(allowed))}）。"


def require_fields(
    label: str,
    value: object,
    required: Iterable[str],
    optional: Iterable[str] = (),
    *,
    error: type[Exception] = ValueError,
) -> dict:
    """字段集合合法时原样返回对象，否则抛出带点名说明的 ``error``。"""
    problem = field_mismatch(label, value, required, optional)
    if problem is not None:
        raise error(problem)
    return value  # type: ignore[return-value]


def _names(names: list[str]) -> str:
    shown = [name[:_MAX_NAME_LENGTH] for name in names[:_MAX_NAMES]]
    more = f" 等 {len(names)} 个" if len(names) > _MAX_NAMES else ""
    return "、".join(shown) + more
