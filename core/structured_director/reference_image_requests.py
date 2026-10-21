"""无时间位置视频参考图片的实际生图输入与提示词编译。"""

from .image_inputs import ImageInput, ordered_image_inputs
from .keyframe_requests import keyframe_character_look
from .models import GenerationOperation, Keyframe


def reference_image_owner(document, image_id):
    for video in () if document.video_plan is None else document.video_plan.segments:
        for image in video.reference_images:
            if image.id == image_id:
                return video, image
    raise ValueError("其他图片计划不存在。")


def reference_image_inputs(document, video, image):
    frame = Keyframe(
        image.id,
        video.segment_id,
        None,
        image.prompt_text,
        image.visible_character_ids,
        character_references=image.character_references,
    )
    characters = {item.id: item for item in document.reference_library.characters}
    entries = []
    for character_id in image.visible_character_ids:
        character = characters[character_id]
        look = keyframe_character_look(frame, character)
        if look is not None:
            entries.append(
                ImageInput(
                    look.selected_asset_id,
                    "角色造型",
                    f"角色「{character.name}」的造型「{look.name}」已选图。",
                )
            )
    entries.extend(
        ImageInput(asset_id, "辅助参考", "用户为该图片显式选择的辅助参考。")
        for asset_id in image.reference_asset_ids
    )
    return ordered_image_inputs(
        document, entries, operation=GenerationOperation.GENERATE, label="其他图片的生图输入"
    )


def reference_image_prompt(document, image, inputs, style):
    if not image.prompt_text.strip():
        raise ValueError("请先规划或填写这张其他图片的画面正文。")
    prompt = inputs.validate_prompt(image.prompt_text, style)
    return prompt + (
        f"\n\n项目画幅：{document.aspect_ratio.value}。" if style.aspect_ratio_in_prompt else ""
    )
