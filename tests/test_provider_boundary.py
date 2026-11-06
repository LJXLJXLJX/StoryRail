"""Core 不认识任何具体 Provider：Core 侧代码不得 import 已知的 Provider 实现包。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SIDE = ("core", "server", "integrations", "slatehand_contracts", "scripts", "tests", "web")
PROVIDER_PACKAGES = ("slatehand_providers", "default_model_providers_implement")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def _python_files(*roots: Path):
    for root in roots:
        for path in root.rglob("*.py"):
            if "__pycache__" not in path.parts and "node_modules" not in path.parts:
                yield path


def test_core_side_never_imports_provider_packages() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in _python_files(*(ROOT / name for name in CORE_SIDE))
        for name in _imports(path)
        if name.split(".")[0] in PROVIDER_PACKAGES
    ]
    assert offenders == []
