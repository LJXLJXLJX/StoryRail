"""冻结真实输出的缺陷复现；输入契约回归不冒充模型服从性评估。"""

import json
import re
from pathlib import Path

from core.director_proposals.professional_contracts import read_contract


def historical(case):
    path = Path(__file__).parent / "fixtures/prompt_contracts/historical" / f"{case}.json"
    return json.loads(path.read_text())["prompt_text"]


def test_frozen_kimi_failures_remain_explicit():
    internal = historical("ref2va-builtin")
    external = historical("ref2va-external")
    for text in (internal, external):
        assert "subject_definitions:" in text
        assert not re.search(r"<Subject \d+>", text)
    detail = internal.split("detailed_description:")[1].split("overall_soundscape:")[0]
    assert "The shot starts exactly" in detail  # 中文要求下仍输出英文正文。
    assert "00:03.000" in detail
    assert not re.search(r"\d{2}:\d{2}\.\d{3}", external)
    for case in ("fl2va-external", "keyframe-external"):
        text = historical(case)
        assert "字幕" not in text and "水印" not in text
    # Base 固定英文锚句/字段不是语言缺陷；外部 FL2VA 时间对齐事实上存在。
    base = historical("fl2va-external")
    assert "0.00-second" in base and "3.00-second" in base


def test_external_and_inline_skill_deliver_same_constraint_resolution():
    from core.model_providers.minimax_h3.prompt_context import skill_resources

    contract = {"resources": skill_resources()}
    skill = next(r["text"] for r in contract["resources"] if r["name"] == "SKILL.md")
    assert "allowed_asset_reference_labels" in skill
    assert "Subject" in skill and "不是新的图片输入" in skill
    assert "MM:SS.mmm" in skill and "未要求的排除项不自动新增" in skill
    keyframe = read_contract("keyframe")["resources"][0]["text"]
    assert "正文约束复核" in keyframe and "无字幕、无水印" in keyframe


def test_keyframe_contract_carries_frame_prompting_laws():
    """真实生产反馈落地为契约：地点视图默认作为底图与正文分工、三层空间、光学具象化、年代锚定与不露脸防御。"""
    text = "\n".join(r["text"] for r in read_contract("keyframe")["resources"])
    for required in (
        "三项都写 null",
        "不因为景别是中近景、特写就退出",
        "不重述视图里已有的固定陈设",
        "正反打背景",
        "只描述一个绝对静止的物理切片",
        "不要用 20~30 字的抽象名词罗列代替画面设计",
        "不得借机新增用户没有要求的排除项",
        "瞳孔急剧收缩",
    ):
        assert required in text
    # 旧说法与新规则不能并存，防止参考文件回退。
    assert "少用精确焦段数字" not in text
    assert "默认不使用环境参考" not in text
    assert "不自动成为 Keyframe 的输入" not in text


def test_script_contract_frontloads_cinematic_director_intent():
    resources = read_contract("script")["resources"]
    intent = next(
        item["text"]
        for item in resources
        if item["name"] == "references/cinematic-director-intent.md"
    )
    script = next(item["text"] for item in resources if item["name"] == "SKILL.md")
    quality = next(
        item["text"] for item in resources if item["name"] == "references/quality-gate.md"
    )
    assert "镜头功能、第一视觉重心、空间调度、连续性锚点" in script
    for required in (
        "观众第一眼必须看见什么",
        "人物、道具和环境在前景、中景、背景中的空间关系",
        "起点、关键变化和落点",
        "不能让 Keyframe Planner",
    ):
        assert required in intent
    assert "必要揭示" in quality
    assert "H3 Provider 字段" in quality


def test_initial_planning_keeps_one_segment_per_shot_and_defers_split_to_video_reminder():
    script = "\n".join(item["text"] for item in read_contract("script")["resources"])
    assert "初次规划一个 Shot 只对应一个 Segment" in script
    assert "超过 15 秒软约束也不压缩或拆分" in script
    # 旧的预拆分说法不能与新规则并存。
    assert "再将过长 Shot 拆成 Segment" not in script
    assert "普通 Shot 只返回一个" not in script
    assert "是则用 Segment" not in script
    video = read_contract("video_prompt")["resources"][0]["text"]
    assert "exceeds_soft_duration_limit" in video
    assert "split_segment" in video
    assert "不擅自拆分，也不拒绝提交" in video
    launcher = (
        Path(__file__).resolve().parents[1] / "integrations/agent_launcher/PROMPT.md"
    ).read_text()
    assert "exceeds_soft_duration_limit" in launcher
    assert "一个 Shot 只有一个 Segment" in launcher


def test_script_contract_carries_drama_scene_craft():
    """剧情戏情绪方法论：整场设计、可见杠杆、倾听者覆盖与 AI 对白边界都进入脚本契约。"""
    resources = read_contract("script")["resources"]
    names = [item["name"] for item in resources]
    assert "references/drama-scene-craft.md" in names
    craft = next(i["text"] for i in resources if i["name"] == "references/drama-scene-craft.md")
    for required in (
        "这场戏是谁的",
        "转折拍在哪里",
        "全场只有一个“最重的镜头”",
        "台词的情绪落在听者脸上",
        "一个 Segment 里只有一个开口说话的可见人物",
        "中文约每秒 4–5 字",
    ):
        assert required in craft
    script = next(i["text"] for i in resources if i["name"] == "SKILL.md")
    assert "drama Scene 先做整场设计" in script
    quality = next(i["text"] for i in resources if i["name"] == "references/quality-gate.md")
    assert "每个 Segment 至多一个开口说话的可见角色" in quality
    intent = next(
        i["text"] for i in resources if i["name"] == "references/cinematic-director-intent.md"
    )
    assert "剧情戏中情绪焦点换到另一个人脸上" in intent
    from core.model_providers.minimax_h3.prompt_context import skill_resources

    h3 = "\n".join(r["text"] for r in skill_resources())
    assert "on_screen=false" in h3
