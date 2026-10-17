"""O4 · 上游失效级联 oracle。

ARRIVE   双 Scene 项目（第一场两个 Shot、第二场一个 Shot）驱动到最终装配已选择，
         随后经真实 script revision 入口（agent 的 script.apply_operations）
         删除第一场的第二个 Shot。
ORACLE   断言失效精确传播：
         - 被删 Shot 的 Keyframe 绑定与视频卡随槽位移除，其历史 Asset/Generation
           保留（作废不解绑、不删除）；
         - 同 Scene 幸存 Shot 的 Keyframe / Segment 视频选择保留（重建只动被删槽位）；
         - 未受影响 Scene（第二场）的 Keyframe 选择、视频选择、Scene 成片全部保留；
         - 受影响 Scene 的 Scene 成片作废、最终装配计划作废（回改后必须重新装配）；
         - revision 单调前进，project.json 仍是唯一事实源。
覆盖领域规则：生产期脚本回改的即时计划重建、精确失效、历史产物保留、
Approval 前生产基线可回改。
"""

from __future__ import annotations

import json

import pytest
from conftest import Journey, mp4_bytes


@pytest.mark.oracle
def test_oracle_script_structural_edit_invalidates_precisely(
    journey, http_server, synthetic_provider
):
    # 让每个 Segment 视频提交产出可区分的确定性字节（内容寻址 Asset 的前提）。
    video_contents = [
        mp4_bytes(b"video-scene-a-shot-1"),
        mp4_bytes(b"video-scene-a-shot-2"),
        mp4_bytes(b"video-scene-b-shot-1"),
    ]
    http_server.providers.fl2va = synthetic_provider(
        media_type="video/mp4",
        content=mp4_bytes(b"fl2va"),
        duration_seconds=8,
        contents=video_contents,
        plugin_id="test.fl2va",
    )
    http_server.providers.ref2va = synthetic_provider(
        media_type="video/mp4",
        content=mp4_bytes(b"ref2va"),
        duration_seconds=8,
        contents=video_contents,
        plugin_id="test.ref2va",
    )

    # ARRIVE：双 Scene 生产到最终装配已选择；第一场含两个 Shot。
    journey.create_project(title="O4失效级联")
    journey.propose_references()
    journey.approve_references()
    character_id = journey.snapshot()["reference_library"]["characters"][0]["id"]
    first_scene = Journey.drama_scene(character_id, title="第一场")
    first_scene["shots"].append(json.loads(json.dumps(first_scene["shots"][0])))
    first_scene["segments"].append(
        {
            **json.loads(json.dumps(first_scene["segments"][0])),
            "shot_indexes": [1],
        }
    )
    journey.apply_script(
        scenes=[
            first_scene,
            Journey.drama_scene(character_id, title="第二场"),
        ]
    )
    journey.plan_narration_shots()
    journey.unlock_visual_production()
    journey.generate_keyframes()
    journey.generate_videos()
    journey.assemble_scene_finals()
    journey.assemble_final()

    before = journey.document()
    first, second = before["structured_director"]["director_script"]["scenes"]
    removed_shot_id = first["shots"][1]["id"]
    surviving_shot_id = first["shots"][0]["id"]
    removed_segment_id = next(
        segment["id"] for segment in first["segments"] if removed_shot_id in segment["shot_ids"]
    )
    before_generations = len(before["generations"])
    before_assets = len(before["assets"])
    before_revision = before["revision"]

    def shot_state(document: dict, shot_id: str) -> dict:
        structured = document["structured_director"]
        segment_ids = {
            segment["id"]
            for scene in structured["director_script"]["scenes"]
            for segment in scene["segments"]
            if shot_id in segment["shot_ids"]
        }
        keyframe_ids = {
            keyframe_id
            for binding in structured["keyframe_plan"]["segments"]
            if binding["segment_id"] in segment_ids
            for keyframe_id in (binding["start_keyframe_id"], binding["end_keyframe_id"])
            if keyframe_id is not None
        }
        return {
            "keyframes": {
                frame["id"]: frame["selected_asset_id"]
                for frame in structured["keyframe_plan"]["keyframes"]
                if frame["id"] in keyframe_ids
            },
            "videos": {
                item["segment_id"]: item["selected_asset_id"]
                for item in structured["video_plan"]["segments"]
                if item["segment_id"] in segment_ids
            },
        }

    def scene_final_dismissed(document: dict, scene_id: str) -> dict:
        return {
            generation["id"]: generation["dismissed"]
            for generation in document["generations"]
            if generation["kind"] == "scene_final_video" and generation["target_id"] == scene_id
        }

    removed_before = shot_state(before, removed_shot_id)
    surviving_before = shot_state(before, surviving_shot_id)
    second_before = shot_state(before, second["shots"][0]["id"])
    assert all(value is not None for value in removed_before["keyframes"].values())
    assert all(value is not None for value in surviving_before["keyframes"].values())
    assert all(value is not None for value in second_before["keyframes"].values())
    first_finals_before = scene_final_dismissed(before, first["id"])
    second_finals_before = scene_final_dismissed(before, second["id"])
    assert first_finals_before and all(not dismissed for dismissed in first_finals_before.values())
    assert second_finals_before and all(
        not dismissed for dismissed in second_finals_before.values()
    )

    # ARRIVE：真实 script revision 入口删除第一场的第二个 Shot。
    journey._command(
        "script.apply_operations",
        {
            "scope": {"scene_ids": [first["id"]]},
            "operations": [
                {
                    "op": "delete_segment",
                    "scene_id": first["id"],
                    "segment_id": removed_segment_id,
                },
                {"op": "delete_shot", "scene_id": first["id"], "shot_id": removed_shot_id},
            ],
        },
        role="agent",
        step="O4.delete_shot",
    )

    after = journey.document()
    structured = after["structured_director"]
    after_first = structured["director_script"]["scenes"][0]

    # ORACLE：脚本只剩幸存 Shot 与第二场，revision 前进。
    assert [shot["id"] for shot in after_first["shots"]] == [surviving_shot_id]
    assert [scene["id"] for scene in structured["director_script"]["scenes"]] == [
        first["id"],
        second["id"],
    ]
    assert after["revision"] > before_revision

    # ORACLE：被删 Shot 的槽位移除，历史 Asset/Generation 全部保留。
    surviving_after = shot_state(after, surviving_shot_id)
    assert surviving_after["keyframes"].keys().isdisjoint(removed_before["keyframes"].keys())
    assert surviving_after["videos"].keys().isdisjoint(removed_before["videos"].keys())
    assert len(after["generations"]) == before_generations
    assert len(after["assets"]) == before_assets

    # ORACLE：幸存 Shot 与未受影响 Scene 的选择精确保留。
    assert surviving_after["keyframes"] == surviving_before["keyframes"]
    assert surviving_after["videos"] == surviving_before["videos"]
    second_after = shot_state(after, second["shots"][0]["id"])
    assert second_after == second_before
    assert scene_final_dismissed(after, second["id"]) == second_finals_before

    # ARRIVE：脚本回改使生产基线过期，先按真实流程重新校准建立当前基线。
    journey.plan_narration_shots()

    # ORACLE：回改立即使最终装配计划作废，且受影响 Scene 的 Scene 成片在结构上过期
    # （dismissed 标记保留历史卡片，过期性由当前 Segment 视频派生判断）。
    assert structured["final_assembly"] is None
    error_status, error_body = journey._server.request(
        "POST",
        f"{journey.resource}/final/enter",
        {"expected_revision": journey._revision()},
        role="human",
    )
    assert error_status in (400, 409)
    listed = json.dumps(error_body, ensure_ascii=False)
    assert first["title"] in listed
    assert second["title"] not in listed

    # ORACLE：重新装配时按当前脚本精确重渲——受影响 Scene 出新的 Scene 成片
    # Generation，未受影响 Scene 的成片 Asset 按内容寻址复用（Asset 字节不变）。
    second_final_assets_before = {
        generation["language"]: generation["output_asset_id"]
        for generation in before["generations"]
        if generation["kind"] == "scene_final_video"
        and generation["target_id"] == second["id"]
        and not generation["dismissed"]
    }
    journey.assemble_scene_finals()
    journey.assemble_final()
    rebuilt = journey.document()
    assembly = rebuilt["structured_director"]["final_assembly"]
    clips = {clip["scene_id"]: clip for clip in assembly["clips"]}
    for language in ("zh", "en"):
        assert clips[second["id"]][f"{language}_asset_id"] == second_final_assets_before[language]
    new_first_finals = [
        generation
        for generation in rebuilt["generations"]
        if generation["kind"] == "scene_final_video"
        and generation["target_id"] == first["id"]
        and not generation["dismissed"]
        and generation["id"] not in first_finals_before
    ]
    # 受影响 Scene 中英两版都重新渲染。
    assert {generation["language"] for generation in new_first_finals} == {"zh", "en"}
    assert len(new_first_finals) == 2
    for generation in new_first_finals:
        assert (
            clips[first["id"]][f"{generation['language']}_asset_id"]
            == generation["output_asset_id"]
        )
