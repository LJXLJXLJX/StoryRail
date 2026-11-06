"""对白时长只以已选 TTS WAV 的真实时长为准。"""

from __future__ import annotations

from .models import ShotSegment, StructuredDirectorDocument

# 首句对白之前与末句对白之后各留的呼吸余量；相邻 Segment 硬切时两段对白之间至少隔两倍此值。
# 只是软提示：Core 不拒绝余量不足的时序或时长。
DIALOGUE_BREATHING_SECONDS = 0.5


def actual_dialogue_timing(
    document: StructuredDirectorDocument,
    segment: ShotSegment,
    *,
    output_duration_seconds: float | None = None,
) -> dict[str, object] | None:
    """返回逐句真实 WAV 时序；未全部选择或未完成校准时显式标记未就绪。

    ``output_duration_seconds`` 是插件给出的实际输出时长（例如向上取到帧网格）；
    缺省时按请求时长计算段尾余量。
    """
    if not segment.dialogue_lines:
        return None
    if document.dialogue_plan is None:
        return {"ready": False, "reason": "dialogue_plan_missing"}
    items = {item.dialogue_line_id: item for item in document.dialogue_plan.items}
    assets = {item.id: item for item in document.assets}
    lines = []
    maximum_end = 0.0
    for line in segment.dialogue_lines:
        item = items.get(line.id)
        if item is None or item.selected_audio_asset_id is None:
            return {"ready": False, "reason": "audio_not_selected"}
        asset = assets.get(item.selected_audio_asset_id)
        if asset is None or asset.duration_seconds is None:
            return {"ready": False, "reason": "audio_missing"}
        if item.start_seconds is None:
            return {"ready": False, "reason": "timing_not_set"}
        end = item.start_seconds + asset.duration_seconds
        maximum_end = max(maximum_end, end)
        lines.append(
            {
                "dialogue_line_id": line.id,
                "asset_id": asset.id,
                "start_seconds": item.start_seconds,
                "duration_seconds": asset.duration_seconds,
                "end_seconds": end,
            }
        )
    video_end = (
        segment.duration_estimate_seconds
        if output_duration_seconds is None
        else output_duration_seconds
    )
    lead = min(item["start_seconds"] for item in lines)
    tail = video_end - maximum_end
    return {
        "ready": maximum_end <= segment.duration_estimate_seconds + 1e-6,
        "minimum_duration_seconds": maximum_end,
        "duration_seconds": segment.duration_estimate_seconds,
        "lines": lines,
        "breathing_seconds": DIALOGUE_BREATHING_SECONDS,
        "lead_seconds": round(lead, 3),
        "tail_seconds": round(tail, 3),
        "breathing_hints": _breathing_hints(lead, tail),
    }


def _breathing_hints(lead: float, tail: float) -> list[str]:
    hints = []
    if lead + 1e-6 < DIALOGUE_BREATHING_SECONDS:
        hints.append(
            f"首句对白在 {lead:.3f} 秒开口，段首建议至少留 {DIALOGUE_BREATHING_SECONDS} 秒；"
            "可把各句起点整体后移并相应加长时长，开口前写可见动作与环境声。"
        )
    if tail + 1e-6 < DIALOGUE_BREATHING_SECONDS:
        hints.append(
            f"末句对白结束后视频只剩 {max(tail, 0.0):.3f} 秒，段尾建议至少留 "
            f"{DIALOGUE_BREATHING_SECONDS} 秒；可加长 Segment 时长，尾部写持续动作与环境声。"
        )
    return hints
