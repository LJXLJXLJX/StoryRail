"""HTTP 受信凭据装配；配置不进入业务文件或请求正文。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from core.application.caller import AccessPolicy


def reject_symlink_ancestors(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("受保护路径不能包含符号链接。")
    return path


def load_access_policy(path: Path) -> AccessPolicy:
    path = reject_symlink_ancestors(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError("访问策略必须为服务用户独占的普通文件。")
        if metadata.st_size > 128 * 1024:
            raise ValueError("访问策略过大。")
        return AccessPolicy.parse(source.read(128 * 1024 + 1))
