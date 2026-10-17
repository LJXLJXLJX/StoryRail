"""工程指标测量脚本：输出 JSON（模块规模、依赖、门禁耗时、Agent 驻留字节等）。

用法：
    .venv/bin/python scripts/metrics.py             # 静态指标（秒级）
    .venv/bin/python scripts/metrics.py --with-timing  # 额外实测 pytest/vitest 时长

指标编号 M1–M18 沿用函数名 ``m<N>_*``；每个指标的测量口径以对应函数实现为准。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_json(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True).stdout


def m1_store() -> dict:
    """store facade（store/__init__.py）行数 / public 方法数。

    P2-C1 起 store.py 拆为 store/ 包，facade 在 __init__.py；
    P2-D1 后 domains 归位、剩余方法经 __getattr__ 路由，def 数即卡口径。
    """
    src = (ROOT / "core/structured_director/store/__init__.py").read_text()
    return {
        "lines": len(src.splitlines()),
        "public_methods": len(re.findall(r"def [a-z]", src)),
    }


def m2_function_level_imports() -> dict:
    """core/ 内函数级 core import 数，口径与 tests/test_layer_rules.py 守卫一致。

    只计 import 目标为 core.* 的语句；豁免 TYPE_CHECKING 块与 PEP 562
    模块级 __getattr__ 懒加载 export。基线 91 为全量口径（含 json 等
    stdlib 函数内 import），P2-A5 起改为 core-internal 口径（守卫基线 0）。
    """
    count = 0
    for path in sorted((ROOT / "core").rglob("*.py")):
        tree = ast.parse(path.read_text())
        parents: dict = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                targets = [node.module] if node.module else []
            else:
                continue
            type_checking = False
            function_level = False
            cur = parents.get(node)
            while cur is not None:
                if (
                    isinstance(cur, ast.If)
                    and isinstance(cur.test, ast.Name)
                    and cur.test.id == "TYPE_CHECKING"
                ):
                    type_checking = True
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_level = True
                    if cur.name == "__getattr__" and isinstance(parents.get(cur), ast.Module):
                        function_level = False
                cur = parents.get(cur)
            if function_level and not type_checking:
                count += sum(1 for target in targets if target and target.startswith("core"))
    return {"count": count}


def m3_models() -> dict:
    """models/ 包总行数 / 总类数（P2-B1 起 models.py 拆为 models/ 包）。"""
    package = ROOT / "core/structured_director/models"
    lines = 0
    classes = 0
    for path in sorted(package.rglob("*.py")):
        src = path.read_text()
        lines += len(src.splitlines())
        classes += len(re.findall(r"^class ", src, re.M))
    return {
        "lines": lines,
        "classes": classes,
        "largest_file": max(
            (len(p.read_text().splitlines()) for p in package.rglob("*.py")), default=0
        ),
    }


def m4_codecs() -> dict:
    """手写 proposal schema / 统一错误类型数量。

    P3-T2 起六域 schema 均由 schema_gen 生成；P7-T2 删除最后的六个兼容错误子类，
    codec 只抛 ``schema_gen.ProposalError``。这里计名字以 OUTPUT_SCHEMA 结尾且值为
    dict literal 的模块级赋值；``legacy_error_aliases`` 统计 codec 模块内残留的
    ``*Error`` 类定义（目标为 0）。
    """
    proposals = ROOT / "core/director_proposals"
    handwritten_schemas = 0
    legacy_error_aliases = 0
    for path in proposals.glob("*_codec.py"):
        tree = ast.parse(path.read_text())
        handwritten_schemas += sum(
            1
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            and isinstance(node.value, ast.Dict)
            and any(
                target.id.endswith("OUTPUT_SCHEMA")
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(target, ast.Name)
            )
        )
        legacy_error_aliases += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name.endswith("Error")
        )
    return {
        "handwritten_schemas": handwritten_schemas,
        "canonical_error_classes": 1,
        "legacy_error_aliases": legacy_error_aliases,
    }


def m6_mcp_tool_schema() -> dict:
    sys.path.insert(0, str(ROOT))
    import integrations.storyrail_mcp.app as app

    models = app.published_models()
    per_tool = {
        name: len(
            json.dumps(
                app.published_tool_schema(name, model),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )
        for name, model in models.items()
    }
    return {
        "tools": len(models),
        "schema_bytes_total": sum(per_tool.values()),
        "per_tool": per_tool,
    }


def m7_h3_contract_bytes() -> dict:
    total = sum(
        p.stat().st_size
        for p in (ROOT / "core/director_proposals/skills/h3-prompt-writing").rglob("*")
        if p.is_file()
    )
    return {"h3_contract_bytes": total}


def m8_app_tsx() -> dict:
    src = (ROOT / "web/src/App.tsx").read_text()
    return {"lines": len(src.splitlines()), "useState_count": len(re.findall(r"useState", src))}


def m9_workspace_props() -> dict:
    src = (ROOT / "web/src/director_workspace/contracts.tsx").read_text()
    match = re.search(r"export interface StructuredDirectorWorkspaceProps \{(.*?)\n\}", src, re.S)
    fields = re.findall(r"^\s{2}(\w+)\??:", match.group(1), re.M)
    return {"props_fields": len(fields)}


def m11_pollers() -> dict:
    """前端快照轮询器数与间隔（P5-C1 合并为单一可见性感知调度器）。"""
    src = (ROOT / "web/src/director_workspace/useSnapshotScheduler.ts").read_text()

    def interval(name: str) -> int | None:
        match = re.search(rf"{name} = (\d+)", src)
        return int(match.group(1)) if match else None

    return {
        "schedulers": len(re.findall(r"export function useSnapshotScheduler", src)),
        "active_interval_ms": interval("ACTIVE_INTERVAL_MS"),
        "idle_interval_ms": interval("IDLE_INTERVAL_MS"),
        "max_backoff_ms": interval("MAX_BACKOFF_MS"),
    }


def m12_oracle_scenarios() -> dict:
    oracle_dir = ROOT / "tests/oracle"
    scenarios = len(list(oracle_dir.glob("*.py"))) if oracle_dir.exists() else 0
    return {"oracle_scenarios": scenarios}


def m13_ci_workflows() -> dict:
    workflows = ROOT / ".github/workflows"
    return {"ci_workflows": len(list(workflows.glob("*.yml"))) if workflows.exists() else 0}


def m15_test_setup_files() -> dict:
    """测试搭建样板口径（P7-T4 按卡片定义）。

    ``public_factory_files``：使用公共工厂的文件——conftest fixture
    （service_factory/store_factory/http_server/journey）、
    provider_factory（make_service/provider_registry）或共享
    ``proposal_fixture_service.ProposalFixtureService``。
    ``raw_self_build_files``：不经过任何公共工厂、直接构造 Store/Service 的文件。
    ``self_build_ratio``：raw_self_build / total（卡片口径，目标 ≤0.20）。
    ``builder_test_files``：需要 store/service 的文件数，用于给出
    「builder 中公共工厂覆盖率」这一更有意义的补充口径。
    """
    test_files = sorted((ROOT / "tests").glob("test_*.py"))
    raw = re.compile(r"(?<!Fixture)(StructuredDirectorStore|StructuredDirectorService)\(")
    factory_names = (
        "service_factory",
        "store_factory",
        "http_server",
        "journey",
        "make_service",
        "provider_registry",
        "ProposalFixtureService",
    )
    raw_files: list[str] = []
    factory_files: list[str] = []
    for path in test_files:
        text = path.read_text()
        if raw.search(text):
            raw_files.append(path.name)
        if any(name in text for name in factory_names):
            factory_files.append(path.name)
    total = len(test_files)
    builder_files = sorted(set(raw_files) | set(factory_files))
    raw_only = sorted(set(raw_files) - set(factory_files))
    return {
        "total_test_files": total,
        "builder_test_files": len(builder_files),
        "public_factory_files": len(factory_files),
        "raw_self_build_files": len(raw_only),
        "self_build_ratio": round(len(raw_only) / total, 3) if total else 0.0,
    }


def m16_declared_runtime_deps() -> dict:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r"^dependencies = \[(.*?)\]", text, re.S | re.M)
    declared = [d.strip() for d in match.group(1).split(",") if d.strip()] if match else []
    extras = re.findall(r"^(\w+) = \[", text, re.M)
    return {"runtime_dependencies": len(declared), "extras": extras}


def m17_agent_baseline_bytes() -> dict:
    import inspect

    import integrations.storyrail_mcp.app as app

    source = inspect.getsource(app)
    match = re.search(r"instructions=\((.*?)\n        \),\n", source, re.S)
    instructions = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1)))
    return {
        "agents_md_bytes": (ROOT / "AGENTS.md").stat().st_size,
        "mcp_instructions_bytes": len(instructions.encode()),
    }


def m18_agent_turn_tokens() -> dict:
    data = json.loads(
        (ROOT / "scripts/harness/benchmark/baselines/agent-tokens-2026-09-11.json").read_text()
    )
    rows = {(row["phase"], row["lane"], row["turn"]): row for row in data["rows"]}
    measured = {
        f"{lane}_turn1_{phase}_input_tokens": rows[(phase, lane, 1)]["input_tokens"]
        for lane in ("director", "h3", "keyframe")
        for phase in ("before", "after")
    }
    return {
        **measured,
        "supplemental_ref2va": {
            phase: {"input_tokens": data["supplemental_ref2va"][phase]["input_tokens"]}
            for phase in ("before", "after")
        },
    }


def m14_timing() -> dict:
    started = time.monotonic()
    pytest_out = _run_json([str(ROOT / ".venv/bin/python"), "-m", "pytest"])
    pytest_seconds = time.monotonic() - started
    match = re.search(r"in ([\d.]+)s", pytest_out)
    started = time.monotonic()
    _run_json(["npm", "test"], cwd=ROOT / "web")
    vitest_seconds = time.monotonic() - started
    return {
        "pytest_wall_seconds": round(pytest_seconds, 1),
        "pytest_reported_seconds": float(match.group(1)) if match else None,
        "vitest_wall_seconds": round(vitest_seconds, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-timing", action="store_true", help="实测 pytest/vitest 时长")
    args = parser.parse_args()

    metrics = {
        "M1_store": m1_store(),
        "M2_function_level_imports": m2_function_level_imports(),
        "M3_models": m3_models(),
        "M4_codecs": m4_codecs(),
        "M6_mcp_tool_schema": m6_mcp_tool_schema(),
        "M7_h3_contract_bytes": m7_h3_contract_bytes(),
        "M8_app_tsx": m8_app_tsx(),
        "M9_workspace_props": m9_workspace_props(),
        "M11_pollers": m11_pollers(),
        "M12_oracle_scenarios": m12_oracle_scenarios(),
        "M13_ci_workflows": m13_ci_workflows(),
        "M15_test_setup_files": m15_test_setup_files(),
        "M16_declared_runtime_deps": m16_declared_runtime_deps(),
        "M17_agent_baseline_bytes": m17_agent_baseline_bytes(),
        "M18_agent_turn_tokens": m18_agent_turn_tokens(),
    }
    if args.with_timing:
        metrics["M14_timing"] = m14_timing()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
