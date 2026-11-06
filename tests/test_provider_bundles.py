"""Provider 目录：清单严格解析、依赖检查、按目录顺序安装、服务启动回滚与返回值校验。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sample_plugins import IMAGE

from core.model_providers.bundle import MANIFEST_NAME, BundleContext, ProviderBundle
from core.model_providers.registry import PluginInstance, ProviderRegistry
from server.provider_bundles import (
    ProviderManifest,
    install_bundles,
    load_factory,
    read_provider_directories,
    read_provider_manifest,
    start_services,
)


def _provider(tmp_path: Path, name: str, manifest: str, files: dict[str, str] | None = None):
    directory = tmp_path / name
    directory.mkdir()
    (directory / MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    for relative, text in (files or {}).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return directory


class _Recipe:
    def submit_recipe(self, request):
        raise AssertionError

    def observe(self, handle):
        raise AssertionError

    def cancel(self, handle):
        raise AssertionError

    def read_artifact(self, handle, artifact_id):
        raise AssertionError


def _plugin(endpoint: str) -> PluginInstance:
    return PluginInstance(
        IMAGE, endpoint=endpoint, recipes={recipe.id: _Recipe() for recipe in IMAGE.recipes}
    )


def test_manifest_defaults_and_resolves_paths(tmp_path: Path) -> None:
    directory = _provider(tmp_path, "mine", 'name = "mine"\nfactory = "pkg.bundle:create"\n')
    manifest = read_provider_manifest(directory)
    assert manifest == ProviderManifest(
        directory.resolve(), "mine", "pkg.bundle:create", (directory.resolve(),), ()
    )


@pytest.mark.parametrize(
    "text",
    [
        "not toml = [",
        'factory = "pkg:create"\n',
        'name = "Bad-Name"\nfactory = "pkg:create"\n',
        'name = "ok"\nfactory = "no_colon"\n',
        'name = "ok"\nfactory = "pkg:create"\nextra = 1\n',
        'name = "ok"\nfactory = "pkg:create"\npython-path = ".."\n',
        'name = "ok"\nfactory = "pkg:create"\npython-path = [".."]\n',
        'name = "ok"\nfactory = "pkg:create"\nrequires = ["pillow; os_name == \'nt\'"]\n',
    ],
)
def test_manifest_rejects_malformed_documents(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        read_provider_manifest(_provider(tmp_path, "provider", text))


def test_missing_manifest_and_duplicate_names_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=MANIFEST_NAME):
        read_provider_manifest(tmp_path)
    first = _provider(tmp_path, "a", 'name = "same"\nfactory = "a:f"\n')
    second = _provider(tmp_path, "b", 'name = "same"\nfactory = "b:f"\n')
    with pytest.raises(ValueError, match="多个 Provider 目录"):
        read_provider_directories([first, second])


def test_factory_is_imported_from_the_provider_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))
    directory = _provider(
        tmp_path,
        "dir_provider",
        'name = "dir_provider"\n'
        'factory = "dir_provider_pkg.bundle:create"\n'
        'python-path = ["src"]\n',
        {
            "src/dir_provider_pkg/__init__.py": "",
            "src/dir_provider_pkg/bundle.py": "def create(context):\n    return context\n",
        },
    )
    factory = load_factory(read_provider_manifest(directory))
    context = BundleContext(directory, tmp_path / "runtime")
    assert factory(context) is context
    assert str((directory / "src").resolve()) in sys.path


def test_missing_requirements_and_bad_factories_fail_before_import(tmp_path: Path) -> None:
    requires = _provider(
        tmp_path,
        "needs",
        'name = "needs"\nfactory = "never_imported:f"\nrequires = ["surely-not-installed-xyz"]\n',
    )
    with pytest.raises(ValueError, match="surely-not-installed-xyz"):
        load_factory(read_provider_manifest(requires))
    missing = _provider(tmp_path, "missing", 'name = "missing"\nfactory = "no_such_module_xyz:f"\n')
    with pytest.raises(ValueError, match="无法导入"):
        load_factory(read_provider_manifest(missing))


def test_install_follows_directory_order_and_returns_services(tmp_path: Path) -> None:
    calls: list[tuple[str, BundleContext]] = []
    mac = _provider(tmp_path, "mac", 'name = "mac"\nfactory = "m:f"\n')
    empty = _provider(tmp_path, "empty", 'name = "empty"\nfactory = "e:f"\n')

    def load(manifest: ProviderManifest):
        def factory(context: BundleContext) -> ProviderBundle:
            calls.append((manifest.name, context))
            if manifest.name == "mac":
                return ProviderBundle((_plugin("http://127.0.0.1:8792"),))
            return ProviderBundle(())

        return factory

    registry = ProviderRegistry()
    services = install_bundles(
        registry, read_provider_directories([mac, empty]), tmp_path / "providers", load=load
    )

    assert [name for name, _ in calls] == ["mac", "empty"]
    assert calls[0][1] == BundleContext(mac.resolve(), tmp_path / "providers" / "mac")
    assert services == []
    assert registry.installed("sample_image")


def test_install_rejects_wrong_return_type(tmp_path: Path) -> None:
    bad = _provider(tmp_path, "bad", 'name = "bad"\nfactory = "b:f"\n')
    with pytest.raises(ValueError, match="没有返回 ProviderBundle"):
        install_bundles(
            ProviderRegistry(),
            read_provider_directories([bad]),
            tmp_path,
            load=lambda manifest: lambda context: object(),
        )


def test_failed_service_start_closes_started_services_in_reverse() -> None:
    events: list[str] = []

    class Service:
        def __init__(self, name: str, fail: bool = False) -> None:
            self.name, self.fail = name, fail

        def start(self) -> None:
            if self.fail:
                raise RuntimeError(self.name)
            events.append("start " + self.name)

        def close(self) -> None:
            events.append("close " + self.name)

    with pytest.raises(RuntimeError, match="c"):
        start_services([Service("a"), Service("b"), Service("c", fail=True), Service("d")])
    assert events == ["start a", "start b", "close b", "close a"]


def test_bundle_type_checks_plugins_and_services() -> None:
    with pytest.raises(ValueError):
        ProviderBundle((object(),))
    with pytest.raises(ValueError):
        ProviderBundle((), (object(),))
