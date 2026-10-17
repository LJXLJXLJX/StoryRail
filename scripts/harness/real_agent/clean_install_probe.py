import importlib.util
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import core
from core.director_proposals.professional_contracts import CONTRACTS

assert importlib.util.find_spec("openai_codex") is None
assert importlib.util.find_spec("codex") is None
assert shutil.which("pi") is None and shutil.which("codex") is None
assert "site-packages" in core.__file__
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
with tempfile.TemporaryDirectory() as root:
    proc = subprocess.Popen(
        ["python", "-m", "server", "--port", str(port), "--stories-directory", root],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects") as r:
                    assert json.load(r) == {"projects": []}
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("server startup failed")
        body = json.dumps(
            {
                "title": "R09 clean install",
                "aspect_ratio": "16:9",
                "director_plan_markdown": "# 合成方案\n静态海岸。",
                "narration_languages": ["zh", "en"],
            }
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/projects",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            assert r.status == 201
            result = json.load(r)
        assert result["structured_director"]["director_plan_markdown"].startswith("# 合成")
        assert "assistant_mode" not in result["structured_director"]
        assert Path("/validation/web/dist/index.html").is_file()
        print(
            json.dumps(
                {
                    "installed_from_wheel": True,
                    "agent_cli": False,
                    "agent_sdk": False,
                    "server_start": True,
                    "api_create": 201,
                    "web_dist": True,
                    "professional_contracts": list(CONTRACTS),
                },
                ensure_ascii=False,
            )
        )
    finally:
        proc.terminate()
        proc.wait(timeout=10)
