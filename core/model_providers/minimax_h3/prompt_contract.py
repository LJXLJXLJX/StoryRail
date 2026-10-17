from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class H3PromptMode(StrEnum):
    I2VA = "i2va"
    L2VA = "l2va"
    FL2VA = "fl2va"
    REF2VA = "ref2va"


@dataclass(frozen=True, slots=True)
class H3DialogueInput:
    character_name: str
    text: str
    delivery: str | None
    # 说话者是否在本 Shot 可见；False 表示画外台词，落在可见听者的镜头上。
    on_screen: bool


@dataclass(frozen=True, slots=True)
class H3PromptContext:
    mode: H3PromptMode
    duration_seconds: float
    aspect_ratio: str
    scene_title: str
    scene_setting: str
    shot_composition: str
    camera_movement: str
    shot_action: str
    segment_action: str
    historical_prompt: str
    user_direction: str
    audio_direction: str
    start_frame_description: str | None
    end_frame_description: str | None
    dialogue: tuple[H3DialogueInput, ...]
    additional_image_descriptions: tuple[str, ...] = ()
    audio_reference_descriptions: tuple[str, ...] = ()
    video_reference_descriptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.aspect_ratio not in {"16:9", "9:16", "2:1"}:
            raise ValueError("H3 prompt 画面比例不合法。")
        if not isfinite(self.duration_seconds) or self.duration_seconds < 0.2:
            raise ValueError("H3 prompt 时长不合法。")
        required = (
            self.scene_title,
            self.scene_setting,
            self.shot_composition,
            self.camera_movement,
            self.shot_action,
            self.segment_action,
            self.audio_direction,
        )
        if any(not item.strip() or len(item) > 10_000 for item in required):
            raise ValueError("H3 prompt 上下文不完整或过长。")
        if not isinstance(self.historical_prompt, str) or len(self.historical_prompt) > 10_000:
            raise ValueError("H3 历史提示词不合法或过长。")
        if not isinstance(self.user_direction, str) or len(self.user_direction) > 10_000:
            raise ValueError("H3 prompt 用户创作方向不合法或过长。")
        if self.mode is H3PromptMode.I2VA and self.start_frame_description is None:
            raise ValueError("I2VA 必须提供首帧描述。")
        if self.mode is H3PromptMode.L2VA and self.end_frame_description is None:
            raise ValueError("L2VA 必须提供尾帧描述。")
        if self.mode is H3PromptMode.FL2VA and (
            self.start_frame_description is None or self.end_frame_description is None
        ):
            raise ValueError("FL2VA 必须提供首尾帧描述。")
        if len(self.additional_image_descriptions) > 4 or any(
            not item.strip() or len(item) > 2_000 for item in self.additional_image_descriptions
        ):
            raise ValueError("Ref2VA 附加图片描述不能为空、超过 2000 字或多于 4 项。")
        if self.additional_image_descriptions and self.mode is not H3PromptMode.REF2VA:
            raise ValueError("附加图片描述只适用于 Ref2VA。")
        if len(self.audio_reference_descriptions) > 8 or any(
            not item.strip() or len(item) > 2_000 for item in self.audio_reference_descriptions
        ):
            raise ValueError("Ref2VA 参考音频描述不能为空、超过 2000 字或多于 8 项。")
        if self.audio_reference_descriptions and self.mode is not H3PromptMode.REF2VA:
            raise ValueError("参考音频只适用于 Ref2VA。")
        if len(self.video_reference_descriptions) > 3 or any(
            not item.strip() or len(item) > 2_000 for item in self.video_reference_descriptions
        ):
            raise ValueError("Ref2VA 参考视频描述不能为空、超过 2000 字或多于 3 项。")
        if self.video_reference_descriptions and self.mode is not H3PromptMode.REF2VA:
            raise ValueError("参考视频只适用于 Ref2VA。")


@dataclass(frozen=True, slots=True)
class H3PromptProposal:
    prompt_text: str

    def __post_init__(self) -> None:
        if not self.prompt_text.strip() or len(self.prompt_text) > 20_000:
            raise ValueError("H3 prompt 不能为空或过长。")
