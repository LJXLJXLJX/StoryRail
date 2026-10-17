"""可读资产文件名的规范化；没有状态，也不读写文件。"""

from __future__ import annotations

import re
import unicodedata

_ASSET_NAME_FORBIDDEN = re.compile(r"[<>:\"/\\|?*\x00-\x1f]+")


_ASSET_NAME_SPACES = re.compile(r"\s+")
_ASSET_NAME_MAX_CHARACTERS = 120
_ASSET_NAME_MAX_BYTES = 200
_ASSET_NAME_ELLIPSIS = "…"


def uploaded_asset_label(filename: str | None, fallback: str) -> str:
    if filename is None:
        return fallback
    basename = re.split(r"[/\\]", filename)[-1]
    stem = basename.rsplit(".", 1)[0].strip()
    return stem or fallback


def asset_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = _ASSET_NAME_FORBIDDEN.sub("-", normalized)
    normalized = _ASSET_NAME_SPACES.sub("-", normalized)
    normalized = normalized.strip(". -")
    if not normalized:
        normalized = "未命名资产"
    if len(normalized) <= _ASSET_NAME_MAX_CHARACTERS and (
        len(normalized.encode("utf-8")) <= _ASSET_NAME_MAX_BYTES
    ):
        return normalized
    # APFS 单个文件名上限 255 UTF-8 字节；为哈希、后缀和历史归档后缀预留空间。
    budget = _ASSET_NAME_MAX_BYTES - len(_ASSET_NAME_ELLIPSIS.encode("utf-8"))
    truncated = normalized[: _ASSET_NAME_MAX_CHARACTERS - 1]
    while len(truncated.encode("utf-8")) > budget:
        truncated = truncated[:-1]
    return truncated.rstrip(". -") + _ASSET_NAME_ELLIPSIS
