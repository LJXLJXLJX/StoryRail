"""容器内图片输入：校验临时图片，再发布原生剪贴板支持的类型。"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_IMAGE_BYTES = 16 * 1024 * 1024


def publish_image(content: bytes, agent: str) -> dict:
    if agent not in {"codex", "pi", "agy", "kimi", "dsh", "grok"}:
        raise ValueError("不支持的 Agent。")
    if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("剪贴板需要不超过 16 MiB 的 PNG。")
    environment = {**os.environ, "DISPLAY": ":99"}
    path = None
    try:
        if agent == "codex":
            # Codex 原生优先读取图片文件列表；X11 只传小 URI，不传大图像素。
            with tempfile.NamedTemporaryFile(
                prefix="storyrail-clipboard-", suffix=".png", dir="/tmp", delete=False
            ) as target:
                target.write(content)
                path = Path(target.name)
            payload = path.as_uri().encode()  # 原生 arboard 3.6.1 不移除 CR。
            media_type = "text/uri-list"
        else:
            payload, media_type = content, "image/png"
        command = ["xclip", "-selection", "clipboard", "-t", media_type]
        subprocess.run(
            [*command, "-i"],
            input=payload,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            timeout=5,
            check=True,
        )
        readback = subprocess.run(
            [*command, "-o"],
            capture_output=True,
            env=environment,
            timeout=5,
            check=True,
        ).stdout
        if readback != payload:
            raise ValueError("容器剪贴板回读不一致。")
        if path is not None and path.read_bytes() != content:
            raise ValueError("容器图片回读不一致。")
        return {"byte_count": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    except BaseException:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def main():
    content = sys.stdin.buffer.read(MAX_IMAGE_BYTES + 1)
    result = publish_image(content, sys.argv[1])
    print(json.dumps(result))


if __name__ == "__main__":
    main()
