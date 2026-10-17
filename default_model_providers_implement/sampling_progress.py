"""按采样回调间隔计时；缺少基准时不虚构速度和 ETA。"""

from __future__ import annotations

import math
import time


class SamplingProgress:
    def __init__(self, label: str) -> None:
        self.label = label
        self._previous: tuple[int, int, float] | None = None
        self._smoothed: float | None = None

    def update(self, completed: int, total: int) -> str:
        now = time.monotonic()
        previous = self._previous
        prefix = f"{self.label} 扩散采样 {completed}/{total}"
        if previous is None or previous[1] != total or completed < previous[0]:
            self._previous = (completed, total, now)
            self._smoothed = None
            return f"{prefix} · 正在估算每步耗时。"
        delta = completed - previous[0]
        if delta == 0:
            return ""  # 重复进度不重置计时、不覆盖上次有效统计。
        elapsed = now - previous[2]
        self._previous = (completed, total, now)
        if elapsed <= 0 or not math.isfinite(elapsed):
            self._smoothed = None
            return f"{prefix} · 正在估算每步耗时。"
        per_step = elapsed / delta
        self._smoothed = (
            per_step if self._smoothed is None else 0.3 * per_step + 0.7 * self._smoothed
        )
        measurement = "本步" if delta == 1 else f"最近 {delta} 步均值"
        speed = f"{measurement} {per_step:.2f} s/iter"
        if completed == total:
            return f"{prefix} · {speed} · 采样完成，等待解码与封装。"
        remaining = max(1, math.ceil(self._smoothed * (total - completed)))
        return f"{prefix} · {speed} · 采样预计剩余 {remaining} 秒。"
