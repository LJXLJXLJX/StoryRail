"""离线原生 Codex TUI：真实 PNG、跨 exec 传输、连续粘贴；不提交用户任务。"""

import fcntl
import json
import os
import random
import select
import struct
import subprocess
import termios
import time
import uuid
import zlib

import pytest

from integrations.agent_launcher.clipboard import transfer_image

pytestmark = pytest.mark.skipif(
    os.environ.get("STORYRAIL_DOCKER_TESTS") != "1", reason="显式原生 Docker 粘贴验收"
)
IMAGE = "storyrail-external-agents:latest-v1"


def png_image(size):
    def chunk(kind, value):
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
        )

    pixels = random.Random(42).randbytes(size * size * 3)
    stride = size * 3
    rows = b"".join(b"\0" + pixels[i : i + stride] for i in range(0, len(pixels), stride))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_native_codex_attaches_consecutive_small_large_images():
    name = "storyrail-clipboard-test-" + uuid.uuid4().hex[:8]
    setup = """import os,subprocess,time
from pathlib import Path
root=Path('/tmp/codex');root.mkdir()
(root/'config.toml').write_text('check_for_update_on_startup = false\\n'
 '[projects."/workspace"]\\ntrust_level = "trusted"\\n')
os.environ['CODEX_HOME']=str(root)
subprocess.run(['codex','login','--with-api-key'],input=b'synthetic-unused-test-key',check=True)
subprocess.Popen(['Xvfb',':99','-screen','0','1x1x24','-nolisten','tcp'])
time.sleep(120)
"""
    process = None
    master = slave = None

    def docker(*args):
        return subprocess.run(["docker", *args], capture_output=True, check=True, timeout=15)

    try:
        docker(
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user",
            "10002:10002",
            "--tmpfs",
            "/tmp:rw,mode=1777",
            "--tmpfs",
            "/workspace:rw,uid=10002,gid=10002",
            IMAGE,
            "python",
            "-c",
            setup,
        )
        docker(
            "exec",
            name,
            "python",
            "-c",
            (
                "from pathlib import Path;import time\nfor _ in range(100):\n"
                " if Path('/tmp/.X11-unix/X99').exists():break\n time.sleep(.02)\n"
                "else:raise RuntimeError('X11 not ready')"
            ),
        )
        master, slave = os.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
        process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-it",
                "--env",
                "DISPLAY=:99",
                "--env",
                "CODEX_HOME=/tmp/codex",
                "--env",
                "TERM=xterm-256color",
                name,
                "codex",
                "--no-alt-screen",
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
        )
        os.close(slave)
        slave = None

        def read_until(marker):
            output = b""
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    data = os.read(master, 65536)
                    output += data
                    if b"\x1b[6n" in data:
                        os.write(master, b"\x1b[1;1R")
                    assert b"Failed to paste image" not in output, output[-2000:]
                    if marker in output:
                        return output
                assert process.poll() is None, "原生终端提前退出"
            pytest.fail(f"等待 {marker!r} 超时：{output[-2000:]!r}")

        read_until(b"gpt-")
        for index, size in enumerate((512, 2048, 32, 2048), start=1):
            png = png_image(size)
            transfer_image(name, png)
            os.write(master, b"\x16")
            read_until(f"[Image #{index}]".encode())
            dimensions = docker(
                "exec",
                name,
                "python",
                "-c",
                "from pathlib import Path;import struct,json;"
                "print(json.dumps(sorted(struct.unpack('>II',p.read_bytes()[16:24]) "
                "for p in Path('/tmp').glob('codex-clipboard-*.png'))))",
            )
            assert json.loads(dimensions.stdout) == sorted(
                [[value, value] for value in (512, 2048, 32, 2048)[:index]]
            )

        # 没有 Enter/任务请求，也无网络；只验证原生附件槽位。
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
        for fd in (master, slave):
            if fd is not None:
                os.close(fd)
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
