"""H3 全局渲染设置：分辨率档位、步数、SageAttention 与 SelfLift 的组合。

它是 Core 进程级设置，不属于项目或 Playground 状态；每次提交 H3 时读取当前值，
改设置只影响之后新提交的任务，不失效已有候选。mode 仍由 Segment/实验自己决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .contracts import H3_STEPS


class H3Resolution(StrEnum):
    P480 = "480p"
    P720 = "720p"
    P1080 = "1080p"


# H3 画布必须落在 32 像素网格（16 倍潜变量下采样再 2×2 patchify），且边长不超过 1920；
# 最终装配会统一缩放裁切。9:16 是 16:9 宽高对调；2:1 保持同档短边，1080p 受长边上限约束取 1920×960。
_CANVAS = {
    "16:9": {
        H3Resolution.P480: (864, 480),
        H3Resolution.P720: (1280, 704),
        H3Resolution.P1080: (1920, 1088),
    },
    "9:16": {
        H3Resolution.P480: (480, 864),
        H3Resolution.P720: (704, 1280),
        H3Resolution.P1080: (1088, 1920),
    },
    "2:1": {
        H3Resolution.P480: (960, 480),
        H3Resolution.P720: (1408, 704),
        H3Resolution.P1080: (1920, 960),
    },
}


@dataclass(frozen=True, slots=True)
class H3RenderSettings:
    resolution: H3Resolution = H3Resolution.P720
    steps: int = 20
    sage_attention: bool = True
    selflift: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, H3Resolution):
            raise ValueError("H3 分辨率只允许 480p、720p 或 1080p。")
        if isinstance(self.steps, bool) or self.steps not in H3_STEPS:
            raise ValueError("H3 步数只允许 20 或 8。")
        if not isinstance(self.sage_attention, bool) or not isinstance(self.selflift, bool):
            raise ValueError("H3 sage_attention 与 selflift 必须是布尔值。")

    def canvas(self, aspect_ratio: str) -> tuple[int, int]:
        canvases = _CANVAS.get(aspect_ratio)
        if canvases is None:
            raise ValueError("H3 画布只支持 16:9、9:16 或 2:1。")
        return canvases[self.resolution]

    def to_json(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution.value,
            "steps": self.steps,
            "sage_attention": self.sage_attention,
            "selflift": self.selflift,
        }

    @classmethod
    def from_json(cls, value: object) -> H3RenderSettings:
        if not isinstance(value, dict) or set(value) != {
            "resolution",
            "steps",
            "sage_attention",
            "selflift",
        }:
            raise ValueError("H3 渲染设置字段不合法。")
        try:
            resolution = H3Resolution(value["resolution"])
        except ValueError as exc:
            raise ValueError("H3 分辨率只允许 480p、720p 或 1080p。") from exc
        return cls(resolution, value["steps"], value["sage_attention"], value["selflift"])
