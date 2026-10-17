"""R08 可信控制器；阶段授权由操作者显式输入精确 command，绝不自动批准模型意图。"""

import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

from core.application.caller import command_digest
from scripts.harness.real_agent.run import allocate_port, docker

# 与 probes 共用 scripts/harness/real_agent/docker/Dockerfile 构建的同一镜像。
IMAGE = "storyrail-r08-external:20260913"

# 真实通道的默认请求上限：保守值，可用环境变量覆盖。
DEFAULT_MAX_REQUESTS = 40

# Pi 客户端包内真实认证模块的安装前缀；真实运行要求该包已安装。
PI_PACKAGE = Path(
    "/opt/homebrew/Cellar/pi-coding-agent/0.85.0/libexec/lib/node_modules/"
    "@earendil-works/pi-coding-agent"
)


def configured_max_requests(environ=None):
    """读取真实通道请求上限；必须是正整数，未设置时给保守默认值。"""
    raw = (os.environ if environ is None else environ).get("STORYRAIL_REAL_AGENT_MAX_REQUESTS")
    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_REQUESTS
    value = int(raw)
    if value <= 0:
        raise ValueError("STORYRAIL_REAL_AGENT_MAX_REQUESTS 必须是正整数")
    return value


def gateway_config(root, port, model_token, *, max_requests):
    """构造计量网关授权配置。

    控制器按实际使用的 kimi OAuth 模块与 Pi `external_agent.py` 的
    `api: anthropic-messages / model: kimi-for-coding` 显式选择 `mode`；网关不再有
    静默默认通道。全局与逐 trial 都必须带正整数上限，上限缺失会放开「不限次」语义，
    因此这里始终写入。
    """
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests <= 0:
        raise ValueError("max_requests 必须是正整数")
    root = Path(root)
    return {
        "authorized": True,
        "limit": None,
        "mode": "kimi_messages",
        "maxRequests": max_requests,
        "port": port,
        "authModule": str(PI_PACKAGE / "dist/core/auth-storage.js"),
        "oauthModule": str(
            PI_PACKAGE / "node_modules/@earendil-works/pi-ai/dist/auth/oauth/kimi-coding.js"
        ),
        "ledger": str(root / "model-requests.json"),
        "trials": {"r08-external": {"token": model_token, "maxRequests": max_requests}},
    }


def write_volume(state, key, files):
    code = """import json,sys
from pathlib import Path
for name,text in json.load(sys.stdin).items():
 p=Path('/workspace')/name;p.parent.mkdir(parents=True,exist_ok=True)
 temp=p.with_name('.'+p.name+'.tmp');temp.write_text(text);temp.chmod(0o600);temp.replace(p)
"""
    docker(
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--user",
        "10001:10001" if key == "core" else "10002:10002",
        "--mount",
        f"type=volume,source={state['volumes'][key]},target=/workspace",
        IMAGE,
        "python",
        "-c",
        code,
        data=json.dumps(files),
    )


def read_volume(state, key, path):
    return docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "10001:10001" if key == "core" else "10002:10002",
        "--mount",
        f"type=volume,source={state['volumes'][key]},target=/workspace,readonly",
        IMAGE,
        "cat",
        "/workspace/" + path,
    ).stdout


def save(state):
    Path(state["runtime"], "state.json").write_text(json.dumps(state))


def prepare():
    root = Path(tempfile.mkdtemp(prefix="storyrail-r08-")).resolve()
    prefix = "storyrail-r08-" + secrets.token_hex(4)
    state = {
        "runtime": str(root),
        "prefix": prefix,
        "volumes": {},
        "containers": [],
        "network": prefix + "-net",
        "core": prefix + "-core",
        "port": allocate_port(),
    }
    state["human_token"] = secrets.token_urlsafe(36)
    state["agent_token"] = secrets.token_urlsafe(36)
    for key in ("core", "agent"):
        volume = prefix + "-" + key
        state["volumes"][key] = volume
        docker("volume", "create", "--label", "storyrail.synthetic=R08", volume)
        uid = "10001" if key == "core" else "10002"
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--mount",
            f"type=volume,source={volume},target=/workspace",
            IMAGE,
            "sh",
            "-c",
            f"chown {uid}:{uid} /workspace && chmod 700 /workspace",
        )
    state["policy"] = {
        "version": 2,
        "external_mutations": True,
        "callers": [
            {
                "id": "human",
                "role": "human",
                "project_ids": [],
                "capabilities": ["project.read", "human.write", "workspace.manage"],
                "expires_at": 4102444800,
                "token_sha256": hashlib.sha256(state["human_token"].encode()).hexdigest(),
                "grants": [],
            }
        ],
    }
    write_volume(state, "core", {"policy.json": json.dumps(state["policy"])})
    docker("network", "create", "--label", "storyrail.synthetic=R08", state["network"])
    gateway_port = allocate_port()
    model_token = secrets.token_urlsafe(36)
    config = gateway_config(
        root,
        gateway_port,
        model_token,
        max_requests=configured_max_requests(),
    )
    (root / "gateway-config.json").write_text(json.dumps(config))
    (root / "gateway-config.json").chmod(0o600)
    write_volume(
        state,
        "agent",
        {
            "core-token": state["agent_token"],
            "config.json": json.dumps(
                {
                    "gateway_url": f"http://host.docker.internal:{gateway_port}/trial/r08-external",
                    "model_token": model_token,
                }
            ),
        },
    )
    state["containers"].append(state["core"])
    save(state)
    docker(
        "run",
        "-d",
        "--name",
        state["core"],
        "--label",
        "storyrail.synthetic=R08",
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
        "-p",
        f"127.0.0.1:{state['port']}:8765",
        "--mount",
        f"type=volume,source={state['volumes']['core']},target=/state",
        IMAGE,
    )
    print(json.dumps({"runtime": str(root), "core_port": state["port"]}))
    return state


def grant(state, project_id, command):
    agent = next(c for c in state["policy"]["callers"] if c["id"] == "agent")
    agent["grants"].append(
        {
            "id": command["idempotency_key"],
            "project_id": project_id,
            "command_digest": command_digest(command),
            "expires_at": 4102444800,
        }
    )
    write_volume(state, "core", {"policy.json": json.dumps(state["policy"])})
    save(state)


def phase(state, name, prompt):
    write_volume(state, "agent", {name + ".md": prompt})
    container = state["prefix"] + "-" + name
    if container in state["containers"]:
        raise ValueError("阶段名称必须唯一，保留失败与消耗")
    state["containers"].append(container)
    save(state)
    return docker(
        "run",
        "--name",
        container,
        "--label",
        "storyrail.synthetic=R08",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        "10002:10002",
        "--network",
        state["network"],
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--mount",
        f"type=volume,source={state['volumes']['agent']},target=/workspace",
        "-w",
        "/workspace",
        IMAGE,
        "python",
        "/app/scripts/harness/real_agent/external_agent.py",
        name,
        check=False,
    )


if __name__ == "__main__":
    prepare()


def http(state, method, path, body=None, *, agent=False, media_type="application/json"):
    import urllib.error
    import urllib.request

    data = (
        body if isinstance(body, bytes) else (None if body is None else json.dumps(body).encode())
    )
    token = state["agent_token" if agent else "human_token"]
    request = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}" + path,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": media_type},
    )
    try:
        response = urllib.request.urlopen(request)
    except urllib.error.HTTPError as exc:
        response = exc
    value = json.load(response)
    with Path(state["runtime"], "http-events.jsonl").open("a") as target:
        target.write(
            json.dumps(
                {
                    "caller": "agent" if agent else "human",
                    "method": method,
                    "path": path,
                    "body": {"byte_count": len(body)} if isinstance(body, bytes) else body,
                    "status": response.status,
                    "result": value,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return response.status, value


def snapshot(state):
    status, value = http(state, "GET", state["route"])
    assert status == 200, value
    return value


def create_project(state, plan):
    status, value = http(
        state,
        "POST",
        "/api/projects",
        {
            "title": "R08 外部 Agent 完整流程",
            "aspect_ratio": "16:9",
            "director_plan_markdown": plan,
            "narration_languages": ["zh", "en"],
        },
    )
    assert status == 201, value
    pid = value["project"]["id"]
    state["project_id"] = pid
    state["route"] = "/api/projects/" + pid + "/structured-director"
    state["policy"]["callers"][0]["project_ids"].append(pid)
    state["policy"]["callers"].append(
        {
            "id": "agent",
            "role": "agent",
            "project_ids": [pid],
            "capabilities": ["project.read", "project.mutate", "project.propose"],
            "expires_at": 4102444800,
            "token_sha256": hashlib.sha256(state["agent_token"].encode()).hexdigest(),
            "grants": [],
        }
    )
    write_volume(state, "core", {"policy.json": json.dumps(state["policy"])})
    save(state)
    return snapshot(state)


def grant_tool(state, tool, arguments):
    from integrations.storyrail_mcp.production_tools import MODELS, translate

    request = MODELS[tool].model_validate(arguments)
    name, values = translate(tool, request)
    command = {
        "name": name,
        "arguments": values,
        "expected_revision": request.expected_revision,
        "idempotency_key": request.idempotency_key,
    }
    grant(state, request.project_id, command)
    return {"tool": tool, "arguments": arguments}


def tool_call(state, request, label, *, drop_response=False):
    """测试操作者显式机械执行；单独标记，不冒充模型生成的调用。"""
    filename = label + "-call.json"
    write_volume(state, "agent", {filename: json.dumps(request, ensure_ascii=False)})
    result = docker(
        "run",
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user",
        "10002:10002",
        "--network",
        state["network"],
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "--mount",
        f"type=volume,source={state['volumes']['agent']},target=/workspace",
        IMAGE,
        "python",
        "/app/scripts/harness/real_agent/external_client.py",
        "/workspace/" + filename,
        *(["--drop-response"] if drop_response else []),
        check=False,
    )
    with Path(state["runtime"], "controller-tools.jsonl").open("a") as log:
        log.write(
            json.dumps(
                {
                    "label": label,
                    "request": request,
                    "stdout": result.stdout,
                    "exit_code": result.returncode,
                    "stderr": result.stderr,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return result
