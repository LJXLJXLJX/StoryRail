"""Provider bundle：一个 Provider 目录对外提供的一组插件实例与部署服务。

Provider 目录根部放 ``MANIFEST_NAME`` 清单，写明 bundle 名与工厂位置；Core 启动时按
``--provider-dir`` 的顺序读取清单、导入工厂并调用 ``factory(context)``，再把返回的插件依次安装进
``ProviderRegistry``。地址、凭据与部署拓扑都由 bundle 从自己的目录读取，Core 不理解。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .registry import PluginInstance

MANIFEST_NAME = "slatehand-provider.toml"


@runtime_checkable
class BundleService(Protocol):
    """随 Core 启停的部署服务（例如拉起远端模型服务、维持活性租约）。

    ``start()`` 可以阻塞到服务就绪，失败时抛出异常让 Core 停止启动；``close()`` 不应抛出。
    """

    def start(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BundleContext:
    """Core 交给 bundle 的最小上下文：Provider 目录本身，以及归该 bundle 独占的运行时目录。"""

    provider_directory: Path
    runtime_directory: Path


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """插件按顺序安装：同一能力未显式绑定时，先安装的插件是默认实现。

    服务按顺序启动、逆序关闭。
    """

    plugins: tuple[PluginInstance, ...]
    services: tuple[BundleService, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(plugin, PluginInstance) for plugin in self.plugins):
            raise ValueError("bundle 的 plugins 只能包含 PluginInstance。")
        if not all(isinstance(service, BundleService) for service in self.services):
            raise ValueError("bundle 的 services 必须提供 start() 与 close()。")


BundleFactory = Callable[[BundleContext], ProviderBundle]
