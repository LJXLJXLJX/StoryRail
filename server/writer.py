"""受信服务启动的单实例租约；不替代 OS volume/父目录保护。"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from .access import reject_symlink_ancestors


class SingleWriterLease:
    def __init__(self, directory: Path):
        self.directory = reject_symlink_ancestors(directory)
        self._fd: int | None = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            raise RuntimeError("该作品目录已有 StoryRail 写服务，请连接现有服务。") from None
        self._fd = descriptor
        return self

    def __exit__(self, *_args):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
