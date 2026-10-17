"""harness 统一 fixture：确定性合成媒体、探针素材与 Core 装配。

产品代码不 import 本包；harness 各子目录（benchmark/real_agent/probes）共享这里，
避免各代脚本各写一份合成 Provider。
"""

from .media import png, wav
from .synthetic_media import SyntheticMediaProvider

__all__ = ["SyntheticMediaProvider", "png", "wav"]
