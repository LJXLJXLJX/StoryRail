"""O1 · 完整旅程 happy path oracle。

ARRIVE   journey 全流程驱动（合成 Provider 全部确定性成功），走真实 HTTP。
ORACLE   断言权威 project.json 的可达状态谓词：
         - 终态 status == "approved"，final_approval 可溯源；
         - final_assembly 逐 Clip 引用各 Scene 已审核成片 Asset；
         - 每个 Scene 的 scene_final_video Generation succeeded 且未作废；
         - workspace_layers 全部解锁（阶段能力累加）；
         - Keyframe / Segment 视频 / 成片的选择全部可溯源到 succeeded Generation 的
           输出 Asset（候选生成与选择分离）。
覆盖领域规则：工作流边界（workspace_layers 累加）、Scene 成片确定性渲染、
最终装配只拼接 Scene 成片、Approval 与选择分离。
"""

from __future__ import annotations

import pytest


def _succeeded_outputs(document: dict) -> dict[str, str]:
    """generation_id -> output_asset_id，只含未作废的 succeeded Generation。"""
    return {
        generation["id"]: generation["output_asset_id"]
        for generation in document["generations"]
        if generation["phase"] == "succeeded" and not generation["dismissed"]
    }


@pytest.mark.oracle
def test_oracle_full_journey_reaches_approved(journey):
    # ARRIVE：完整生产旅程。
    journey.create_project(title="O1完整旅程")
    journey.propose_references()
    journey.approve_references()
    journey.apply_script()
    journey.plan_narration_shots()
    journey.unlock_visual_production()
    journey.generate_keyframes()
    journey.generate_videos()
    journey.assemble_scene_finals()
    journey.assemble_final()
    journey.approve_final()

    document = journey.document()
    structured = document["structured_director"]
    scene_ids = [scene["id"] for scene in structured["director_script"]["scenes"]]

    # ORACLE：终态与 Approval。
    assert structured["status"] == "approved"
    approval = structured["final_approval"]
    assert approval is not None
    assembly = structured["final_assembly"]
    # ORACLE：一次 Approval 同时绑定中英两个单语成片的当前选择。
    for language in ("zh", "en"):
        assert assembly[f"selected_{language}_asset_id"] == approval[f"{language}_asset_id"]

    # ORACLE：最终装配只按脚本顺序拼接各 Scene 已审核成片。
    clips = assembly["clips"]
    assert [clip["scene_id"] for clip in clips] == scene_ids
    succeeded = _succeeded_outputs(document)
    scene_final_assets = {
        (generation["target_id"], generation["language"]): succeeded[generation["id"]]
        for generation in document["generations"]
        if generation["kind"] == "scene_final_video" and not generation["dismissed"]
    }
    assert set(scene_final_assets) == {
        (scene_id, language) for scene_id in scene_ids for language in ("zh", "en")
    }
    for clip in clips:
        for language in ("zh", "en"):
            assert clip[f"{language}_asset_id"] == scene_final_assets[(clip["scene_id"], language)]

    # ORACLE：每个 Scene 成片 Generation succeeded 且未作废。
    scene_final_generations = [
        generation
        for generation in document["generations"]
        if generation["kind"] == "scene_final_video"
    ]
    assert {generation["target_id"] for generation in scene_final_generations} == set(scene_ids)
    for generation in scene_final_generations:
        assert not generation["dismissed"]
        assert (
            scene_final_assets[(generation["target_id"], generation["language"])]
            == succeeded[generation["id"]]
        )

    # ORACLE：最终成片 Generation 与 Approval 可溯源。
    final_generations = [
        generation
        for generation in document["generations"]
        if generation["kind"] == "final_video" and not generation["dismissed"]
    ]
    final_by_id = {generation["id"]: generation for generation in final_generations}
    for language in ("zh", "en"):
        generation_id = approval[f"{language}_generation_id"]
        assert final_by_id[generation_id]["language"] == language
        assert succeeded[generation_id] == approval[f"{language}_asset_id"]

    # ORACLE：workspace_layers 全解锁（阶段能力累加，上游回改不退阶段）。
    assert all(structured["workspace_layers"].values())

    # ORACLE：Keyframe / Segment 视频的选择全部可溯源到 succeeded Generation。
    asset_ids = {asset["id"] for asset in document["assets"]}
    for frame in structured["keyframe_plan"]["keyframes"]:
        selected = frame["selected_asset_id"]
        assert selected is not None and selected in asset_ids
        assert selected in set(succeeded.values())
    for segment in structured["video_plan"]["segments"]:
        selected = segment["selected_asset_id"]
        assert selected is not None and selected in asset_ids
        assert selected in set(succeeded.values())
