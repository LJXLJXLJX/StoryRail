"""宿主终端按键桥：仅在用户粘贴时传递一张图片，不开放宿主剪贴板服务。"""

import hashlib
import json
import os
import select
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.error
import urllib.parse
import urllib.request
import webbrowser


def read_macos_image():
    result = subprocess.run(
        ["osascript", "-e", "get the clipboard as «class PNGf»"],
        capture_output=True,
        timeout=10,
    )
    if result.returncode:
        return None
    value = result.stdout.decode().strip()
    prefix = "«data PNGf"
    if not value.startswith(prefix) or not value.endswith("»"):
        return None
    encoded = value[len(prefix) : -1]
    if len(encoded) > 32 * 1024 * 1024:
        raise ValueError("剪贴板图片超过 16 MiB，请缩小后重试。")
    content = bytes.fromhex(encoded)
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("剪贴板图片不是有效 PNG。")
    return content


def transfer_image(container, content, *, agent="codex"):
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python", "/app/clipboard_input.py", agent],
        input=content,
        capture_output=True,
        timeout=15,
        check=True,
    )
    expected = {"byte_count": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    if json.loads(result.stdout) != expected:
        raise ValueError("图片传输回执不匹配，未触发粘贴。")


def _open_when_ready(url, process, container):
    for _ in range(240):
        if process.poll() is not None:
            return
        token = subprocess.run(
            ["docker", "exec", container, "cat", "/tmp/dsh-browser-token"],
            capture_output=True,
        )
        if token.returncode == 0 and token.stdout.strip():
            value = urllib.parse.quote(token.stdout.decode().strip(), safe="")
            webbrowser.open(url.rstrip("/") + "/?token=" + value)
            return
        time.sleep(0.25)


def run_interactive(command, *, env, container, agent="codex", ready_url=None):
    if sys.platform != "darwin" or not sys.stdin.isatty():
        if ready_url is None:
            return subprocess.run(command, env=env).returncode
        process = subprocess.Popen(command, env=env)
        if ready_url is not None:
            threading.Thread(
                target=_open_when_ready, args=(ready_url, process, container), daemon=True
            ).start()
        return process.wait()
    import fcntl
    import signal
    import struct

    master, slave = os.openpty()
    original = termios.tcgetattr(sys.stdin)
    process = None

    def resize(*_):
        size = os.get_terminal_size(sys.stdin.fileno())
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", size.lines, size.columns, 0, 0))

    old_resize = signal.signal(signal.SIGWINCH, resize)
    try:
        resize()
        process = subprocess.Popen(command, env=env, stdin=slave, stdout=slave, stderr=slave)
        if ready_url is not None:
            threading.Thread(
                target=_open_when_ready, args=(ready_url, process, container), daemon=True
            ).start()
        os.close(slave)
        slave = -1
        tty.setraw(sys.stdin.fileno())
        while process.poll() is None:
            ready, _, _ = select.select([master, sys.stdin], [], [], 0.1)
            if master in ready:
                try:
                    output = os.read(master, 65536)
                except OSError:
                    break
                if not output:
                    break
                os.write(sys.stdout.fileno(), output)
            if sys.stdin in ready:
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    break
                # Ctrl+V 为原生图片粘贴。普通文本/整段 bracketed paste 不读取剪贴板。
                if data in (b"\x16", b"\x1b[118;5u"):
                    # Kitty 键盘协议启用时 Ctrl+V 的编码。
                    try:
                        content = read_macos_image()
                        if content is not None:
                            transfer_image(container, content, agent=agent)
                        else:
                            os.write(sys.stdout.fileno(), "\r\n剪贴板没有 PNG 图片。\r\n".encode())
                            continue
                    except (OSError, ValueError, subprocess.SubprocessError):
                        os.write(
                            sys.stdout.fileno(),
                            "\r\n图片传递失败，请重新复制图片再按 Ctrl+V。\r\n".encode(),
                        )
                        continue
                os.write(master, data)
        return process.wait()
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, original)
        signal.signal(signal.SIGWINCH, old_resize)
        os.close(master)
        if slave >= 0:
            os.close(slave)
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
