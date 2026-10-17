"""文档编解码：asset 域的 parse/serialize 函数对（纯移动，语义/JSON key/错误消息不变）。"""

from __future__ import annotations

from typing import Any

from ..models import (
    Asset,
)
from ._shared import _exact_object, _integer, _optional_number, _string

_ASSET_FIELDS = {
    "id",
    "media_type",
    "byte_count",
    "sha256",
    "relative_path",
    "duration_seconds",
}


def _serialize_asset(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "media_type": asset.media_type,
        "byte_count": asset.byte_count,
        "sha256": asset.sha256,
        "relative_path": asset.relative_path,
        "duration_seconds": asset.duration_seconds,
    }


def _parse_asset(value: object) -> Asset:
    fields = _exact_object(value, _ASSET_FIELDS)
    return Asset(
        _string(fields["id"], "asset.id"),
        _string(fields["media_type"], "asset.media_type"),
        _integer(fields["byte_count"], "asset.byte_count"),
        _string(fields["sha256"], "asset.sha256"),
        _string(fields["relative_path"], "asset.relative_path"),
        _optional_number(fields["duration_seconds"], "asset.duration_seconds"),
    )
