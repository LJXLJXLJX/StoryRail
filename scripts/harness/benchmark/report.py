"""生成 token benchmark 报告，并执行防回归门禁比较。

用法::

    # 生成报告（同时打印门禁结论）
    .venv/bin/python scripts/harness/benchmark/report.py --write

    # 只跑门禁（默认 pytest 用例走这里）
    .venv/bin/python scripts/harness/benchmark/report.py --check

报告字段含义（`schema` 自描述）：

- `environment.date`：本机日期，唯一允许逐次变化的字段之一。
- `environment.git_sha` / `python_version`：取证元数据，同样易变。
- `gate.scenario_total_multiplier`：标准场景总线上字节相对冻结值的倍数上限（1.0 = 防回归）。
- `frozen.tools_list_bytes`：tools/list 总字节，只记录不门禁
  （逐字节变化由 `tests/fixtures/mcp_project_tools.json` 把关）。
- `frozen.scenarios.<name>.total_wire_bytes`：冻结的每场景 input+output 紧凑 JSON 字节。
- `runs.<name>.summary`：本次实测汇总（口径见 `meter.py` 模块 docstring）。
- `runs.<name>.requests`：逐请求明细，`pagination_rounds` 为分页请求次数。
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.harness.benchmark.fake_agent_driver import (  # noqa: E402
    load_scenario,
    run_scenario,
    scenario_names,
)

REPORT_PATH = ROOT / "scripts/harness/benchmark/baselines/token-bench.json"
GATE_SCENARIO_TOTAL_MULTIPLIER = 1.0


def measure(names: list[str] | None = None) -> dict[str, dict]:
    """跑指定场景（默认全部）并返回与报告 `runs` 同构的结果。"""
    selected = names or scenario_names()
    runs: dict[str, dict] = {}
    for name in selected:
        result = run_scenario(name)
        runs[name] = {
            "capability": load_scenario(name)["capability"],
            "bootstrap": load_scenario(name)["bootstrap"],
            "summary": result.summary,
            "requests": result.requests,
        }
    return runs


def git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def build_report(runs: dict[str, dict]) -> dict:
    first = next(iter(runs.values()))
    tools_list_bytes = first["summary"]["tools_list_bytes"]
    return {
        "schema": {
            "name": "storyrail-token-bench",
            "version": 1,
            "description": (
                "确定性 fake Agent driver 的 MCP 线上字节计量；不调用真实模型。"
                "字节口径见 scripts/harness/benchmark/meter.py。"
            ),
            "volatile_fields": [
                "environment.date",
                "environment.git_sha",
                "environment.python_version",
            ],
        },
        "environment": {
            "date": date.today().isoformat(),
            "git_sha": git_sha(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "driver": "scripts/harness/benchmark/fake_agent_driver.py",
        },
        "gate": {
            "scenario_total_multiplier": GATE_SCENARIO_TOTAL_MULTIPLIER,
        },
        "frozen": {
            "tools_list_bytes": tools_list_bytes,
            "scenarios": {
                name: {"total_wire_bytes": run["summary"]["total_wire_bytes"]}
                for name, run in runs.items()
            },
        },
        "runs": runs,
    }


def check(runs: dict[str, dict], frozen: dict, gate: dict | None = None) -> list[str]:
    """返回违规列表；空列表表示门禁通过。"""
    gate = gate or {
        "scenario_total_multiplier": GATE_SCENARIO_TOTAL_MULTIPLIER,
    }
    failures: list[str] = []
    measured_tools = {run["summary"]["tools_list_bytes"] for run in runs.values()}
    if len(measured_tools) != 1:
        failures.append(f"tools/list 字节在场景间不一致：{sorted(measured_tools)}")
    for name, run in runs.items():
        baseline = frozen["scenarios"].get(name)
        if baseline is None:
            failures.append(f"场景 {name} 缺少冻结值")
            continue
        limit = baseline["total_wire_bytes"] * gate["scenario_total_multiplier"]
        measured = run["summary"]["total_wire_bytes"]
        if measured > limit:
            failures.append(
                f"场景 {name} 总线上字节 {measured} > 冻结值 {baseline['total_wire_bytes']} × "
                f"{gate['scenario_total_multiplier']}"
            )
    return failures


def load_frozen() -> dict:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))["frozen"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", action="append", default=None)
    parser.add_argument("--write", action="store_true", help=f"写入 {REPORT_PATH}")
    parser.add_argument("--check", action="store_true", help="按冻结值执行防回归门禁")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    runs = measure(args.scenario)
    report = build_report(runs)
    failures: list[str] = []
    if args.check:
        frozen = load_frozen()
        failures = check(runs, frozen, report["gate"])
    if args.write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {REPORT_PATH.relative_to(ROOT)}")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    for name, run in runs.items():
        print(f"{name}: {json.dumps(run['summary'], ensure_ascii=False)}")
    if args.check:
        if failures:
            for failure in failures:
                print(f"BENCHMARK_GATE_FAIL {failure}")
            return 1
        print("benchmark gate: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
