"""O2 · 中断恢复 oracle。

ARRIVE   drama 旅程驱动到关键帧批量生成进行中：合成 image provider 的观察序列停在
         RUNNING（phases=[RUNNING]，重复应答），经真实 HTTP 提交第一批（首帧）并
         refresh 进入 running；随后 OracleHttpServer.restart() 模拟进程死——停
         server/loop 线程，保留 stories_root/workspaces/共享 providers/policy，
         整体重建 StoryRailApi 与 service 缓存（service 构造时运行
         recover_interrupted_submissions）；最后把观察序列切回 SUCCEEDED，继续
         旅程到 Approval。
ORACLE   断言可达状态谓词（project.json 与 API snapshot）：
         - 重启不丢已提交任务：running Generation 原样保留（同 id、同 phase），
           项目 revision 不回退，图片 provider 提交次数不增长（无重复提交）；
         - 生成继续而非重头来：恢复后同批下一波只提交剩余帧，首帧不重复提交，
           每个激活帧恰好一个 keyframe_image Generation；
         - 终态与 O1 等价：status approved、final_approval 非空、
           workspace_layers 全解锁、Keyframe / Segment 视频选择可溯源到
           succeeded Generation 输出 Asset。
覆盖领域规则：任务与产物进度持久化（Generation 句柄在 project.json，重启后可续
观察）、重试/恢复不自动重放已提交任务、候选生成与选择分离、workspace_layers
阶段能力累加、Approval 与选择分离。
BUDGET   单场景 ≤20s（真实 loopback HTTP + 合成 Provider）。
"""

from __future__ import annotations

import pytest

from core.model_providers.boundary import GenerationPhase


@pytest.mark.oracle
def test_oracle_restart_during_keyframe_batch_recovers_without_resubmission(journey, http_server):
    image = http_server.providers.image
    journey.create_project(title="O2中断恢复")
    journey.propose_references()
    journey.approve_references()
    journey.apply_script()
    journey.plan_narration_shots()
    journey.unlock_visual_production()
    journey.plan_keyframes()

    # ARRIVE：观察停在 RUNNING；显式批量提交第一批（只有首帧前置就绪）。
    image.observations = [GenerationPhase.RUNNING]
    journey._post(
        "O2.first_wave",
        f"{journey.resource}/keyframes/generate-batch",
        {"expected_revision": journey._revision()},
    )
    journey._post("O2.refresh", f"{journey.resource}/generations/refresh", {})
    before = journey.document()
    keyframe_image_before = [
        generation for generation in before["generations"] if generation["kind"] == "keyframe_image"
    ]
    assert len(keyframe_image_before) == 1
    assert keyframe_image_before[0]["phase"] == "running"
    revision_before = before["revision"]
    submits_before = len(image.requests)

    # ARRIVE：进程死（保留 stories_root 与共享 providers）。
    http_server.restart()

    # ORACLE：重启恢复不丢任务、不重放提交；running 不被 recover 改写。
    snap = journey.snapshot()  # 触发 service 重建与 recover_interrupted_submissions
    assert snap["revision"] == revision_before
    recovered = [
        generation for generation in snap["generations"] if generation["kind"] == "keyframe_image"
    ]
    assert [(g["id"], g["phase"]) for g in recovered] == [
        (g["id"], g["phase"]) for g in keyframe_image_before
    ]
    assert len(image.requests) == submits_before

    # ARRIVE：Provider 恢复可成功；批次继续提交剩余帧（首帧不重复提交）。
    image.observations = [GenerationPhase.SUCCEEDED]
    journey.generate_keyframe_candidates()
    journey.select_keyframe_candidates()
    assert len(image.requests) == submits_before + 1  # 只新增尾帧一次提交
    journey.generate_videos()
    journey.assemble_scene_finals()
    journey.assemble_final()
    journey.approve_final()

    # ORACLE：终态与 O1 等价。
    document = journey.document()
    structured = document["structured_director"]
    assert structured["status"] == "approved"
    assert structured["final_approval"] is not None
    assert all(structured["workspace_layers"].values())

    # ORACLE：每个激活帧恰好一个 keyframe_image Generation（无重复提交），
    # 且选择与 succeeded Generation 输出可溯源。
    frame_ids = [frame["id"] for frame in structured["keyframe_plan"]["keyframes"]]
    by_target: dict[str, list[dict]] = {frame_id: [] for frame_id in frame_ids}
    for generation in document["generations"]:
        if generation["kind"] == "keyframe_image":
            by_target[generation["target_id"]].append(generation)
    assert all(len(by_target[frame_id]) == 1 for frame_id in frame_ids)
    succeeded_outputs = {
        generation["id"]: generation["output_asset_id"]
        for generation in document["generations"]
        if generation["phase"] == "succeeded" and not generation["dismissed"]
    }
    for frame in structured["keyframe_plan"]["keyframes"]:
        generation = by_target[frame["id"]][0]
        assert generation["phase"] == "succeeded"
        assert frame["selected_asset_id"] == succeeded_outputs[generation["id"]]
    for segment in structured["video_plan"]["segments"]:
        assert segment["selected_asset_id"] in set(succeeded_outputs.values())
