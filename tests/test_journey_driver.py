"""journey 旅程驱动器自测（P1-T2 验收）。

journey 本身零断言；这里的断言只验证驱动序列能走通真实 HTTP 状态机，
并快照关键可达状态供人工审查。覆盖：
1. drama 主线：建项目 → 引用 proposal → 审核 → 脚本 proposal → 确认；
2. narration 主线：TTS 生成 + 选择 + 时序确认；
3. 全流程 smoke：drama 一路驱动到最终 Approval（O1 的驱动预演）。
"""

from __future__ import annotations

from conftest import Journey


def test_journey_drama_script_reaches_structured_script(journey):
    created = journey.create_project(title="旅程Drama")
    assert created["project"]["aspect_ratio"] == "16:9"
    journey.propose_references()
    journey.approve_references()
    journey.apply_script()
    snapshot = journey.snapshot()
    assert snapshot["director_script"]["scenes"], "脚本应包含至少一个 Scene"
    assert snapshot["director_script"]["scenes"][0]["shots"][0]["segments"]
    document = journey.document()
    assert document["revision"] == snapshot["revision"]


def test_journey_narration_tts_select_and_timing(journey):
    journey.create_project(title="旅程旁白")
    journey.propose_references()
    journey.approve_references()
    journey.apply_script(scenes=[Journey.narration_scene()])
    journey.select_narrator_voice()
    journey.select_narration_audio()
    snapshot = journey.snapshot()
    cue = snapshot["director_script"]["scenes"][0]["narration_cues"][0]
    assert cue["zh"]["selected_audio_asset_id"] is not None
    assert cue["en"]["selected_audio_asset_id"] is not None
    # 时间基准是中英已选音频中较长的一条。
    assert cue["timing_language"] in {"zh", "en"}
    assert cue["timing_seconds"] == max(
        cue["zh"]["selected_duration_seconds"], cue["en"]["selected_duration_seconds"]
    )
    journey.plan_narration_shots()
    snapshot = journey.snapshot()
    scene = snapshot["director_script"]["scenes"][0]
    assert scene["shots"], "旁白时序确认后应按真实音频规划 Shot"
    script = snapshot["director_script"]
    assert script["production_baseline_revision"] == script["revision"]


def test_journey_full_drama_journey_to_approval(journey):
    journey.create_project(title="旅程全程")
    journey.propose_references()
    journey.approve_references()
    journey.apply_script()
    journey.plan_narration_shots()
    journey.unlock_visual_production()
    snapshot = journey.snapshot()
    assert snapshot["workspace_layers"]["videos_unlocked"] is True
    assert snapshot["keyframe_plan"]["segments"], "解锁后应立即建立关键帧空卡绑定"
    journey.generate_keyframes()
    snapshot = journey.snapshot()
    assert all(
        frame["selected_asset_id"] is not None for frame in snapshot["keyframe_plan"]["keyframes"]
    )
    journey.generate_videos()
    assert all(
        segment["selected_asset_id"] is not None
        for segment in journey.snapshot()["video_plan"]["segments"]
    )
    journey.assemble_scene_finals()
    journey.assemble_final()
    journey.approve_final()
    snapshot = journey.snapshot()
    assert snapshot["status"] == "approved"
    assert snapshot["final_approval"] is not None
    assert all(snapshot["workspace_layers"].values())
