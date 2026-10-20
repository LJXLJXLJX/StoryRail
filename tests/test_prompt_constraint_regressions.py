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


def test_keyframe_contract_carries_location_decoupling_and_user_boundary():
    """地点图片不形成隐藏输入，且不得新增用户未要求的排除项。"""
    text = "\n".join(r["text"] for r in read_contract("keyframe")["resources"])
    for required in (
        "不会自动进入生图调用",
        "不得借机新增用户没有要求的排除项",
    ):
        assert required in text
    assert "environment_view_id" not in text


def test_keyframe_contract_treats_location_images_as_explicit_auxiliary_references():
    """地点图片只在用户显式加入辅助参考后才进入实际输入。"""
    skill = read_contract("keyframe")["resources"][0]["text"]
    for required in (
        "地点语义与图片",
        "显式放入 Segment 辅助参考",
        "不假设任何地点图片会自动作为生图输入",
    ):
        assert required in skill
    assert "地点视图的使用" not in skill


def test_script_skill_designs_shots_before_packing_them_into_segments():
    """先设计 Shot 列表，再按打包规则装进 Segment；长镜头与段内切镜都通过覆盖关系表达。"""
    resources = read_contract("script")["resources"]
    text = {item["name"]: item["text"] for item in resources}
    skill = text["SKILL.md"]
    for required in ("设计 Shot 列表", "打包成 Segment", "打包理由"):
        assert required in skill, required
    contract = text["references/script-contract.md"]
    for required in (
        "先设计 Shot 列表，再打包成 Segment",
        "一个 Segment 可以覆盖多个相邻 Shot",
        "一个 Shot 也可以跨多个相邻 Segment",
        "实验前每个 Segment 不超过 3 个",
        "需要精确构图控制的镜头独占 Segment",
        "`boundary_from_previous`",
        "初稿与回改都在 `reply_markdown` 简述打包理由",
    ):
        assert required in contract, required
    quality = " ".join(text["references/quality-gate.md"].split())
    for required in (
        "打包覆盖完整连续",
        "每个 Segment 预计不超过 15 秒",
        "段内切镜只用于同空间、同一节拍的紧密镜头组",
        "实验前每个 Segment 不超过 3 个",
        "精确构图控制",
        "打包理由已写入 `reply_markdown`",
    ):
        assert required in quality, required
    # 旧规则不能以任何措辞残留在契约资源里。
    combined = "\n".join(text.values())
    for stale in (
        "初次规划一个 Shot 只对应一个 Segment",
        "新规划的 Shot 恰好一个 Segment",
        "超过 15 秒软约束也不压缩或拆分",
        "一个 Shot 只有一个 Segment",
    ):
        assert stale not in combined, stale
    launcher = (
        Path(__file__).resolve().parents[1] / "integrations/agent_launcher/PROMPT.md"
    ).read_text()
    assert "exceeds_soft_duration_limit" in launcher
    assert "拆分 Segment 不改变 Shot 设计" in launcher
    assert "一个 Shot 只有一个 Segment" not in launcher


def test_video_contract_defers_long_segment_split_to_pre_generation_reminder():
    video = read_contract("video_prompt")["resources"][0]["text"]
    assert "exceeds_soft_duration_limit" in video
    assert "split_segment" in video
    assert "不擅自拆分，也不拒绝提交" in video
    launcher = (
        Path(__file__).resolve().parents[1] / "integrations/agent_launcher/PROMPT.md"
    ).read_text()
    assert "exceeds_soft_duration_limit" in launcher


def test_multi_shot_video_segments_are_in_video_contract_and_launcher():
    """视频提示词契约与启动器都描述多 Shot Segment 的切镜写法与软约束。"""
    video = read_contract("video_prompt")["resources"][0]["text"]
    launcher = (
        Path(__file__).resolve().parents[1] / "integrations/agent_launcher/PROMPT.md"
    ).read_text()
    for text in (video, launcher):
        for required in (
            "context.shots",
            "[Shot 1]",
            "[Shot 2] At MM:SS.mmm",
            "软约束",
            "切点漂移",
            "不超过 3 个",
            "<scenetrans>",
            "首尾 Picture",
            "boundary_from_previous",
        ):
            assert required in text, required
        assert "一个 Shot 只有一个 Segment" not in text


def test_script_contract_carries_single_visible_speaker_rule_per_shot():
    """段内切镜后开口约束按 Shot 计：每个 Shot 至多一个开口说话的可见角色。"""
    resources = read_contract("script")["resources"]
    names = [item["name"] for item in resources]
    assert "references/drama-scene-craft.md" in names
    craft = next(i["text"] for i in resources if i["name"] == "references/drama-scene-craft.md")
    assert "每个 Shot 里只有一个开口说话的可见人物" in craft
    assert "一个 Segment 里只有一个开口说话的可见人物" not in craft
    quality = " ".join(
        next(i["text"] for i in resources if i["name"] == "references/quality-gate.md").split()
    )
    assert "每个 Shot 至多一个开口说话的可见角色" in quality
    assert "每个 Segment 至多一个开口说话的可见角色" not in quality
    from core.model_providers.minimax_h3.prompt_context import skill_resources

    h3 = "\n".join(r["text"] for r in skill_resources())
    assert "on_screen=false" in h3


def test_script_contract_splits_each_long_dialogue_line_independently_of_segments():
    """15 秒约束必须直接作用于单条对白，不能被误写成只拆 Segment。"""
    resources = read_contract("script")["resources"]
    text = {item["name"]: item["text"] for item in resources}
    for name in (
        "SKILL.md",
        "references/script-contract.md",
        "references/drama-scene-craft.md",
        "references/quality-gate.md",
    ):
        assert "拆 Segment 不能代替拆长对白" in text[name], name
    contract = " ".join(text["references/script-contract.md"].split())
    for required in (
        "`DialogueLine` 自身有独立的 15 秒软上限",
        "任何一条 `dialogue_lines[].text` 本身预计超过 15 秒",
        "不删减、概括或改写原文",
        "使每条预计不超过 15 秒",
    ):
        assert required in contract, required


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


def test_location_contract_keeps_images_optional_and_decoupled_from_shots():
    """Location Planner 只规划可选独立图片，不给 Shot 或 Keyframe 建绑定。"""
    resources = read_contract("location")["resources"]
    text = {item["name"]: item["text"] for item in resources}
    skill = text["SKILL.md"]
    for required in (
        "图片不是“主图 → 视图”的树",
        "不要默认创建全景图",
        "Shot 不保存地点或图片引用",
    ):
        assert required in skill
    coverage = text["references/view-coverage.md"]
    for required in (
        "不是必须覆盖全部 Shot 的机位表",
        "不为每个 Shot 预建一张图",
        "全景图适合需要环视",
    ):
        assert required in coverage
    # 图片说明强制、全景取景子图独立，且规划本身不能删除。
    bible = text["references/location-bible.md"]
    assert "每张图片必须有强制 `description`" in bible
    assert "子图的字节和说明从此独立" in bible


def test_script_contract_requires_plan_coverage_and_duration_reconciliation():
    """最少切镜不能变成删内容：方案清单逐项落地、合计时长对账、删减必须在 reply_markdown 说明。"""
    resources = read_contract("script")["resources"]
    text = {item["name"]: item["text"] for item in resources}
    assert "列出方案清单" in text["SKILL.md"]
    assert "合并镜号只合并摄影，不删内容" in text["SKILL.md"]
    assert "没有删减时明确写“无删减”" in text["SKILL.md"]
    assert "任何一条对白本身按自然语速、语气和停顿预估超过 15 秒" in text["SKILL.md"]
    assert "dialogue_timing.exceeds_duration" not in text["SKILL.md"]
    quality = text["references/quality-gate.md"]
    assert "方案覆盖：方案清单逐项落到了具体 Segment 或 Shot" in quality
    assert "偏差超过约 30% 已在" in quality
    assert "model_constraint" in text["references/script-contract.md"]
    intent = text["references/cinematic-director-intent.md"]
    assert "最少切镜原则只约束剪辑点，不减少内容" in intent
