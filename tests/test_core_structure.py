from pathlib import Path


def test_every_core_source_directory_has_readme() -> None:
    core = Path(__file__).resolve().parents[1] / "core"
    directories = [core, *sorted(path for path in core.rglob("*") if path.is_dir())]
    missing = [
        path.relative_to(core.parent)
        for path in directories
        if "__pycache__" not in path.parts
        and "skills" not in path.relative_to(core).parts
        and not (path / "README.md").is_file()
    ]

    assert missing == []


def test_agent_skill_containers_hold_self_describing_standard_packages() -> None:
    core = Path(__file__).resolve().parents[1] / "core"
    containers = sorted(path for path in core.rglob("skills") if path.is_dir())

    assert containers
    for container in containers:
        packages = sorted(path for path in container.iterdir() if path.is_dir())
        assert packages
        assert all((package / "SKILL.md").is_file() for package in packages)
