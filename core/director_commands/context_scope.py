"""共享的只读会话目标解析；仅定位上下文，不授予 mutation scope。"""

import re


def _relevant_scene_indexes(
    user_message: str,
    scenes: list[dict[str, object]],
    generations_value: object,
    recent_scene_ids_value: object = None,
) -> tuple[int, ...]:
    indexes: set[int] = set()
    for match in re.finditer(r"(?:scene|场景)\s*[-_#]?\s*0*(\d+)", user_message, re.IGNORECASE):
        ordinal = int(match.group(1))
        if 1 <= ordinal <= len(scenes):
            indexes.add(ordinal - 1)
    for match in re.finditer(r"第\s*0*(\d+)\s*个?\s*场景", user_message):
        ordinal = int(match.group(1))
        if 1 <= ordinal <= len(scenes):
            indexes.add(ordinal - 1)
    if scenes and re.search(
        r"(?:最后(?:一个|个)?|最末(?:一个|个)?)\s*(?:scene|场景)",
        user_message,
        re.IGNORECASE,
    ):
        indexes.add(len(scenes) - 1)
    lowered = user_message.casefold()
    mentioned_ids = set(re.findall(r"[0-9a-f]{32}", lowered))
    for index, scene in enumerate(scenes):
        title = scene.get("title")
        if isinstance(title, str) and title and title.casefold() in lowered:
            indexes.add(index)
        if mentioned_ids & _nested_ids(scene):
            indexes.add(index)
    if mentioned_ids and isinstance(generations_value, list):
        targets = {
            item.get("target_id")
            for item in generations_value
            if isinstance(item, dict) and item.get("id") in mentioned_ids
        }
        for index, scene in enumerate(scenes):
            if targets & _nested_ids(scene):
                indexes.add(index)
    continuation = bool(
        re.fullmatch(
            r"\s*(?:继续|接着|接着来|继续执行|开始吧|执行吧|就这样|按这个来|好|好的|可以)"
            r"[。！!，,\s]*",
            user_message,
            re.IGNORECASE,
        )
    )
    if not indexes and (
        continuation
        or re.search(
            r"(?:这个|该|当前|刚才(?:那个|的)?)\s*(?:scene|场景)",
            user_message,
            re.IGNORECASE,
        )
    ):
        recent_scene_ids = (
            {item for item in recent_scene_ids_value if isinstance(item, str)}
            if isinstance(recent_scene_ids_value, list)
            else set()
        )
        for index, scene in enumerate(scenes):
            if scene.get("id") in recent_scene_ids:
                indexes.add(index)
        if not indexes and len(scenes) == 1:
            indexes.add(0)
    return tuple(sorted(indexes))


def _nested_ids(value: object) -> set[str]:
    if isinstance(value, dict):
        result = {item for key, item in value.items() if key == "id" and isinstance(item, str)}
        for item in value.values():
            result.update(_nested_ids(item))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_nested_ids(item))
        return result
    return set()
