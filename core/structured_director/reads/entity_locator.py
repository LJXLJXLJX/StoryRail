"""把写入冲突涉及的实体键翻译成人和 Agent 都能直接定位的描述。"""

from __future__ import annotations

from ..change_journal import PROJECT_KEY

_LIMIT = 20


def describe_entities(document, keys, *, limit: int = _LIMIT) -> tuple[dict[str, str], ...]:
    """按稳定顺序返回至多 ``limit`` 个 ``{id, kind, locator}``；已删除的实体标为 ``deleted``。"""
    index = _locator_index(document)
    ordered = sorted(keys, key=lambda key: (key != PROJECT_KEY, key not in index, key))
    result = []
    for key in ordered[:limit]:
        kind, locator = index.get(key, ("deleted", "已删除或尚未出现在当前项目中的对象"))
        result.append({"id": key, "kind": kind, "locator": locator})
    return tuple(result)


def _locator_index(document) -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {
        PROJECT_KEY: ("project", "项目级字段（阶段、内容层、标题、导演方案、Scene 顺序等）")
    }
    segment_names: dict[str, str] = {}
    script = document.director_script
    if script is not None:
        for scene_number, scene in enumerate(script.scenes, 1):
            scene_name = f"场景 {scene_number}"
            index[scene.id] = ("scene", scene_name)
            for number, shot in enumerate(scene.shots, 1):
                index[shot.id] = ("shot", f"{scene_name}－镜头 {number}")
            for number, segment in enumerate(scene.segments, 1):
                name = f"{scene_name}－片段 {number}"
                segment_names[segment.id] = name
                index[segment.id] = ("segment", name)
                for line_number, line in enumerate(segment.dialogue_lines, 1):
                    index[line.id] = ("dialogue_line", f"{name} 对白 {line_number}")
            for number, cue in enumerate(scene.narration_cues, 1):
                index[cue.id] = ("narration_cue", f"{scene_name} 旁白 {number}")
    plan = document.keyframe_plan
    if plan is not None:
        slots: dict[str, list[str]] = {}
        for binding in plan.segments:
            name = segment_names.get(binding.segment_id, "未知片段")
            slots.setdefault(binding.start_keyframe_id, []).append(f"{name} 首帧")
            slots.setdefault(binding.end_keyframe_id, []).append(f"{name} 尾帧")
        for keyframe in plan.keyframes:
            index[keyframe.id] = ("keyframe", " / ".join(slots.get(keyframe.id, ["Keyframe"])))
    if document.video_plan is not None:
        for video in document.video_plan.segments:
            name = segment_names.get(video.segment_id, "未知片段")
            for image in video.reference_images:
                index[image.id] = (
                    "video_reference_image",
                    f"{name} 其他图片 {image.slot_index + 1}",
                )
    for character in document.reference_library.characters:
        index[character.id] = ("character", f"角色「{character.name}」")
        for look in character.looks:
            index[look.id] = ("look", f"角色「{character.name}」造型「{look.name}」")
    narrator = document.reference_library.narrator
    if narrator is not None:
        index[narrator.id] = ("narrator", f"旁白身份「{narrator.name}」")
    for location in document.location_library.locations:
        index[location.id] = ("location", f"地点「{location.name}」")
        for fixture in location.fixtures:
            index[fixture.id] = (
                "location_fixture",
                f"地点「{location.name}」陈设「{fixture.name}」",
            )
        for state in location.states:
            index[state.id] = ("location_state", f"地点「{location.name}」状态「{state.name}」")
        for image in location.images:
            index[image.id] = ("location_image", f"地点「{location.name}」图片「{image.name}」")
    for generation in document.generations:
        target = index.get(generation.target_id, (None, "其它对象"))[1]
        index[generation.id] = ("generation", f"{target} 的 {generation.kind.value} 任务")
    for asset in document.assets:
        index.setdefault(asset.id, ("asset", "媒体 Asset"))
    for run in document.director_runs:
        index[run.id] = ("director_run", f"{run.kind.value} 任务")
    return index
