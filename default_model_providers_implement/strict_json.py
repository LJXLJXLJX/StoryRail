from __future__ import annotations

import base64
import binascii
import math
from typing import Any

# 图片插件可选比例；与 core/model_providers/manifest.py 的 IMAGE_ASPECT_RATIOS 保持一致。
IMAGE_ASPECT_RATIOS = frozenset(
    {
        "16:9",
        "9:16",
        "2:1",
        "1:2",
        "1:1",
        "3:2",
        "2:3",
        "4:3",
        "3:4",
        "5:4",
        "4:5",
        "21:9",
        "9:21",
        "3:1",
        "1:3",
    }
)


class RequestError(ValueError):
    pass


def object_fields(
    value: Any, *, required: set[str], optional: set[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RequestError("JSON 顶层必须是对象。")
    unknown = set(value) - required - optional
    missing = required - set(value)
    if unknown:
        raise RequestError(f"包含未知字段：{sorted(unknown)}。")
    if missing:
        raise RequestError(f"缺少字段：{sorted(missing)}。")
    return value


def string(value: Any, name: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value):
        raise RequestError(f"{name} 不是合法字符串。")
    return value


def integer(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RequestError(f"{name} 不是合法整数。")
    return value


def number(value: Any, name: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(f"{name} 不是合法数字。")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise RequestError(f"{name} 超出允许范围。")
    return result


def boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise RequestError(f"{name} 必须是布尔值。")
    return value


def encoded_bytes(value: Any, name: str, *, maximum: int) -> bytes:
    text = string(value, name, maximum=(maximum * 4 // 3) + 16)
    try:
        result = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RequestError(f"{name} 不是合法 Base64。") from exc
    if not result or len(result) > maximum:
        raise RequestError(f"{name} 解码后的大小不合法。")
    return result


def require_image_magic(content: bytes, media_type: str) -> str:
    signatures = {
        "image/png": ((b"\x89PNG\r\n\x1a\n",), ".png"),
        "image/jpeg": ((b"\xff\xd8\xff",), ".jpg"),
        "image/webp": ((b"RIFF",), ".webp"),
    }
    if media_type not in signatures:
        raise RequestError("图片 media type 不受支持。")
    prefixes, suffix = signatures[media_type]
    if not any(content.startswith(prefix) for prefix in prefixes):
        raise RequestError("图片字节与声明的 media type 不一致。")
    if media_type == "image/webp" and content[8:12] != b"WEBP":
        raise RequestError("WebP 文件头不合法。")
    return suffix
