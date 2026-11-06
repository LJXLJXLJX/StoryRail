"""按 ``--provider-dir`` 加载 Provider 目录（清单格式见 ``core.model_providers.bundle``）。

清单 ``slatehand-provider.toml``::

    name = "example"                                   # bundle 名，也是运行时目录名
    factory = "slatehand_providers.bundle:create_bundle"
    python-path = ["."]                                # 相对 Provider 目录，加入 import 路径
    requires = []                                      # Core 环境必须已安装的发行包名

目录按出现顺序安装，同一能力未显式绑定时先安装的插件是默认实现。
"""

from __future__ import annotations

import importlib
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from core.model_providers.bundle import (
    MANIFEST_NAME,
    BundleContext,
    BundleService,
    ProviderBundle,
)
from core.model_providers.registry import ProviderRegistry

_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_FACTORY = re.compile(r"[A-Za-z_][\w.]*:[A-Za-z_]\w*")
_DISTRIBUTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_KEYS = frozenset({"name", "factory", "python-path", "requires"})


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    directory: Path
    name: str
    factory: str
    python_path: tuple[Path, ...]
    requires: tuple[str, ...]


def read_provider_manifest(directory: Path) -> ProviderManifest:
    """严格读取 Provider 目录的清单：未知键、非法名称与越出目录的 import 路径都拒绝。"""
    directory = directory.expanduser().resolve()
    path = directory / MANIFEST_NAME
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Provider 目录缺少可读的 {MANIFEST_NAME}：{directory}（{exc}）") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} 不是合法 TOML：{exc}") from exc
    unknown = set(document) - _KEYS
    if unknown:
        raise ValueError(f"{path} 包含未知键：{'、'.join(sorted(unknown))}")
    name = document.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError(f"{path} 的 name 必须是小写字母开头的标识符。")
    factory = document.get("factory")
    if not isinstance(factory, str) or not _FACTORY.fullmatch(factory):
        raise ValueError(f"{path} 的 factory 必须形如 package.module:function。")
    python_path = document.get("python-path", ["."])
    if not isinstance(python_path, list) or not all(isinstance(p, str) for p in python_path):
        raise ValueError(f"{path} 的 python-path 必须是字符串列表。")
    resolved: list[Path] = []
    for item in python_path:
        entry = (directory / item).resolve()
        if entry != directory and directory not in entry.parents:
            raise ValueError(f"{path} 的 python-path 不能越出 Provider 目录：{item}")
        resolved.append(entry)
    requires = document.get("requires", [])
    if not isinstance(requires, list) or not all(
        isinstance(item, str) and _DISTRIBUTION.fullmatch(item) for item in requires
    ):
        raise ValueError(f"{path} 的 requires 必须是发行包名列表。")
    return ProviderManifest(directory, name, factory, tuple(resolved), tuple(requires))


def read_provider_directories(directories: list[Path]) -> list[ProviderManifest]:
    manifests = [read_provider_manifest(directory) for directory in directories]
    seen: set[str] = set()
    for manifest in manifests:
        if manifest.name in seen:
            raise ValueError(f"Provider bundle {manifest.name} 出现在多个 Provider 目录中。")
        seen.add(manifest.name)
    return manifests


def load_factory(manifest: ProviderManifest) -> Callable[[BundleContext], ProviderBundle]:
    """检查依赖、把 Provider 目录加入 import 路径并导入工厂。"""
    missing = [name for name in manifest.requires if not _installed(name)]
    if missing:
        raise ValueError(
            f"Provider bundle {manifest.name} 需要在 Core 环境中安装：{'、'.join(missing)}"
        )
    for entry in reversed(manifest.python_path):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    module_name, attribute = manifest.factory.split(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"Provider bundle {manifest.name} 无法导入 {module_name}：{exc}") from exc
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise ValueError(f"Provider bundle {manifest.name} 的工厂 {manifest.factory} 不可调用。")
    return factory


def install_bundles(
    registry: ProviderRegistry,
    manifests: list[ProviderManifest],
    runtime_root: Path,
    *,
    load: Callable[[ProviderManifest], Callable[[BundleContext], ProviderBundle]] = load_factory,
) -> list[BundleService]:
    """依次构造并安装 bundle，返回需要随 Core 启停的服务（尚未启动）。"""
    services: list[BundleService] = []
    for manifest in manifests:
        factory = load(manifest)
        bundle = factory(BundleContext(manifest.directory, runtime_root / manifest.name))
        if not isinstance(bundle, ProviderBundle):
            raise ValueError(f"Provider bundle {manifest.name} 没有返回 ProviderBundle。")
        for plugin in bundle.plugins:
            registry.install(plugin)
        services.extend(bundle.services)
    return services


def start_services(services: list[BundleService]) -> None:
    """按顺序启动；任一失败时逆序关闭已启动的服务并重新抛出。"""
    started: list[BundleService] = []
    try:
        for service in services:
            service.start()
            started.append(service)
    except BaseException:
        close_services(started)
        raise


def close_services(services: list[BundleService]) -> None:
    for service in reversed(services):
        try:
            service.close()
        except Exception as exc:  # 关闭失败只报告，不阻止其余服务关闭。
            print(f"Provider 服务关闭失败：{exc}", file=sys.stderr)


def _installed(name: str) -> bool:
    try:
        distribution(name)
    except PackageNotFoundError:
        return False
    return True
