"""H3 提示词静态校验：对白唯一位置、官方对白标签、说话者与段落结构。"""

import pytest

from core.model_providers.minimax_h3.prompt_lint import lint_h3_prompt

REF2VA = "minimax_h3.ref2va"
LINE = "我不想继续这样的对话了。"
FACTS = {
    "duration_seconds": 5.0,
    "asset_labels": ["<Picture 1>", "<Picture 2>", "<Audio 1>"],
    "dialogue": [{"speaker": "Claude", "text": LINE, "audio_label": "<Audio 1>"}],
}
VALID = f"""subject_definitions:
<Subject 1> 是 <Picture 1> 中的 Claude，短发，深灰外套。
<Subject 2> 是 <Picture 1> 中站在门口的灰狼，厚毛，琥珀色眼睛。
<Audio 1> 是 <Subject 1> (S1) 的对白音频。
summary:
[keyframe completion + audio reuse] <Subject 1> 从 <Picture 1> 转身拒绝对话，停在 <Picture 2>。
retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - 外观与服装保持一致。
<Subject 2> (appears in [Shot 1]): fully_preserved - 毛色与体型保持一致。
<Audio 1>: partially_copy - 原信号放在 00:01.000 至 00:02.520 的对白时间窗内，其余声音另行生成。
detailed_description:
写实电影风格，室内暖光。
[Shot 1] 镜头从 <Picture 1> 开始，中景固定机位。<Subject 2> 压低身体发出低沉的非语言咆哮。\
<Subject 1> (S1) 侧过身，按 <Audio 1> 平静而坚定地说：<d>[Chinese]{LINE}</d> 随后双唇闭合，\
镜头缓慢推近并停在 <Picture 2>。
overall_soundscape:
室内空调低鸣，衣料摩擦声，灰狼低沉的喉音咆哮。除上述对白外无其它人类语音。
non_diegetic_music:
N/A"""


def problems(prompt, facts=FACTS, recipe=REF2VA):
    return lint_h3_prompt(recipe, prompt, facts)


def test_official_structure_with_single_dialogue_declaration_passes():
    assert problems(VALID) == []


def test_text_outside_sections_such_as_legacy_dialogue_mapping_is_rejected():
    found = problems(
        f"严格让角色说出参考音频的原始内容。\n<Audio 1> 对应原始对白：{LINE}\n\n{VALID}"
    )
    assert any("subject_definitions 之前不能有其它文字" in item for item in found)
    assert any("在 `<d>` 之外重复出现（段名之前）" in item for item in found)


@pytest.mark.parametrize(
    ("section", "old", "new"),
    [
        (
            "subject_definitions",
            "的对白音频。",
            f"的对白音频，内容为“{LINE}”",
        ),
        ("summary", "转身拒绝对话", f"转身说出“{LINE[:-1]}”"),
        ("overall_soundscape", "除上述对白外", f"除「{LINE}」外"),
    ],
)
def test_dialogue_text_repeated_in_other_sections_is_rejected(section, old, new):
    found = problems(VALID.replace(old, new, 1))
    assert any("之外重复出现" in item and section in item for item in found), found


def test_same_line_declared_twice_is_rejected():
    twice = VALID.replace(
        "随后双唇闭合", f"她停顿后 (S1) 又说：<d>[Chinese]{LINE}</d> 随后双唇闭合"
    )
    assert any("被 `<d>` 声明了 2 次" in item for item in problems(twice))


def test_missing_speaker_id_and_language_tag_are_rejected():
    no_speaker = VALID.replace("<Subject 1> (S1) 侧过身", "<Subject 1> 侧过身")
    assert any("缺少说话者 ID" in item for item in problems(no_speaker))
    no_tag = VALID.replace(f"<d>[Chinese]{LINE}", f"<d>{LINE}")
    assert any("必须以语言标签开头" in item for item in problems(no_tag))
    wrong = VALID.replace("<d>[Chinese]", "<d>[English]")
    assert any("语言标签 [English] 与台词语言不一致" in item for item in problems(wrong))


def test_dialogue_must_be_in_description_and_closed():
    moved = VALID.replace(
        "除上述对白外无其它人类语音。", f"(S1) 说 <d>[Chinese]{LINE}</d>"
    ).replace(f"<d>[Chinese]{LINE}</d> 随后", "随后", 1)
    assert any("不能出现在 overall_soundscape" in item for item in problems(moved))
    assert problems(VALID.replace("</d>", "", 1)) == ["存在没有闭合的 `<d>`。"]
    stray = VALID.replace("除上述对白外", "除 <d> 中的台词外")
    assert problems(stray)


def test_silent_characters_get_no_speaker_id_or_spoken_words():
    roar_with_id = VALID.replace("<Subject 2> 压低身体", "<Subject 2> (S2) 压低身体")
    assert any("没有台词的说话者 ID (S2)" in item for item in problems(roar_with_id))
    shouted = VALID.replace("发出低沉的非语言咆哮。", "(S2) 斥责：<d>[Chinese]快滚出去！</d>")
    assert any("「快滚出去！」不是本段对白" in item for item in problems(shouted))


def test_dialogue_audio_relationship_must_be_partial_copy_and_defined():
    referenced = VALID.replace("<Audio 1>: partially_copy", "<Audio 1>: reference")
    assert any("必须标为 `partially_copy`" in item for item in problems(referenced))
    invented = VALID.replace("<Audio 1>: partially_copy", "<Audio 1>: copied")
    assert any("<Audio 1> 的关系标记必须是" in item for item in problems(invented))
    with_id = VALID.replace("<Audio 1>: partially_copy -", "<Audio 1>: partially_copy - (S1)")
    assert any("retention_analysis 不写说话者 ID" in item for item in problems(with_id))
    undefined = VALID.replace("<Audio 1> 是 <Subject 1> (S1) 的对白音频。\n", "")
    assert any("必须单独定义对白音频 <Audio 1>" in item for item in problems(undefined))
    wrong_speaker = VALID.replace("<Subject 1> (S1) 的对白音频", "<Subject 1> (S2) 的对白音频")
    assert any("沿用这句对白的说话者 ID (S1)" in item for item in problems(wrong_speaker))
    no_reuse = VALID.replace("[keyframe completion + audio reuse]", "[keyframe completion]")
    assert any("必须包含 `audio reuse`" in item for item in problems(no_reuse))


def test_sections_labels_and_shot_timing_follow_official_format():
    reordered = VALID.replace("summary:\n", "summary_text:\n")
    assert any("按官方顺序各写一次" in item for item in problems(reordered))
    unknown = VALID.replace("停在 <Picture 2>。\noverall", "停在 <Picture 3>。\noverall")
    assert any("<Picture 3>" in item for item in problems(unknown))
    undefined_subject = VALID.replace("<Subject 2> 压低", "<Subject 3> 压低")
    assert any("缺少这些主体的定义行：<Subject 3>" in item for item in problems(undefined_subject))
    cut = VALID.replace("镜头缓慢推近", "[Shot 2] 镜头缓慢推近")
    assert any("[Shot 2] 后必须紧跟 `At MM:SS.mmm`" in item for item in problems(cut))
    late = VALID.replace("镜头缓慢推近", "[Shot 2] At 00:06.000, 镜头缓慢推近")
    assert any("早于视频结束" in item for item in problems(late))
    timed = VALID.replace("镜头缓慢推近", "[Shot 2] At 00:03.000, 镜头缓慢推近")
    assert problems(timed) == []


def test_line_split_across_cut_with_scenetrans_counts_once():
    split = VALID.replace(
        f"<d>[Chinese]{LINE}</d>",
        "<d>[Chinese]我不想继续 <scenetrans></d> [Shot 2] At 00:02.000, 声音延续到下一镜，"
        "<Subject 1> (S1) 接着说：<d>[Chinese]<scenetrans> 这样的对话了。</d>",
    )
    assert problems(split) == []


def test_non_dialogue_prompts_may_stay_free_form_but_cannot_invent_dialogue():
    facts = {"duration_seconds": 4.0, "asset_labels": ["<Picture 1>"], "dialogue": []}
    free = "<Picture 1> 中的站台空无一人，顶灯轻微闪烁，电流嗡鸣。"
    assert problems(free, facts, "minimax_h3.fl2va") == []
    spoken = free + "女人 (S1) 说：<d>[Chinese] 有人吗？</d>"
    assert any("不是本段对白" in item for item in problems(spoken, facts, "minimax_h3.fl2va"))
    base = (
        "integrated_multimodal_description: [Shot 1] 站台空无一人。\noverall_soundscape: 电流嗡鸣。"
    )
    assert any("按官方顺序各写一次" in item for item in problems(base, facts, "minimax_h3.fl2va"))


def test_base_mode_allows_official_alignment_sentence_but_ref2va_does_not():
    facts = {
        "duration_seconds": 9.0,
        "asset_labels": ["<Picture 1>", "<Picture 2>"],
        "dialogue": [],
    }
    body = (
        "integrated_multimodal_description: [Shot 1] 站台空无一人，镜头缓慢推近。\n"
        "overall_soundscape: 电流嗡鸣。\nnon_diegetic_music: N/A"
    )
    aligned = (
        "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns "
        "with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the "
        "9.00-second mark of the target video.\n\n" + body
    )
    assert problems(aligned, facts, "minimax_h3.fl2va") == []
    extra = "严格让角色说出参考音频的原始内容。\n\n" + body
    assert any("之前不能有其它文字" in item for item in problems(extra, facts, "minimax_h3.fl2va"))
    assert any("之前不能有其它文字" in item for item in problems("说明。\n" + VALID))
