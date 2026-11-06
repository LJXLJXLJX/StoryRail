"""P6-T1 · token benchmark 门禁。

ARRIVE   真实 MCP stdio 子进程 + 本进程真实 loopback Core（合成媒体 Provider，
         不跑模型、不联网），按 `scripts/harness/benchmark/scenarios/*.json`
         的确定性脚本驱动 reference→script→location→keyframe→h3→ref2va 六个标准场景。
ORACLE   断言门禁谓词（口径见 `scripts/harness/benchmark/meter.py`）：
         - 每场景 input+output 线上字节 ≤ `scripts/harness/benchmark/baselines/token-bench.json`
           冻结值 × 1.0（防回归）；
         - 同一进程内重复计量逐字节一致（确定性；只复跑最小场景 reference）。
覆盖领域规则：Agent 每轮固定驻留与读路径成本可测量、可门禁，且优化后的
第一版实测值被冻结为回归基线。
BUDGET   六场景约 18s（stdio 子进程 + 合成 Provider），确定性复跑另加一个场景。
"""

from __future__ import annotations

import json

import pytest

from scripts.harness.benchmark import report

pytestmark = pytest.mark.oracle


@pytest.fixture(scope="module")
def runs() -> dict[str, dict]:
    return report.measure()


def test_token_benchmark_gate_holds(runs: dict[str, dict]):
    frozen = report.load_frozen()
    failures = report.check(runs, frozen)
    assert failures == [], "\n".join(failures)

    summary = {name: run["summary"] for name, run in runs.items()}
    for name in ("reference", "script", "location", "keyframe", "h3", "ref2va"):
        assert name in summary, f"缺少标准场景 {name}"
        assert summary[name]["total_wire_bytes"] <= frozen["scenarios"][name]["total_wire_bytes"]
        assert summary[name]["error_responses"] == 0


def test_token_benchmark_measurement_is_deterministic(runs: dict[str, dict]):
    again = report.measure(["reference"])
    assert again == {"reference": runs["reference"]}


def test_gate_rejects_regression(runs: dict[str, dict]):
    """负向对照：冻结值人为收紧后门禁必须红（证明门禁真的在比较）。"""
    frozen = report.load_frozen()
    tightened = json.loads(json.dumps(frozen))
    tightened["scenarios"]["ref2va"]["total_wire_bytes"] -= 1
    failures = report.check(runs, tightened)
    assert len(failures) == 1 and "ref2va" in failures[0]
