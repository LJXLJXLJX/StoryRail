"""Guard extracted domain computations against acquiring external authority."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "name",
    [
        "assembly_timeline",
        "script_mutations",
        "keyframe_mutations",
        "generation_lifecycle",
        "production_context",
        "keyframe_requests",
        "director_steps",
        "run_state",
        "repair_mutations",
        "video_mutations",
        "asset_metadata",
        "manual_commands",
    ],
)
def test_domain_computations_have_no_persistence_or_runtime_dependency(name: str) -> None:
    tree = ast.parse((ROOT / "core" / "structured_director" / f"{name}.py").read_text())
    forbidden = {"store", "service", "http_api", "subprocess", "pathlib", "os"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (set((node.module or "").split(".")) & forbidden)
            assert not (node.module or "").startswith(("agent_thread_adapters", "server"))
        elif isinstance(node, ast.Import):
            assert all(not (set(alias.name.split(".")) & forbidden) for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open"


def _usecase_sources(name: str) -> list[Path]:
    file_path = ROOT / "core/structured_director" / f"{name}.py"
    if file_path.is_file():
        return [file_path]
    return sorted((ROOT / "core/structured_director" / name).rglob("*.py"))


@pytest.mark.parametrize("name", ["production_commands", "media_submission"])
def test_usecases_depend_on_injected_authority_not_service_implementation(name):
    for path in _usecase_sources(name):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[-1] != "service"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"StructuredDirectorStore", "DirectorCommandRegistry"}
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "_atomic_write"
                if name == "media_submission":
                    assert node.func.attr not in {
                        "propose",
                        "respond",
                        "compile",
                        "instruct_production",
                    }
