"""受信宿主控制器；仅管理自己创建的合成 Docker 资源，不是产品 adapter。"""

import argparse
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

# 与 real_agent 共用 scripts/harness/real_agent/docker/Dockerfile 构建的同一镜像。
IMAGE = "storyrail-t07-isolation:20260912"


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result


def start():
    runtime = Path(tempfile.mkdtemp(prefix="storyrail-t07-"))
    prefix = "storyrail-t07-" + uuid.uuid4().hex[:8]
    state = {"prefix": prefix, "image": IMAGE, "runtime": str(runtime)}
    for key in ("state", "workspace", "human"):
        state[key] = prefix + "-" + key
        docker("volume", "create", "--label", "storyrail.synthetic=T07", state[key])
    state["network"] = prefix + "-network"
    docker("network", "create", "--label", "storyrail.synthetic=T07", state["network"])
    mounts = sum(
        (
            ["--mount", f"type=volume,source={state[k]},target=/{k}"]
            for k in ("state", "workspace", "human")
        ),
        [],
    )
    docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "0:0",
        *mounts,
        IMAGE,
        "python",
        "/app/scripts/harness/probes/provision.py",
    )
    state["core"] = prefix + "-core"
    docker(
        "run",
        "-d",
        "--name",
        state["core"],
        "--label",
        "storyrail.synthetic=T07",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        "10001:10001",
        "--network",
        state["network"],
        "--network-alias",
        "core",
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--mount",
        f"type=volume,source={state['state']},target=/state",
        "-p",
        "127.0.0.1::8765",
        IMAGE,
        # 统一镜像的默认 CMD 是 real_agent 的 external_core；探针显式选择合成 Core。
        "python",
        "/app/scripts/harness/probes/core_fixture.py",
    )
    (runtime / "state.json").write_text(json.dumps(state))
    for _ in range(50):
        logs = docker("logs", state["core"]).stdout
        if "SYNTHETIC_CORE_READY" in logs:
            break
        if (
            docker("inspect", "--format", "{{.State.Running}}", state["core"]).stdout.strip()
            != "true"
        ):
            raise RuntimeError(docker("logs", state["core"]).stderr)
        time.sleep(0.2)
    else:
        raise RuntimeError("合成 Core 未就绪。")
    port = docker("port", state["core"], "8765").stdout.strip().rsplit(":", 1)[1]
    state["core_url"] = "http://127.0.0.1:" + port
    command = docker("exec", state["core"], "cat", "/state/public-command.json").stdout
    # 公共 command 不含凭据；只复制到 Agent 自己的 workspace。
    docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "10002:10002",
        "--mount",
        f"type=volume,source={state['workspace']},target=/workspace",
        IMAGE,
        "python",
        "-c",
        "from pathlib import Path; import sys; "
        "Path('/workspace/command.json').write_text(sys.argv[1])",
        command,
    )
    token = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "10003:10003",
        "--mount",
        f"type=volume,source={state['human']},target=/human,readonly",
        IMAGE,
        "cat",
        "/human/token",
    ).stdout
    for name, value in [
        ("human-token", token),
        ("browser-token", uuid.uuid4().hex + uuid.uuid4().hex),
    ]:
        path = runtime / name
        path.write_text(value)
        path.chmod(0o600)
    state["authority_before"] = authority_hash(state)
    (runtime / "state.json").write_text(json.dumps(state))
    print(json.dumps({"runtime": str(runtime), "core_url": state["core_url"]}))


def authority_hash(state):
    result = docker(
        "exec",
        state["core"],
        "python",
        "-c",
        "from pathlib import Path; import hashlib; "
        "print(hashlib.sha256(Path('/state/stories/'+'a'*32+'/project.json')"
        ".read_bytes()).hexdigest())",
    )
    return result.stdout.strip()


def probe(runtime, evidence):
    state = json.loads((runtime / "state.json").read_text())
    evidence.mkdir(parents=True, exist_ok=True)
    state["agent"] = state["prefix"] + "-agent"
    (runtime / "state.json").write_text(json.dumps(state))
    result = docker(
        "run",
        "--name",
        state["agent"],
        "--label",
        "storyrail.synthetic=T07",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        "10002:10002",
        "--network",
        state["network"],
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--workdir",
        "/workspace",
        "--mount",
        f"type=volume,source={state['workspace']},target=/workspace",
        IMAGE,
        "python",
        "/app/scripts/harness/probes/native_agent.py",
        check=False,
    )
    print(result.stdout.strip())
    for name in ("native-agent.json", "probe.json"):
        copied = docker(
            "cp", state["agent"] + ":/workspace/" + name, str(evidence / name), check=False
        )
        if copied.returncode:
            print("missing evidence: " + name)
    after = authority_hash(state)
    second = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        "10001:10001",
        "--mount",
        f"type=volume,source={state['state']},target=/state",
        IMAGE,
        "python",
        "-c",
        "from pathlib import Path; from server.writer import SingleWriterLease\n"
        "with SingleWriterLease(Path('/state/stories')): pass",
        check=False,
    )
    configs = {}
    for role in ("core", "agent"):
        value = json.loads(docker("inspect", state[role]).stdout)[0]
        configs[role] = {
            "user": value["Config"]["User"],
            "image_id": value["Image"],
            "read_only": value["HostConfig"]["ReadonlyRootfs"],
            "cap_drop": value["HostConfig"]["CapDrop"],
            "security_opt": value["HostConfig"]["SecurityOpt"],
            "mounts": [
                {"type": m["Type"], "destination": m["Destination"], "rw": m["RW"]}
                for m in value["Mounts"]
            ],
        }
    summary = {
        "authority_unchanged": state["authority_before"] == after,
        "before_sha256": state["authority_before"],
        "after_sha256": after,
        "second_writer_rejected": second.returncode != 0,
        "agent_exit": result.returncode,
        "containers": configs,
    }
    (evidence / "deployment.json").write_text(json.dumps(summary, indent=2))
    if (
        result.returncode
        or not summary["authority_unchanged"]
        or not summary["second_writer_rejected"]
    ):
        raise RuntimeError("隔离验收尚未通过；保留资源用于诊断。")
    print("ISOLATION_PROBE_PASSED")


def cleanup(runtime):
    state = json.loads((runtime / "state.json").read_text())
    for key in ("agent", "core"):
        if key in state:
            docker("rm", "-f", state[key], check=False)
    docker("network", "rm", state["network"])
    for key in ("state", "workspace", "human"):
        docker("volume", "rm", state[key])
    for name in ("human-token", "browser-token"):
        (runtime / name).unlink(missing_ok=True)
    print("SYNTHETIC_RESOURCES_REMOVED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "probe", "cleanup"])
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--evidence", type=Path, default=Path("var/validation/isolation"))
    args = parser.parse_args()
    if args.action == "start":
        start()
    elif args.action == "probe":
        probe(args.runtime, args.evidence)
    else:
        cleanup(args.runtime)
