"""图片比例词汇：Core、私有服务、Worker 与 MCP 使用同一份列表。"""

from __future__ import annotations

import typing

from core.model_providers.manifest import IMAGE_ASPECT_RATIOS
from default_model_providers_implement.codex_worker import _IMAGE_ASPECT_RATIOS as WORKER
from default_model_providers_implement.strict_json import IMAGE_ASPECT_RATIOS as SERVICE
from integrations.storyrail_mcp.production_tools import AspectRatio


def test_aspect_ratio_vocabulary_is_identical_everywhere() -> None:
    assert set(IMAGE_ASPECT_RATIOS) == SERVICE == WORKER == set(typing.get_args(AspectRatio))
    assert len(IMAGE_ASPECT_RATIOS) == len(set(IMAGE_ASPECT_RATIOS))
