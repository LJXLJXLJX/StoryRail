"""store/domains 装配模块（P2-D1）。

把十个域 collaborator 类集中导入，供 store/__init__.py 在模块尾部
（全部模块级助手绑定后）一次性装配；拆分本模块即可让 isort/E402 稳定。
"""

from .domains.asset import AssetDomain
from .domains.final import FinalDomain
from .domains.generation import GenerationDomain
from .domains.keyframe import KeyframeDomain
from .domains.location import LocationDomain
from .domains.narration import NarrationDomain
from .domains.reference import ReferenceDomain
from .domains.run import RunDomain
from .domains.script import ScriptDomain
from .domains.video import VideoDomain

__all__ = [
    "AssetDomain",
    "FinalDomain",
    "GenerationDomain",
    "KeyframeDomain",
    "LocationDomain",
    "NarrationDomain",
    "ReferenceDomain",
    "RunDomain",
    "ScriptDomain",
    "VideoDomain",
]
