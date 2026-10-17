"""HTTP 边缘共享判定：媒体上传路径与查询字段纪律。"""

from __future__ import annotations

from urllib.parse import urlsplit

MEDIA_UPLOAD_SUFFIXES = ("/assets/images", "/assets/media", "/voice-reference/upload")


def is_media_upload_path(path: str) -> bool:
    return urlsplit(path).path.endswith(MEDIA_UPLOAD_SUFFIXES)


def query_is_allowed(path: str, query: str) -> bool:
    return not query or is_media_upload_path(path)
