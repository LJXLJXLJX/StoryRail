"""由实际 Pi bash 工具执行；只检查合成拓扑，报告布尔值。"""

import ctypes
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from core.structured_director import StructuredDirectorStore

ROOT = "/api/projects/" + "a" * 32 + "/structured-director"


def denied(action):
    try:
        action()
    except (OSError, ValueError):
        return True
    return False


def request(method, suffix, body=None, authenticated=True):
    headers = {"Content-Type": "application/json", "X-Caller-Role": "human"}
    if authenticated:
        headers["Authorization"] = "Bearer " + Path("/workspace/token").read_text()
    data = None if body is None else json.dumps(body).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                "http://core:8765" + ROOT + suffix, data=data, method=method, headers=headers
            ),
            timeout=5,
        ) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def main():
    results = {}
    authority = Path("/state/stories") / ("a" * 32) / "project.json"
    paths = [
        authority,
        Path("/state/core_canary"),
        Path("/state/policy.json"),
        Path("/state/stories/.trash"),
        Path("/state/backup"),
        Path("/human/token"),
        Path("/human/profile/Default/Cookies"),
        Path("/human/cookie_canary"),
    ]
    for index, path in enumerate(paths):
        for kind, action in {
            "read": path.read_bytes,
            "write": lambda p=path: p.write_bytes(b"invalid"),
            "chmod": lambda p=path: p.chmod(0o777),
            "unlink": path.unlink,
            "rename": lambda p=path: p.rename("/workspace/stolen"),
        }.items():
            results[f"path_{index}_{kind}_denied"] = denied(action)
    results["parent_replace_denied"] = denied(lambda: Path("/state").rename("/workspace/state"))
    results["parent_create_denied"] = denied(lambda: Path("/state").mkdir())
    alias = Path("/workspace/alias")
    alias.symlink_to(authority)
    results["symlink_read_denied"] = denied(alias.read_bytes)
    results["symlink_write_denied"] = denied(lambda: alias.write_bytes(b"invalid"))
    results["relative_path_denied"] = denied(lambda: Path("../state/core_canary").read_bytes())
    results["hardlink_denied"] = denied(lambda: os.link(authority, "/workspace/hardlink"))
    results["second_store_denied"] = denied(
        lambda: StructuredDirectorStore(authority.parent, "a" * 32)
    )
    results["code_write_denied"] = denied(lambda: Path("/app/server/http.py").write_text("invalid"))
    Path("/workspace/mount").mkdir()
    results["mount_denied"] = (
        ctypes.CDLL(None, use_errno=True).mount(b"/state", b"/workspace/mount", None, 4096, None)
        == -1
    )
    results["no_admin_identity"] = os.getuid() == 10002 and 0 not in os.getgroups()
    results["no_docker_socket"] = not Path("/var/run/docker.sock").exists()
    results["no_core_environment"] = "CORE_CANARY" not in os.environ
    status = Path("/proc/self/status").read_text()
    results["no_effective_capabilities"] = "CapEff:\t0000000000000000" in status
    results["no_new_privileges"] = "NoNewPrivs:\t1" in status
    command = json.loads(Path("/workspace/command.json").read_text())
    projection = {
        "name": "project.get_projection",
        "expected_revision": command["expected_revision"],
        "idempotency_key": "read",
        "arguments": {"level": "outline", "scope": {"project_id": "a" * 32}},
    }
    results["native_web_read"] = request("POST", "/commands", projection)[0] == 200
    results["unauthenticated_denied"] = request("POST", "/commands", projection, False)[0] == 401
    for name in [
        "final.approve",
        "final.select_candidate",
        "project.apply_repair_patch",
        "run.resume",
    ]:
        results[name + "_denied"] = (
            request("POST", "/commands", {**command, "name": name})[0] == 403
        )
    for suffix in [
        "/final/approve",
        "/final/select",
        "/final/reopen",
        "/assets/images",
        "/director/messages",
        "/keyframes/" + "e" * 32 + "/generate",
        "/generations/" + "e" * 32 + "/retry",
    ]:
        results[suffix + "_denied"] = (
            request("POST", suffix, {"approval": True, "caller": "human"})[0] == 403
        )
    forged = {**command, "arguments": {"scope": {"scene_ids": ["e" * 32]}, "operations": []}}
    results["wrong_target_denied"] = request("POST", "/application/commands", forged)[0] == 403
    # 实际子 Pi 会话，只使用同一个合成模型端点，继承同等 OS 边界。
    child = subprocess.run(
        [
            "pi",
            "--print",
            "--no-session",
            "--provider",
            "canary",
            "--model",
            "child",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "probe",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    results["native_child_agent"] = child.returncode == 0 and Path("/workspace/child-ok").is_file()
    Path("/workspace/probe.json").write_text(json.dumps(results, sort_keys=True))
    print(json.dumps({"all_passed": all(results.values()), "checks": len(results)}))
    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
