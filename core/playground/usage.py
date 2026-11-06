"""Playground Asset 占用判定（纯函数）。

目前只有一种占用原因：Asset 是某个未结束实验的输入。
"""

from __future__ import annotations

from .models import UNFINISHED_PHASES, PlaygroundDocument

UNFINISHED_RUN_INPUT = "unfinished_run_input"


def asset_usage(document: PlaygroundDocument) -> dict[str, tuple[str, ...]]:
    """返回 ``asset_id → 占用原因码元组``。"""
    reasons: dict[str, list[str]] = {}
    for run in document.runs:
        if run.phase not in UNFINISHED_PHASES:
            continue
        for asset_id in run.input_asset_ids:
            bucket = reasons.setdefault(asset_id, [])
            if UNFINISHED_RUN_INPUT not in bucket:
                bucket.append(UNFINISHED_RUN_INPUT)
    return {asset_id: tuple(codes) for asset_id, codes in reasons.items()}


def is_in_use(document: PlaygroundDocument, asset_id: str) -> bool:
    return bool(asset_usage(document).get(asset_id))
