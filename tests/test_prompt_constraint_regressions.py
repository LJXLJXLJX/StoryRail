"""专业契约输入的回归；输入契约回归不冒充模型服从性评估。"""

from pathlib import Path

from core.director_proposals.professional_contracts import read_contract


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


def test_script_contract_keeps_external_speakers_and_planned_music():
    """龙套台词不能因没有引用卡而丢失；导演方案写明的配乐不能被当成未经要求的 BGM。"""
    resources = read_contract("script")["resources"]
    contract = next(i["text"] for i in resources if i["name"] == "references/script-contract.md")
    assert "写 `character_id: null` 与 `speaker_label`" in contract
    assert "不要删掉，也不要挪进 `audio_direction`" in contract
    assert "导演方案或用户明确写出的配乐、音乐入点就是明确要求" in contract
    assert "也不要写“无背景音乐”去否定方案" in contract
    script = next(i["text"] for i in resources if i["name"] == "SKILL.md")
    assert "对白写 `character_id: null` 加 `speaker_label`" in script


def test_script_contract_requires_plan_coverage_and_duration_reconciliation():
    """最少切镜不能变成删内容：方案清单逐项落地、合计时长对账、删减必须在 reply_markdown 说明。"""
    resources = read_contract("script")["resources"]
    text = {item["name"]: item["text"] for item in resources}
    assert "列出方案清单" in text["SKILL.md"]
    assert "合并镜号只合并摄影，不删内容" in text["SKILL.md"]
    assert "没有删减时明确写“无删减”" in text["SKILL.md"]
    assert "dialogue_timing.exceeds_duration" in text["SKILL.md"]
    quality = text["references/quality-gate.md"]
    assert "方案覆盖：方案清单逐项落到了具体 Segment 或 Shot" in quality
    assert "偏差超过约 30% 已在" in quality
    intent = text["references/cinematic-director-intent.md"]
    assert "最少切镜原则只约束剪辑点，不减少内容" in intent
