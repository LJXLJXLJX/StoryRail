"""真实 Agent 计量网关的配置契约：显式通道、正整数限额、`--validate-config` 可执行。

不建 Docker、不联网、不调用真实模型；Pi 包路径只做条件性文件存在断言，
契约字段断言无条件执行，CI 无 Pi 包也必须能跑。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.harness.real_agent.external_run import (
    DEFAULT_MAX_REQUESTS,
    configured_max_requests,
    gateway_config,
)

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "scripts/harness/real_agent/meter_gateway.mjs"
PI_PACKAGE = Path(
    "/opt/homebrew/Cellar/pi-coding-agent/0.85.0/libexec/lib/node_modules/"
    "@earendil-works/pi-coding-agent"
)


def validate_config(tmp_path, config) -> subprocess.CompletedProcess:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return subprocess.run(
        ["node", str(GATEWAY), "--validate-config", str(path)],
        capture_output=True,
        text=True,
    )


def test_gateway_config_declares_kimi_channel_and_positive_limits(tmp_path):
    config = gateway_config(tmp_path, 18081, "model-token", max_requests=40)

    assert config["mode"] == "kimi_messages"
    assert config["authorized"] is True
    assert config["limit"] is None
    assert config["maxRequests"] == 40
    assert config["port"] == 18081
    assert config["ledger"] == str(tmp_path / "model-requests.json")

    trial = config["trials"]["r08-external"]
    assert trial["token"] == "model-token"
    assert isinstance(trial["maxRequests"], int) and trial["maxRequests"] > 0
    assert trial["maxRequests"] == 40

    assert "pi-coding-agent" in config["authModule"]
    assert config["authModule"].endswith("dist/core/auth-storage.js")
    assert config["oauthModule"].endswith("auth/oauth/kimi-coding.js")
    if PI_PACKAGE.exists():
        assert Path(config["authModule"]).is_file()
        assert Path(config["oauthModule"]).is_file()


def test_gateway_config_rejects_non_positive_limit(tmp_path):
    with pytest.raises(ValueError):
        gateway_config(tmp_path, 18081, "model-token", max_requests=0)
    with pytest.raises(ValueError):
        gateway_config(tmp_path, 18081, "model-token", max_requests=-1)
    with pytest.raises(ValueError):
        gateway_config(tmp_path, 18081, "model-token", max_requests=True)


def test_configured_max_requests_defaults_and_reads_environment():
    assert configured_max_requests({}) == DEFAULT_MAX_REQUESTS == 40
    assert configured_max_requests({"STORYRAIL_REAL_AGENT_MAX_REQUESTS": "7"}) == 7
    assert configured_max_requests({"STORYRAIL_REAL_AGENT_MAX_REQUESTS": " 7 "}) == 7
    with pytest.raises(ValueError):
        configured_max_requests({"STORYRAIL_REAL_AGENT_MAX_REQUESTS": "0"})


def test_validate_config_accepts_controller_contract(tmp_path):
    config = gateway_config(tmp_path, 18082, "model-token", max_requests=40)

    result = validate_config(tmp_path, config)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"valid": True, "mode": "kimi_messages"}


def test_validate_config_rejects_missing_mode(tmp_path):
    config = gateway_config(tmp_path, 18083, "model-token", max_requests=40)
    del config["mode"]

    result = validate_config(tmp_path, config)

    assert result.returncode != 0
    assert "缺少 mode" in result.stderr
    assert "openai_responses" in result.stderr and "kimi_messages" in result.stderr


def test_validate_config_rejects_unknown_mode(tmp_path):
    config = gateway_config(tmp_path, 18084, "model-token", max_requests=40)
    config["mode"] = "auto"

    result = validate_config(tmp_path, config)

    assert result.returncode != 0
    assert "无效 mode" in result.stderr


def test_validate_config_rejects_non_positive_limit(tmp_path):
    config = gateway_config(tmp_path, 18085, "model-token", max_requests=40)
    config["trials"]["r08-external"]["maxRequests"] = 0

    result = validate_config(tmp_path, config)

    assert result.returncode != 0
    assert "maxRequests" in result.stderr


def test_validate_config_rejects_kimi_config_without_oauth_module(tmp_path):
    config = gateway_config(tmp_path, 18086, "model-token", max_requests=40)
    del config["oauthModule"]

    result = validate_config(tmp_path, config)

    assert result.returncode != 0
    assert "oauthModule" in result.stderr
