from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .ffmpeg_pano_view_worker import SCHEMA as PANO_VIEW_SCHEMA
from .ffmpeg_pano_view_worker import check_view as check_pano_view
from .h3_request import SCHEMA as H3_RUNTIME_SCHEMA
from .h3_request import STEPS as H3_STEPS
from .qwen_image_request import MAX_IMAGES as QWEN_MAX_IMAGES
from .qwen_image_request import SCHEMA as QWEN_IMAGE_SCHEMA
from .strict_json import (
    IMAGE_ASPECT_RATIOS,
    RequestError,
    boolean,
    encoded_bytes,
    integer,
    number,
    object_fields,
    require_image_magic,
    string,
)
from .task_store import TaskRecord


def prepare_mock(payload: Any):
    data = object_fields(payload, required={"text", "delay_ms"})
    request = {
        "text": string(data["text"], "text", maximum=1000),
        "delay_ms": integer(data["delay_ms"], "delay_ms", minimum=0, maximum=10_000),
    }
    return lambda record: _write_request(record, request)


def prepare_codex(payload: Any, *, operation: str):
    if operation not in {"generate", "edit"}:
        raise RequestError("Codex 图片 operation 不合法。")
    data = object_fields(
        payload,
        required={
            "instruction",
            "model",
            "aspect_ratio",
            "source_image",
            "reference_images",
        },
    )
    instruction = string(data["instruction"], "instruction", maximum=20_000)
    model = string(data["model"], "model", maximum=128)
    aspect_ratio = string(data["aspect_ratio"], "aspect_ratio", maximum=16)
    if aspect_ratio not in IMAGE_ASPECT_RATIOS:
        raise RequestError("aspect_ratio 不在支持的图片比例中。")
    reference_images = data["reference_images"]
    if not isinstance(reference_images, list) or len(reference_images) > (
        4 if operation == "edit" else 5
    ):
        raise RequestError("reference_images 数量不合法。")
    if operation == "edit" and data["source_image"] is None:
        raise RequestError("图片编辑必须包含 source_image。")
    if operation == "generate" and data["source_image"] is not None:
        raise RequestError("图片生成不能包含 source_image。")

    def prepare(record: TaskRecord) -> None:
        names = []
        all_images = (
            [data["source_image"], *reference_images]
            if data["source_image"] is not None
            else reference_images
        )
        for index, raw in enumerate(all_images, start=1):
            item = object_fields(raw, required={"content_type", "data_base64"})
            media_type = string(item["content_type"], "content_type", maximum=64)
            content = encoded_bytes(item["data_base64"], "data_base64", maximum=32 * 1024 * 1024)
            suffix = require_image_magic(content, media_type)
            name = f"input-{index}{suffix}"
            (Path(record.task_dir) / name).write_bytes(content)
            names.append(name)
        _write_request(
            record,
            {
                "schema": "codex_image_request_v3",
                "operation": operation,
                "instruction": instruction,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "images": names,
            },
        )

    return prepare


def prepare_qwen_image(payload: Any):
    data = object_fields(
        payload,
        required={
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "steps",
            "cfg",
            "seed",
            "images",
        },
    )
    prompt = string(data["prompt"], "prompt", maximum=20_000)
    if not prompt.strip():
        raise RequestError("prompt 不能为空白。")
    negative = string(data["negative_prompt"], "negative_prompt", maximum=4_000, allow_empty=True)
    width = integer(data["width"], "width", minimum=256, maximum=2048)
    height = integer(data["height"], "height", minimum=256, maximum=2048)
    if width % 32 or height % 32:
        raise RequestError("width 与 height 必须是 32 的倍数。")
    steps = integer(data["steps"], "steps", minimum=4, maximum=60)
    cfg = number(data["cfg"], "cfg", minimum=1, maximum=8)
    seed = integer(data["seed"], "seed", minimum=0, maximum=2**63 - 1)
    images = data["images"]
    if not isinstance(images, list) or len(images) > QWEN_MAX_IMAGES:
        raise RequestError(f"images 最多 {QWEN_MAX_IMAGES} 张。")
    decoded = []
    for raw in images:
        item = object_fields(raw, required={"media_type", "content_base64"})
        media_type = string(item["media_type"], "media_type", maximum=64)
        content = encoded_bytes(item["content_base64"], "content_base64", maximum=32 * 1024 * 1024)
        decoded.append((require_image_magic(content, media_type), content))

    def prepare(record: TaskRecord) -> None:
        names = []
        for index, (suffix, content) in enumerate(decoded, start=1):
            name = f"image-{index}{suffix}"
            (Path(record.task_dir) / name).write_bytes(content)
            names.append(name)
        _write_request(
            record,
            {
                "schema": QWEN_IMAGE_SCHEMA,
                "prompt": prompt,
                "negative_prompt": negative,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg": cfg,
                "seed": seed,
                "images": names,
            },
        )

    return prepare


def prepare_h3_fl2va(payload: Any):
    data = object_fields(
        payload,
        required={
            "prompt",
            "canvas",
            "seconds",
            "seed",
            "sampling",
            "include_audio",
            "opening_frame",
            "closing_frame",
        },
    )
    canvas = object_fields(data["canvas"], required={"width", "height"})
    sampling = object_fields(
        data["sampling"], required={"steps", "cfg", "sage_attention", "selflift"}
    )
    common = _h3_common(
        prompt=data["prompt"],
        width=canvas["width"],
        height=canvas["height"],
        duration=data["seconds"],
        seed=data["seed"],
        steps=sampling["steps"],
        cfg=sampling["cfg"],
        sage_attention=sampling["sage_attention"],
        selflift=sampling["selflift"],
        save_audio=data["include_audio"],
    )
    if data["opening_frame"] is None and data["closing_frame"] is None:
        raise RequestError("FL2VA 至少需要 opening_frame 或 closing_frame 之一。")

    def prepare(record: TaskRecord) -> None:
        first = _store_h3_fl2va_image(record, data["opening_frame"], "first")
        last = _store_h3_fl2va_image(record, data["closing_frame"], "last")
        _write_request(
            record,
            {
                "schema": H3_RUNTIME_SCHEMA,
                "mode": "fl2va",
                **common,
                "first_image": first,
                "last_image": last,
                "additional_images": [],
                "reference_audios": [],
                "reference_videos": [],
            },
        )

    return prepare


def prepare_h3_ref2va(payload: Any):
    data = object_fields(
        payload,
        required={
            "direction",
            "first_reference",
            "last_reference",
            "additional_references",
            "width_px",
            "height_px",
            "duration_s",
            "random_seed",
            "step_count",
            "guidance",
            "sage_attention",
            "selflift",
            "audio",
            "audio_references",
            "video_references",
        },
    )
    common = _h3_common(
        prompt=data["direction"],
        width=data["width_px"],
        height=data["height_px"],
        duration=data["duration_s"],
        seed=data["random_seed"],
        steps=data["step_count"],
        cfg=data["guidance"],
        sage_attention=data["sage_attention"],
        selflift=data["selflift"],
        save_audio=data["audio"],
    )
    additional_references = data["additional_references"]
    if (
        not isinstance(additional_references, list)
        or len(additional_references) > 4
        or any(item is None for item in additional_references)
    ):
        raise RequestError("Ref2VA additional_references 必须是最多 4 项的数组。")
    audios = data["audio_references"]
    if not isinstance(audios, list) or len(audios) > 8:
        raise RequestError("Ref2VA audio_references 必须是最多 8 项的数组。")
    audio_contents: list[bytes] = []
    for index, raw_audio in enumerate(audios, start=1):
        audio = object_fields(raw_audio, required={"media_type", "content"})
        audio_media_type = string(
            audio["media_type"], f"audio_references[{index - 1}].media_type", maximum=64
        )
        if audio_media_type != "audio/wav":
            raise RequestError("Ref2VA 参考音频只接受 WAV。")
        audio_contents.append(
            encoded_bytes(
                audio["content"],
                f"audio_references[{index - 1}].content",
                maximum=64 * 1024 * 1024,
            )
        )
    videos = data["video_references"]
    if not isinstance(videos, list) or len(videos) > 3:
        raise RequestError("Ref2VA video_references 必须是最多 3 项的数组。")
    video_contents: list[bytes] = []
    for index, raw_video in enumerate(videos, start=1):
        video = object_fields(raw_video, required={"media_type", "content"})
        video_media_type = string(
            video["media_type"], f"video_references[{index - 1}].media_type", maximum=64
        )
        if video_media_type != "video/mp4":
            raise RequestError("Ref2VA 参考视频只接受 MP4。")
        video_contents.append(
            encoded_bytes(
                video["content"],
                f"video_references[{index - 1}].content",
                maximum=512 * 1024 * 1024,
            )
        )
    if not any(
        (
            data["first_reference"],
            data["last_reference"],
            additional_references,
            audios,
            videos,
        )
    ):
        raise RequestError("Ref2VA 至少需要一个媒体参考。")

    def prepare(record: TaskRecord) -> None:
        first = _store_h3_ref_image(record, data["first_reference"], "first")
        last = _store_h3_ref_image(record, data["last_reference"], "last")
        additional = [
            _store_h3_ref_image(record, raw, f"additional-{index}")
            for index, raw in enumerate(additional_references, start=1)
        ]
        audio_names = []
        for index, audio_content in enumerate(audio_contents, start=1):
            audio_name = f"audio-{index}.wav"
            (Path(record.task_dir) / audio_name).write_bytes(audio_content)
            audio_names.append(audio_name)
        video_names = []
        for index, video_content in enumerate(video_contents, start=1):
            video_name = f"video-{index}.mp4"
            (Path(record.task_dir) / video_name).write_bytes(video_content)
            video_names.append(video_name)
        _write_request(
            record,
            {
                "schema": H3_RUNTIME_SCHEMA,
                "mode": "ref2va",
                **common,
                "first_image": first,
                "last_image": last,
                "additional_images": additional,
                "reference_audios": audio_names,
                "reference_videos": video_names,
            },
        )

    return prepare


def prepare_stable_audio_3(payload: Any):
    """校验文生音频请求。步数和精度由 runtime 固定。"""

    data = object_fields(payload, required={"prompt", "duration_seconds", "seed"})
    prompt = string(data["prompt"], "prompt", maximum=1000).strip()
    if not prompt:
        raise RequestError("prompt 不是合法字符串。")
    duration = number(data["duration_seconds"], "duration_seconds", minimum=1, maximum=380)
    seed = integer(data["seed"], "seed", minimum=0, maximum=2**63 - 1)
    request = {
        "schema": "stable_audio_3_request_v1",
        "prompt": prompt,
        "duration_seconds": duration,
        "seed": seed,
    }
    return lambda record: _write_request(record, request)


def prepare_indextts2(payload: Any):
    data = object_fields(
        payload,
        required={"content", "voice_sample", "randomness", "pace", "emotion"},
        optional={"language"},
    )
    voice = object_fields(data["voice_sample"], required={"type", "encoded"})
    media_type = string(voice["type"], "voice_sample.type", maximum=64)
    suffixes = {
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/flac": ".flac",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
    }
    if media_type not in suffixes:
        raise RequestError("参考音频类型不受支持。")
    content = encoded_bytes(voice["encoded"], "voice_sample.encoded", maximum=64 * 1024 * 1024)
    emotion = data["emotion"]
    if not isinstance(emotion, list) or len(emotion) != 8:
        raise RequestError("emotion 必须包含 8 个数字。")
    emotion_values = [number(item, "emotion", minimum=-1, maximum=1) for item in emotion]
    language = data.get("language", "auto")
    if language not in ("auto", "zh", "en"):
        raise RequestError("language 必须是 auto、zh 或 en。")
    request = {
        "schema": "indextts2_request_v2",
        "language": language,
        "text": string(data["content"], "content", maximum=20_000),
        "seed": integer(data["randomness"], "randomness", minimum=0, maximum=2**63 - 1),
        "duration_factor": number(data["pace"], "pace", minimum=0.5, maximum=2.0),
        "emotion_vector": emotion_values,
        "voice_file": "voice" + suffixes[media_type],
    }

    def prepare(record: TaskRecord) -> None:
        (Path(record.task_dir) / request["voice_file"]).write_bytes(content)
        _write_request(record, request)

    return prepare


def prepare_breeze_tts2(payload: Any):
    """Validate the closed Breeze request before it enters the GPU queue."""

    data = object_fields(
        payload,
        required={"text", "instruction", "voice", "reference_transcript", "cfg_scale", "seed"},
    )
    text = string(data["text"], "text", maximum=20_000)
    instruction = data["instruction"]
    if instruction is not None:
        instruction = string(instruction, "instruction", maximum=4_000)
    transcript = data["reference_transcript"]
    if transcript is not None:
        transcript = string(transcript, "reference_transcript", maximum=20_000)
    cfg_scale = number(data["cfg_scale"], "cfg_scale", minimum=0.0001, maximum=20)
    seed = integer(data["seed"], "seed", minimum=0, maximum=2**63 - 1)
    raw_voice = data["voice"]
    voice_name: str | None = None
    voice_content: bytes | None = None
    voice_media_type: str | None = None
    if raw_voice is not None:
        voice = object_fields(raw_voice, required={"media_type", "base64"})
        voice_media_type = string(voice["media_type"], "voice.media_type", maximum=64)
        if voice_media_type not in {
            "audio/wav",
            "audio/mpeg",
            "audio/flac",
            "audio/mp4",
            "audio/ogg",
        }:
            raise RequestError("Breeze 参考音频类型不受支持。")
        voice_content = encoded_bytes(voice["base64"], "voice.base64", maximum=64 * 1024 * 1024)
        voice_name = (
            "reference"
            + {
                "audio/wav": ".wav",
                "audio/mpeg": ".mp3",
                "audio/flac": ".flac",
                "audio/mp4": ".m4a",
                "audio/ogg": ".ogg",
            }[voice_media_type]
        )
        if not transcript:
            raise RequestError("Breeze Voice Clone 必须提供完整文字稿。")
    elif transcript is not None:
        raise RequestError("Breeze Voice Design 不能包含 reference_transcript。")
    request = {
        "schema": "breeze_tts2_request_v1",
        "text": text,
        "instruction": instruction,
        "reference_transcript": transcript,
        "cfg_scale": cfg_scale,
        "seed": seed,
        "voice": voice_name,
        "voice_media_type": voice_media_type,
    }

    def prepare(record: TaskRecord) -> None:
        if voice_name is not None and voice_content is not None:
            (Path(record.task_dir) / voice_name).write_bytes(voice_content)
        _write_request(record, request)

    return prepare


def prepare_seedvr2_7b_sharp_fp8(payload: Any):
    data = object_fields(
        payload,
        required={"source_video", "target_short_side", "max_long_side", "seed"},
    )
    source = object_fields(data["source_video"], required={"mime", "base64"})
    if string(source["mime"], "source_video.mime", maximum=64) != "video/mp4":
        raise RequestError("SeedVR2 输入只接受 MP4。")
    content = encoded_bytes(source["base64"], "source_video.base64", maximum=512 * 1024 * 1024)
    if len(content) < 12 or content[4:8] != b"ftyp":
        raise RequestError("SeedVR2 输入不是真实 MP4。")
    short_side = integer(data["target_short_side"], "target_short_side", minimum=720, maximum=1440)
    if short_side not in {720, 1080, 1440}:
        raise RequestError("target_short_side 不受支持。")
    long_side = integer(data["max_long_side"], "max_long_side", minimum=1280, maximum=2560)
    if long_side not in {1280, 1920, 2560}:
        raise RequestError("max_long_side 不受支持。")
    request = {
        "schema": "seedvr2_7b_sharp_fp8_request_v1",
        "input_video": "input.mp4",
        "target_short_side": short_side,
        "max_long_side": long_side,
        "seed": integer(data["seed"], "seed", minimum=0, maximum=2**63 - 1),
    }

    def prepare(record: TaskRecord) -> None:
        (Path(record.task_dir) / "input.mp4").write_bytes(content)
        _write_request(record, request)

    return prepare


def prepare_ffmpeg_final_assembly(payload: Any):
    data = object_fields(
        payload,
        required={"aspect_ratio", "transition_seconds", "clips", "narrations"},
        optional={"video_audio_volume", "narration_audio_volume"},
    )
    aspect_ratio = string(data["aspect_ratio"], "aspect_ratio", maximum=16)
    if aspect_ratio not in {"16:9", "9:16", "2:1"}:
        raise RequestError("aspect_ratio 只允许 16:9、9:16 或 2:1。")
    transition_seconds = number(
        data["transition_seconds"], "transition_seconds", minimum=0.1, maximum=1.0
    )
    video_audio_volume = number(
        data.get("video_audio_volume", 1.0), "video_audio_volume", minimum=0.0, maximum=2.0
    )
    narration_audio_volume = number(
        data.get("narration_audio_volume", 1.0),
        "narration_audio_volume",
        minimum=0.0,
        maximum=2.0,
    )
    raw_clips = data["clips"]
    raw_narrations = data["narrations"]
    if not isinstance(raw_clips, list) or not 1 <= len(raw_clips) <= 500:
        raise RequestError("clips 必须包含 1 到 500 项。")
    if not isinstance(raw_narrations, list) or len(raw_narrations) > 200:
        raise RequestError("narrations 最多包含 200 项。")
    clips: list[tuple[bytes, str | None, float]] = []
    for index, raw in enumerate(raw_clips):
        item = object_fields(
            raw,
            required={"mime", "base64", "transition_from_previous", "duration_seconds"},
        )
        if string(item["mime"], f"clips[{index}].mime", maximum=64) != "video/mp4":
            raise RequestError("成片片段只接受 MP4。")
        content = encoded_bytes(item["base64"], f"clips[{index}].base64", maximum=512 * 1024 * 1024)
        if len(content) < 12 or content[4:8] != b"ftyp":
            raise RequestError("成片片段不是真实 MP4。")
        transition = item["transition_from_previous"]
        if transition is not None:
            transition = string(transition, f"clips[{index}].transition_from_previous", maximum=32)
        if index == 0 and transition is not None:
            raise RequestError("首个片段不能包含入场转场。")
        if index > 0 and transition not in {None, "seam_blend"}:
            raise RequestError("后续片段必须声明受支持的入场转场。")
        duration = number(
            item["duration_seconds"],
            f"clips[{index}].duration_seconds",
            minimum=0.05,
            maximum=600,
        )
        clips.append((content, transition, duration))
    narrations: list[tuple[bytes, int]] = []
    for index, raw in enumerate(raw_narrations):
        item = object_fields(raw, required={"mime", "base64", "start_clip_index"})
        if string(item["mime"], f"narrations[{index}].mime", maximum=64) != "audio/wav":
            raise RequestError("成片旁白只接受 WAV。")
        content = encoded_bytes(
            item["base64"], f"narrations[{index}].base64", maximum=64 * 1024 * 1024
        )
        if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
            raise RequestError("成片旁白不是真实 WAV。")
        start = integer(
            item["start_clip_index"],
            f"narrations[{index}].start_clip_index",
            minimum=0,
            maximum=len(clips) - 1,
        )
        narrations.append((content, start))

    def prepare(record: TaskRecord) -> None:
        root = Path(record.task_dir)
        clip_specs = []
        for index, (content, transition, duration) in enumerate(clips):
            name = f"clip-{index:04d}.mp4"
            (root / name).write_bytes(content)
            clip_specs.append(
                {
                    "file": name,
                    "transition_from_previous": transition,
                    "duration_seconds": duration,
                }
            )
        narration_specs = []
        for index, (content, start) in enumerate(narrations):
            name = f"narration-{index:04d}.wav"
            (root / name).write_bytes(content)
            narration_specs.append({"file": name, "start_clip_index": start})
        _write_request(
            record,
            {
                "schema": "ffmpeg_final_assembly_request_v2",
                "aspect_ratio": aspect_ratio,
                "transition_seconds": transition_seconds,
                "video_audio_volume": video_audio_volume,
                "narration_audio_volume": narration_audio_volume,
                "clips": clip_specs,
                "narrations": narration_specs,
            },
        )

    return prepare


def prepare_ffmpeg_animatic(payload: Any):
    data = object_fields(
        payload,
        required={"aspect_ratio", "transition_seconds", "clips", "narrations"},
    )
    aspect_ratio = string(data["aspect_ratio"], "aspect_ratio", maximum=16)
    if aspect_ratio not in {"16:9", "9:16", "2:1"}:
        raise RequestError("aspect_ratio 只允许 16:9、9:16 或 2:1。")
    transition_seconds = number(
        data["transition_seconds"], "transition_seconds", minimum=0.1, maximum=1.0
    )
    raw_clips = data["clips"]
    raw_narrations = data["narrations"]
    if not isinstance(raw_clips, list) or not 1 <= len(raw_clips) <= 500:
        raise RequestError("clips 必须包含 1 到 500 项。")
    if not isinstance(raw_narrations, list) or len(raw_narrations) > 200:
        raise RequestError("narrations 最多包含 200 项。")
    clips: list[tuple[bytes, str, str | None, float]] = []
    for index, raw in enumerate(raw_clips):
        item = object_fields(
            raw,
            required={"mime", "base64", "transition_from_previous", "duration_seconds"},
        )
        media_type = string(item["mime"], f"clips[{index}].mime", maximum=64)
        if media_type not in {"image/png", "image/jpeg"}:
            raise RequestError("Animatic 关键帧只接受 PNG 或 JPEG。")
        content = encoded_bytes(item["base64"], f"clips[{index}].base64", maximum=64 * 1024 * 1024)
        require_image_magic(content, media_type)
        transition = item["transition_from_previous"]
        if transition is not None:
            transition = string(transition, f"clips[{index}].transition_from_previous", maximum=32)
        if index == 0 and transition is not None:
            raise RequestError("首个片段不能包含入场转场。")
        if index > 0 and transition not in {None, "seam_blend"}:
            raise RequestError("后续片段的入场转场类型不受支持。")
        duration = number(
            item["duration_seconds"],
            f"clips[{index}].duration_seconds",
            minimum=0.05,
            maximum=600,
        )
        clips.append((content, media_type, transition, duration))
    narrations: list[tuple[bytes, int]] = []
    for index, raw in enumerate(raw_narrations):
        item = object_fields(raw, required={"mime", "base64", "start_clip_index"})
        if string(item["mime"], f"narrations[{index}].mime", maximum=64) != "audio/wav":
            raise RequestError("Animatic 旁白只接受 WAV。")
        content = encoded_bytes(
            item["base64"], f"narrations[{index}].base64", maximum=64 * 1024 * 1024
        )
        if len(content) < 12 or content[:4] != b"RIFF" or content[8:12] != b"WAVE":
            raise RequestError("Animatic 旁白不是真实 WAV。")
        start = integer(
            item["start_clip_index"],
            f"narrations[{index}].start_clip_index",
            minimum=0,
            maximum=len(clips) - 1,
        )
        narrations.append((content, start))

    def prepare(record: TaskRecord) -> None:
        root = Path(record.task_dir)
        clip_specs = []
        for index, (content, media_type, transition, duration) in enumerate(clips):
            suffix = require_image_magic(content, media_type)
            name = f"clip-{index:04d}{suffix}"
            (root / name).write_bytes(content)
            clip_specs.append(
                {
                    "file": name,
                    "transition_from_previous": transition,
                    "duration_seconds": duration,
                }
            )
        narration_specs = []
        for index, (content, start) in enumerate(narrations):
            name = f"narration-{index:04d}.wav"
            (root / name).write_bytes(content)
            narration_specs.append({"file": name, "start_clip_index": start})
        _write_request(
            record,
            {
                "schema": "ffmpeg_animatic_request_v1",
                "aspect_ratio": aspect_ratio,
                "transition_seconds": transition_seconds,
                "clips": clip_specs,
                "narrations": narration_specs,
            },
        )

    return prepare


def prepare_demucs_audio_separation(payload: Any):
    data = object_fields(payload, required={"video", "stem"})
    video = object_fields(data["video"], required={"mime", "base64"})
    if string(video["mime"], "video.mime", maximum=64) != "video/mp4":
        raise RequestError("音轨分离只接受 MP4。")
    content = encoded_bytes(video["base64"], "video.base64", maximum=512 * 1024 * 1024)
    if len(content) < 12 or content[4:8] != b"ftyp":
        raise RequestError("音轨分离输入不是真实 MP4。")
    stem = string(data["stem"], "stem", maximum=32)
    if stem not in {"voice", "background"}:
        raise RequestError("stem 只允许 voice 或 background。")

    def prepare(record: TaskRecord) -> None:
        root = Path(record.task_dir)
        (root / "input.mp4").write_bytes(content)
        _write_request(
            record,
            {"schema": "demucs_audio_separation_request_v1", "input": "input.mp4", "stem": stem},
        )

    return prepare


def prepare_ffmpeg_audio_remix(payload: Any):
    data = object_fields(
        payload,
        required={"video", "voice", "background", "voice_gain_db", "background_gain_db"},
        optional={
            "voice_gain_start_seconds",
            "voice_gain_end_seconds",
            "background_gain_start_seconds",
            "background_gain_end_seconds",
        },
    )

    def media(name: str, mime: str, maximum: int) -> bytes:
        item = object_fields(data[name], required={"mime", "base64"})
        if string(item["mime"], f"{name}.mime", maximum=64) != mime:
            raise RequestError(f"{name} 媒体类型不合法。")
        return encoded_bytes(item["base64"], f"{name}.base64", maximum=maximum)

    video = media("video", "video/mp4", 512 * 1024 * 1024)
    voice = media("voice", "audio/wav", 128 * 1024 * 1024)
    background = media("background", "audio/wav", 128 * 1024 * 1024)
    if len(video) < 12 or video[4:8] != b"ftyp":
        raise RequestError("音轨混音视频不是真实 MP4。")
    if any(
        len(item) < 12 or item[:4] != b"RIFF" or item[8:12] != b"WAVE"
        for item in (voice, background)
    ):
        raise RequestError("音轨混音输入不是真实 WAV。")
    voice_gain = number(data["voice_gain_db"], "voice_gain_db", minimum=-100, maximum=24)
    background_gain = number(
        data["background_gain_db"], "background_gain_db", minimum=-100, maximum=24
    )
    voice_range = _optional_time_range(data, "voice_gain")
    background_range = _optional_time_range(data, "background_gain")

    def prepare(record: TaskRecord) -> None:
        root = Path(record.task_dir)
        (root / "input.mp4").write_bytes(video)
        (root / "voice.wav").write_bytes(voice)
        (root / "background.wav").write_bytes(background)
        _write_request(
            record,
            {
                "schema": "ffmpeg_audio_remix_request_v2",
                "video": "input.mp4",
                "voice": "voice.wav",
                "background": "background.wav",
                "voice_gain_db": voice_gain,
                "background_gain_db": background_gain,
                "voice_gain_start_seconds": voice_range[0],
                "voice_gain_end_seconds": voice_range[1],
                "background_gain_start_seconds": background_range[0],
                "background_gain_end_seconds": background_range[1],
            },
        )

    return prepare


def _optional_time_range(data: dict[str, Any], prefix: str) -> tuple[float | None, float | None]:
    start_value = data.get(f"{prefix}_start_seconds")
    end_value = data.get(f"{prefix}_end_seconds")
    if (start_value is None) != (end_value is None):
        raise RequestError(f"{prefix} 开始和结束时间必须同时提供或同时省略。")
    if start_value is None or end_value is None:
        return None, None
    start = number(start_value, f"{prefix}_start_seconds", minimum=0, maximum=604800)
    end = number(end_value, f"{prefix}_end_seconds", minimum=0, maximum=604800)
    if end <= start:
        raise RequestError(f"{prefix} 结束时间必须晚于开始时间。")
    return start, end


def _h3_common(
    *,
    prompt: Any,
    width: Any,
    height: Any,
    duration: Any,
    seed: Any,
    steps: Any,
    cfg: Any,
    sage_attention: Any,
    selflift: Any,
    save_audio: Any,
) -> dict[str, Any]:
    width_value = integer(width, "width", minimum=256, maximum=1920)
    height_value = integer(height, "height", minimum=256, maximum=1920)
    if width_value % 32 or height_value % 32 or width_value * height_value > 2_100_000:
        raise RequestError("H3 画布必须对齐到 32 且不超过像素上限。")
    steps_value = integer(steps, "steps", minimum=8, maximum=20)
    if steps_value not in H3_STEPS:
        raise RequestError("H3 steps 只允许 20 或 8。")
    return {
        "prompt": string(prompt, "prompt", maximum=20_000),
        "width": width_value,
        "height": height_value,
        "duration_seconds": number(duration, "duration", minimum=0.2, maximum=15),
        "seed": integer(seed, "seed", minimum=0, maximum=2**63 - 1),
        "steps": steps_value,
        "cfg": number(cfg, "cfg", minimum=0, maximum=30),
        "sage_attention": boolean(sage_attention, "sage_attention"),
        "selflift": boolean(selflift, "selflift"),
        "save_audio": boolean(save_audio, "save_audio"),
    }


def _store_h3_fl2va_image(record: TaskRecord, raw: Any, stem: str) -> str | None:
    if raw is None:
        return None
    item = object_fields(raw, required={"mime", "base64"})
    media_type = string(item["mime"], "mime", maximum=64)
    content = encoded_bytes(item["base64"], "base64", maximum=64 * 1024 * 1024)
    return _write_h3_image(record, stem, media_type, content)


def _store_h3_ref_image(record: TaskRecord, raw: Any, stem: str) -> str | None:
    if raw is None:
        return None
    item = object_fields(raw, required={"media_type", "content"})
    media_type = string(item["media_type"], "media_type", maximum=64)
    content = encoded_bytes(item["content"], "content", maximum=64 * 1024 * 1024)
    return _write_h3_image(record, stem, media_type, content)


def _write_h3_image(record: TaskRecord, stem: str, media_type: str, content: bytes) -> str:
    suffix = require_image_magic(content, media_type)
    name = stem + suffix
    (Path(record.task_dir) / name).write_bytes(content)
    return name


def _write_request(record: TaskRecord, value: dict[str, Any]) -> None:
    path = Path(record.task_dir) / "request.json"
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def prepare_ffmpeg_video_frame(payload):
    data = object_fields(payload, required={"mime", "base64", "frame_index"})
    if data["mime"] != "video/mp4":
        raise RequestError("抽帧只接受 MP4。")
    frame_index = data["frame_index"]
    if type(frame_index) is not int or not 0 <= frame_index < 10_000_000:
        raise RequestError("抽帧帧号必须是非负整数。")
    content = encoded_bytes(data["base64"], "base64", maximum=512 * 1024 * 1024)
    if len(content) < 12 or content[4:8] != b"ftyp":
        raise RequestError("抽帧输入不是真实 MP4。")

    def prepare(record):
        (Path(record.task_dir) / "source.mp4").write_bytes(content)
        _write_request(record, {"schema": "video_frame_v2", "frame_index": frame_index})

    return prepare


def prepare_ffmpeg_pano_view(payload):
    data = object_fields(
        payload,
        required={"mime", "base64", "yaw_deg", "pitch_deg", "hfov_deg", "aspect_ratio"},
    )
    if data["mime"] not in {"image/png", "image/jpeg"}:
        raise RequestError("全景裁切只接受 PNG 或 JPEG。")
    try:
        check_pano_view(data["yaw_deg"], data["pitch_deg"], data["hfov_deg"], data["aspect_ratio"])
    except ValueError as exc:
        raise RequestError(str(exc)) from exc
    content = encoded_bytes(data["base64"], "base64", maximum=64 * 1024 * 1024)
    suffix = require_image_magic(content, data["mime"])
    view = {
        "schema": PANO_VIEW_SCHEMA,
        "source": f"source{suffix}",
        "yaw_deg": float(data["yaw_deg"]),
        "pitch_deg": float(data["pitch_deg"]),
        "hfov_deg": float(data["hfov_deg"]),
        "aspect_ratio": data["aspect_ratio"],
    }

    def prepare(record):
        (Path(record.task_dir) / view["source"]).write_bytes(content)
        _write_request(record, view)

    return prepare
