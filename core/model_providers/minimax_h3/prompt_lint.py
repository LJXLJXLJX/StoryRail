"""按官方 H3 Prompt 结构静态检查视频提示词；只报告问题，不改写正文、不阻止生成。

Core 在构造工作集时给出领域事实（时长、实际输入标签、本段对白及其 Audio 标签），本模块据此检查：
对白只在描述段以 ``(Sx) … <d>[Language] 原台词</d>`` 出现一次、其它段不重复台词原文、
无台词的声音不分配说话者 ID，以及段落顺序、引用标签、复用关系标记与切镜时间语法。
"""

from __future__ import annotations

import re
from collections import Counter

REF2VA_SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
BASE_SECTIONS = ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
_SECTION_NAMES = "|".join(sorted({*REF2VA_SECTIONS, *BASE_SECTIONS}))
_HEADER = re.compile(rf"^({_SECTION_NAMES}):", re.MULTILINE)
_D_TAG = re.compile(r"</?d>")
_ALIGNMENT = re.compile(
    r"(How the reference pictures align with the target video —"
    r"|For the target video, at [\d.]+ seconds into the target video,)[^\n]*"
)
_LANGUAGE = re.compile(r"^\s*\[([A-Za-z][A-Za-z ]*)\]")
_SPEAKER = re.compile(r"\((S\d+(?:\s*,\s*S\d+)*)\)")
_ASSET_LABEL = re.compile(r"<(?:Picture|Audio|Video) \d+>")
_LABEL_LINE = re.compile(r"^\s*(<(?:Subject|Picture|Video|Audio) \d+>)", re.MULTILINE)
_SHOT = re.compile(r"\[Shot (\d+)\]")
_CUT_TIME = re.compile(r"\s*At (\d{2}):(\d{2}\.\d{3})\b")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_CONTINUITY = re.compile(r"<scenetrans>|<cutoff>")
_VISUAL_MARKERS = {"fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference"}
_AUDIO_MARKERS = {"fully_copy", "partially_copy", "reference", "weak_reference"}
_TASK_TYPES = {
    "keyframe completion",
    "reference generation",
    "video editing",
    "video continuation",
    "audio reuse",
    "audio reference",
}
# 规范化后少于此长度的台词不做跨段原文检查，避免“好”“嗯”之类误报。
_MIN_REPEAT_CHARS = 4


def _norm(text: str) -> str:
    return "".join(char for char in _CONTINUITY.sub("", text).casefold() if char.isalnum())


def _quote(text: str, limit: int = 40) -> str:
    text = " ".join(text.split())
    return f"「{text if len(text) <= limit else text[:limit] + '…'}」"


def lint_h3_prompt(recipe_id: str, prompt: str, facts: dict) -> list[str]:
    """返回中文问题列表；空列表表示通过。

    ``facts``：``duration_seconds``、``asset_labels``（实际 Picture/Audio/Video 标签）与
    ``dialogue``（``[{speaker, text, audio_label}]``，按剧本顺序；无对白为空列表）。
    """
    ref2va = recipe_id.endswith(".ref2va")
    expected = REF2VA_SECTIONS if ref2va else BASE_SECTIONS
    description = expected[3] if ref2va else expected[0]
    dialogue = list(facts["dialogue"])
    problems: list[str] = []

    headers = list(_HEADER.finditer(prompt))
    structured = bool(headers) or bool(dialogue)
    sections: dict[str, tuple[int, int]] = {}
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(prompt)
        sections.setdefault(match.group(1), (match.end(), end))

    def section_text(name: str) -> str:
        start, end = sections.get(name, (0, 0))
        return prompt[start:end]

    def section_at(offset: int) -> str | None:
        return next((name for name, (s, e) in sections.items() if s <= offset < e), None)

    if structured:
        names = [match.group(1) for match in headers]
        if names != list(expected):
            problems.append(
                f"提示词必须按官方顺序各写一次这些段：{'、'.join(expected)}"
                f"（段名单独位于行首并紧跟冒号）；当前为：{'、'.join(names) or '无'}。"
            )
        preamble = prompt[: headers[0].start()].strip() if headers else ""
        # Base 模式的官方格式允许在三段前写一句首尾帧对齐说明；Ref2VA 六段前不允许任何文字。
        if preamble and (ref2va or not _ALIGNMENT.fullmatch(preamble)):
            problems.append(
                f"{headers[0].group(1)} 之前不能有其它文字；"
                "对白映射、额外指令等都必须写进官方段内。"
            )

    # —— <d> 块解析 ——
    blocks: list[tuple[int, int, str]] = []
    opened: int | None = None
    for match in _D_TAG.finditer(prompt):
        if match.group() == "<d>":
            if opened is not None:
                problems.append("`<d>` 不能嵌套，每个 `<d>` 都要先用 `</d>` 闭合。")
                return problems
            opened = match.end()
        else:
            if opened is None:
                problems.append("存在没有对应 `<d>` 的 `</d>`。")
                return problems
            blocks.append((opened - 3, match.end(), prompt[opened : match.start()]))
            opened = None
    if opened is not None:
        problems.append("存在没有闭合的 `<d>`。")
        return problems

    shot_starts = [match.start() for match in _SHOT.finditer(prompt)]
    utterances: list[dict] = []
    previous_end = 0
    for start, end, inner in blocks:
        located = section_at(start)
        if structured and located is not None and located != description:
            problems.append(
                f"台词 `<d>` 只能写在 {description}，不能出现在 {located}：{_quote(inner)}。"
            )
        language = _LANGUAGE.match(inner)
        if language is None:
            problems.append(
                f"`<d>` 必须以语言标签开头，例如 `<d>[Chinese] …</d>`：{_quote(inner)}。"
            )
        spoken = inner[language.end() :] if language else inner
        if language is not None:
            tag, has_cjk = language.group(1).strip(), bool(_CJK.search(spoken))
            if (tag == "Chinese") != has_cjk and tag in {"Chinese", "English"}:
                problems.append(f"`<d>` 的语言标签 [{tag}] 与台词语言不一致：{_quote(inner)}。")
        window_start = max(
            [previous_end, prompt.rfind("\n", 0, start) + 1]
            + [offset for offset in shot_starts if offset < start]
            + [s for s, _ in sections.values() if s <= start]
        )
        window = prompt[window_start:start]
        speakers = _SPEAKER.findall(window)
        ids = tuple(item.strip() for item in speakers[-1].split(",")) if speakers else ()
        if not ids and (dialogue or not _ASSET_LABEL.search(window)):
            problems.append(
                "`<d>` 前的同一句中缺少说话者 ID `(Sx)`；说话方式可自由描述，例如 "
                f"`角色 (S1) 在画外低声问：<d>[Chinese] …</d>`："
                f"{_quote(inner)}。"
            )
        previous_end = end
        if utterances and utterances[-1]["open"]:
            utterances[-1]["text"] += spoken
            utterances[-1]["open"] = spoken.rstrip().endswith("<scenetrans>")
        else:
            utterances.append(
                {"text": spoken, "ids": ids, "open": spoken.rstrip().endswith("<scenetrans>")}
            )

    # —— 台词唯一性 ——
    actual = Counter(_norm(item["text"]) for item in utterances)
    wanted = Counter(_norm(line["text"]) for line in dialogue)
    shown = {_norm(item["text"]): item["text"] for item in utterances}
    shown.update({_norm(line["text"]): line["text"] for line in dialogue})
    for key, count in wanted.items():
        if actual[key] < count:
            problems.append(
                f"对白{_quote(shown[key])}必须在 {description} 中以 "
                "`说话者 (Sx) … <d>[语言] 原台词</d>` 逐字写出。"
            )
    for key, count in actual.items():
        if key and count > max(wanted[key], 1):
            problems.append(
                f"台词{_quote(shown[key])}被 `<d>` 声明了 {count} 次；每句台词只能写一次。"
            )
    for key in actual:
        if key and key not in wanted:
            problems.append(
                f"`<d>` 中的{_quote(shown[key])}不是本段对白；无对白角色的喊叫、斥责等声音写成"
                "非语言音效，不写成台词。"
            )
    # 把 <d> 块抹成空白后按段检查，台词原文只允许留在 <d> 中。
    masked = list(prompt)
    for start, end, _inner in blocks:
        masked[start:end] = " " * (end - start)
    outside = "".join(masked)
    regions = {"段名之前": (0, headers[0].start() if headers else len(prompt)), **sections}
    for key in sorted({*actual, *wanted}):
        if len(key) < _MIN_REPEAT_CHARS:
            continue
        where = [name for name, (s, e) in regions.items() if key in _norm(outside[s:e])]
        if where:
            problems.append(
                f"台词{_quote(shown[key])}在 `<d>` 之外重复出现（{'、'.join(where)}）；"
                "其它位置只能用 `<Audio N>` 或说话者 ID 指代这句对白，不能再写台词原文。"
            )

    # —— 说话者 ID ——
    by_text = {_norm(item["text"]): item["ids"] for item in utterances}
    speaker_ids: dict[str, set[str]] = {}
    line_ids: dict[int, tuple[str, ...]] = {}
    for index, line in enumerate(dialogue):
        ids = by_text.get(_norm(line["text"]), ())
        line_ids[index] = ids
        speaker_ids.setdefault(line["speaker"], set()).update(ids)
    for speaker, ids in speaker_ids.items():
        if len(ids) > 1:
            problems.append(f"说话者 {speaker} 的台词使用了多个 ID：{'、'.join(sorted(ids))}。")
    owners: dict[str, set[str]] = {}
    for speaker, ids in speaker_ids.items():
        for item in ids:
            owners.setdefault(item, set()).add(speaker)
    for item, speakers in sorted(owners.items()):
        if len(speakers) > 1:
            problems.append(
                f"({item}) 同时被 {'、'.join(sorted(speakers))} 使用；不同说话者需要不同 ID。"
            )
    used = {item for utterance in utterances for item in utterance["ids"]}
    declared = {item.strip() for group in _SPEAKER.findall(prompt) for item in group.split(",")}
    unused = sorted(declared - used)
    if unused:
        problems.append(
            f"出现了没有台词的说话者 ID {'、'.join(f'({item})' for item in unused)}；"
            "不说台词的角色只写非语言音效，不分配 (Sx)。"
        )

    # —— 引用标签 ——
    allowed = set(facts["asset_labels"])
    unknown = sorted(set(_ASSET_LABEL.findall(prompt)) - allowed)
    if unknown:
        problems.append(f"引用了本次提交没有的输入标签：{'、'.join(unknown)}。")

    if structured and ref2va:
        problems.extend(_ref2va_problems(prompt, section_text, dialogue, line_ids))
    if structured:
        problems.extend(_shot_problems(section_text(description), description, facts))
    return problems


def _ref2va_problems(prompt, section_text, dialogue, line_ids):
    problems = []
    definitions_text = section_text("subject_definitions")
    retention_text = section_text("retention_analysis")
    defined = set(_LABEL_LINE.findall(definitions_text))
    used_subjects = set(re.findall(r"<Subject \d+>", prompt))
    missing = sorted(used_subjects - defined)
    if missing:
        problems.append(f"subject_definitions 缺少这些主体的定义行：{'、'.join(missing)}。")
    if _SPEAKER.search(retention_text):
        problems.append("retention_analysis 不写说话者 ID (Sx)。")
    markers = {}
    for line in retention_text.splitlines():
        found = _LABEL_LINE.match(line)
        if found is None:
            continue
        label = found.group(1)
        marker = re.search(r":\s*([a-z_]+)", line[found.end() :])
        value = marker.group(1) if marker else None
        markers[label] = value
        allowed = _AUDIO_MARKERS if label.startswith("<Audio") else _VISUAL_MARKERS
        if value not in allowed:
            problems.append(
                f"retention_analysis 中 {label} 的关系标记必须是 "
                f"{'、'.join(sorted(allowed))} 之一。"
            )
    for label in sorted(defined - set(markers)):
        problems.append(f"retention_analysis 缺少 {label} 的复用关系行。")
    summary = section_text("summary").strip()
    prefix = re.match(r"\[([^\]]+)\]", summary)
    types = [item.strip() for item in prefix.group(1).split("+")] if prefix else []
    if (
        not prefix
        or any(item not in _TASK_TYPES for item in types)
        or len(types) != len(set(types))
    ):
        problems.append(
            "summary 必须以方括号任务类型开头，例如 `[keyframe completion + audio reuse]`，"
            f"类型只能取 {'、'.join(sorted(_TASK_TYPES))} 且不重复。"
        )
    audio_labels = [line.get("audio_label") for line in dialogue if line.get("audio_label")]
    if audio_labels and prefix and "audio reuse" not in types:
        problems.append("对白音频按原信号复用，summary 的任务类型必须包含 `audio reuse`。")
    definition_lines = {
        found.group(1): line
        for line in definitions_text.splitlines()
        if (found := _LABEL_LINE.match(line)) is not None
    }
    for index, line in enumerate(dialogue):
        label = line.get("audio_label")
        if not label:
            continue
        if label not in definition_lines:
            problems.append(
                f"subject_definitions 必须单独定义对白音频 {label}，并写明它属于哪个说话者 (Sx)。"
            )
        else:
            ids = set(line_ids.get(index, ()))
            declared = {
                item.strip()
                for group in _SPEAKER.findall(definition_lines[label])
                for item in group.split(",")
            }
            if ids and not ids <= declared:
                problems.append(
                    f"subject_definitions 中 {label} 的定义必须沿用这句对白的说话者 ID "
                    f"{'、'.join(f'({item})' for item in sorted(ids))}。"
                )
        if markers.get(label) not in (None, "partially_copy"):
            problems.append(
                f"对白音频 {label} 在目标视频中按原信号放在自己的时间窗内、其余声音另行生成，"
                "retention_analysis 必须标为 `partially_copy`。"
            )
    return problems


def _shot_problems(text, description, facts):
    problems = []
    first_seen: list[tuple[int, int]] = []
    seen: set[int] = set()
    for match in _SHOT.finditer(text):
        number = int(match.group(1))
        if number not in seen:
            seen.add(number)
            first_seen.append((number, match.end()))
    if not first_seen:
        return [f"{description} 必须以 `[Shot 1]` 开始逐镜描述。"]
    numbers = [number for number, _ in first_seen]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"{description} 的镜头编号必须从 [Shot 1] 起连续递增。")
    previous = 0.0
    duration = facts["duration_seconds"]
    for number, end in first_seen:
        cut = _CUT_TIME.match(text, end)
        if number == 1:
            if cut is not None:
                problems.append("[Shot 1] 是开场镜头，不写切镜时间。")
            continue
        if cut is None:
            problems.append(f"[Shot {number}] 后必须紧跟 `At MM:SS.mmm` 切镜时间。")
            continue
        seconds = int(cut.group(1)) * 60 + float(cut.group(2))
        if not previous < seconds < duration:
            problems.append(
                f"[Shot {number}] 的切镜时间 {cut.group(1)}:{cut.group(2)} 必须晚于上一切点且早于"
                f"视频结束 {duration:.3f} 秒。"
            )
        previous = max(previous, seconds)
    return problems
