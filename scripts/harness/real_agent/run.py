"""外部验收共用的隔离资源工具，不依赖开发任务系统。"""

import json
import socket
import subprocess


def docker(*args, data=None, check=True):
    result = subprocess.run(["docker", *args], input=data, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError("合成Docker操作失败：" + result.stderr[-1000:])
    return result


def save(runtime, state):
    (runtime / "state.json").write_text(json.dumps(state))


def allocate_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
