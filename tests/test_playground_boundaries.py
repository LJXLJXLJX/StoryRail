"""PG1-T4：Playground 与项目之间的依赖方向守卫。

用 AST 遍历全部 import（包括函数体内和 TYPE_CHECKING 块），确保两个 authority
互不依赖；唯一被允许同时接触两侧的是跨域复制模块与 server 装配点。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
SERVER = ROOT / "server"

PLAYGROUND_FORBIDDEN = (
    "core.structured_director",
    "core.project_workspaces",
    "core.director_commands",
    "core.web_contracts",
)

# 允许同时 import 两个 authority 的 server 模块：跨域复制与装配点。
BOTH_SIDES_ALLOWED = {"server/asset_transfer.py", "server/api.py", "server/__main__.py"}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                modules.add(node.module)
    return modules


def _python_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*.py")
        if "__pycache__" not in path.parts and not path.name.startswith(".")
    )


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def test_playground_does_not_import_project_packages() -> None:
    violations: list[str] = []
    for path in _python_files(CORE / "playground"):
        for module in _imported_modules(path):
            if any(_matches(module, prefix) for prefix in PLAYGROUND_FORBIDDEN):
                violations.append(f"{path.relative_to(ROOT)}: {module}")
    assert violations == []


def test_project_does_not_import_playground() -> None:
    violations: list[str] = []
    for path in _python_files(CORE / "structured_director"):
        for module in _imported_modules(path):
            if _matches(module, "core.playground"):
                violations.append(f"{path.relative_to(ROOT)}: {module}")
    assert violations == []


def test_only_asset_transfer_touches_both_sides() -> None:
    both_sides: list[str] = []
    for path in _python_files(SERVER):
        modules = _imported_modules(path)
        imports_playground = any(_matches(module, "core.playground") for module in modules)
        imports_project = any(_matches(module, "core.structured_director") for module in modules)
        if imports_playground and imports_project:
            both_sides.append(str(path.relative_to(ROOT)))
    assert set(both_sides) <= BOTH_SIDES_ALLOWED, both_sides
