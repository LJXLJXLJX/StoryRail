"""PG2-T1：Playground 能力目录、参数契约与输入解析。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.audio_effects.presets import preset_names
from core.model_providers.codex_image.provider import to_generate_request
from core.model_providers.contracts import VideoFrameRequest
from core.model_providers.minimax_h3.contracts import FL2VARequest, Ref2VARequest
from core.model_providers.minimax_h3.manifest import MANIFEST as H3_MANIFEST
from core.model_providers.minimax_h3.prompt_contract import (
    H3PromptContext,
    H3PromptMode,
    H3ShotInput,
)
from core.model_providers.minimax_h3.prompt_payload import (
    _actual_provider_inputs,
    h3_prompt_payload,
)
from core.model_providers.minimax_h3.render import H3RenderSettings, H3Resolution
from core.model_providers.recipe import RecipeRequest, recipe_wire_schema
from core.model_providers.registry import CAPABILITIES
from core.playground.capabilities import resolve_recipe_request, run_output_label
from core.playground.models import AssetOrigin, PlaygroundAsset, PlaygroundDocument
from core.playground.parameters import input_asset_ids, parameter_seed, recipe_input_labels
from tests.playground_fixtures import real_mp4_bytes
from tests.playground_recipes import (
    CAPABILITY_SPECS,
    PARAMETER_SCHEMAS,
    RECIPE_CAPABILITIES,
    PlaygroundCapability,
    parse_parameters,
    recipe_for,
    resolve_request,
)

TS = "2026-09-28T03:12:45.123456+00:00"
ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _described(asset_id: str, description: str = "参考") -> dict[str, str]:
    return {"asset_id": asset_id, "description": description}


SAMPLES: dict[PlaygroundCapability, dict[str, object]] = {
    PlaygroundCapability.IMAGE_GENERATE: {
        "prompt": "雨夜街道",
        "aspect_ratio": "16:9",
        "reference_image_asset_ids": [],
    },
    PlaygroundCapability.IMAGE_EDIT: {
        "prompt": "改成白天",
        "aspect_ratio": "9:16",
        "source_image_asset_id": ID_A,
        "reference_image_asset_ids": [ID_B],
    },
    PlaygroundCapability.TTS_VOICE_DESIGN: {
        "text": "你好",
        "voice_description": "中年男声，低沉沙哑",
        "seed": 42,
    },
    PlaygroundCapability.TTS_VOICE_CLONE: {
        "text": "你好",
        "voice_asset_id": ID_A,
        "reference_transcript": "你好",
        "performance_instruction": None,
        "seed": 42,
    },
    PlaygroundCapability.ASR_TRANSCRIBE: {"audio_asset_id": ID_A, "language": "auto"},
    PlaygroundCapability.VIDEO_FL2VA: {
        "prompt": "镜头推近",
        "aspect_ratio": "16:9",
        "duration_seconds": 6.0,
        "seed": 1234,
        "first_frame_asset_id": ID_A,
        "last_frame_asset_id": None,
    },
    PlaygroundCapability.VIDEO_REF2VA: {
        "prompt": "<Picture 1> 镜头推近",
        "aspect_ratio": "16:9",
        "duration_seconds": 8.0,
        "seed": 99,
        "first_frame_asset_id": ID_A,
        "last_frame_asset_id": None,
        "additional_images": [],
        "reference_audios": [],
        "reference_videos": [],
    },
    PlaygroundCapability.VIDEO_UPSCALE: {"video_asset_id": ID_A, "seed": 42},
    PlaygroundCapability.VIDEO_EXTRACT_FRAME: {"video_asset_id": ID_A, "frame_index": 0},
    PlaygroundCapability.IMAGE_PANO_VIEW: {
        "image_asset_id": ID_A,
        "yaw_deg": 90.0,
        "pitch_deg": 0.0,
        "hfov_deg": 90.0,
        "aspect_ratio": "16:9",
    },
    PlaygroundCapability.AUDIO_SEPARATE: {"video_asset_id": ID_A, "stem": "voice"},
    PlaygroundCapability.AUDIO_GENERATE: {
        "prompt": "安静的钢琴",
        "duration_seconds": 10,
        "seed": 7,
    },
    PlaygroundCapability.AUDIO_REMIX: {
        "video_asset_id": ID_A,
        "voice_asset_id": ID_B,
        "background_asset_id": ID_C,
        "voice_gain_db": 0.0,
        "background_gain_db": -6.0,
        "voice_gain_start_seconds": None,
        "voice_gain_end_seconds": None,
        "background_gain_start_seconds": None,
        "background_gain_end_seconds": None,
    },
    PlaygroundCapability.AUDIO_EFFECT: {
        "audio_asset_id": ID_A,
        "preset": preset_names()[0],
        "strength": 0.7,
        "seed": 42,
        "start_seconds": None,
        "end_seconds": None,
    },
    PlaygroundCapability.AUDIO_TRIM: {
        "audio_asset_id": ID_A,
        "start_seconds": 1.0,
        "end_seconds": 4.5,
    },
}

assert set(SAMPLES) == set(PlaygroundCapability)


def _asset(
    asset_id: str, media_type: str, *, duration: float | None, label: str
) -> PlaygroundAsset:
    sha = asset_id + "f" * 32
    extension = {"image/png": "png", "audio/wav": "wav", "video/mp4": "mp4"}[media_type]
    directory = {"image/png": "images", "audio/wav": "audio", "video/mp4": "videos"}[media_type]
    return PlaygroundAsset(
        id=asset_id,
        media_type=media_type,
        byte_count=1024,
        sha256=sha,
        relative_path=f"assets/{directory}/imported/{label}-{sha[:10]}.{extension}",
        duration_seconds=duration,
        origin=AssetOrigin("imported"),
        created_at=TS,
    )


def _recipe(capability):
    return recipe_for(capability)


def _schema(capability):
    recipe = _recipe(capability)
    return recipe_wire_schema(recipe) if recipe else PARAMETER_SCHEMAS[capability]


def _keys(capability):
    return tuple(_schema(capability)["properties"])


def _parse(capability, value):
    return parse_parameters(capability, value, recipe=_recipe(capability))


def _resolve(capability, parameters, *, document, read_asset, h3_render=None):
    if capability not in {PlaygroundCapability.VIDEO_FL2VA, PlaygroundCapability.VIDEO_REF2VA}:
        return resolve_request(capability, parameters, document=document, read_asset=read_asset)
    from core.model_providers.minimax_h3.requests import to_request

    render = h3_render or H3RenderSettings()
    resolved = resolve_recipe_request(
        H3_MANIFEST,
        _recipe(capability),
        parameters,
        read_asset=read_asset,
        settings={
            "preset": "turbo_v2" if render.steps == 8 else "hybrid_v2",
            "resolution": render.resolution.value,
            "sage_attention": render.sage_attention,
            "selflift": render.selflift,
        },
    )
    return replace(resolved, provider_request=to_request(resolved.provider_request))


def ref2va_input_labels(parameters):
    return recipe_input_labels(H3_MANIFEST.recipe("minimax_h3.ref2va"), parameters)


def test_every_capability_has_spec_and_parser() -> None:
    assert set(CAPABILITY_SPECS) == set(PlaygroundCapability)
    for capability, spec in CAPABILITY_SPECS.items():
        assert spec.label
        assert spec.notes
        assert spec.id is capability
        assert set(_schema(capability)["properties"]) == set(_keys(capability))
        if spec.execution == "async":
            assert spec.registry_capability in CAPABILITIES or capability in RECIPE_CAPABILITIES
        else:
            assert spec.registry_capability in {None, "speech_recognition"}


def test_schema_keys_match_parser_keys() -> None:
    for capability in PlaygroundCapability:
        schema = _schema(capability)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == set(schema["required"]) == set(_keys(capability))

        dropped = _keys(capability)[0]
        missing = {key: value for key, value in SAMPLES[capability].items() if key != dropped}
        with pytest.raises(ValueError):
            _parse(capability, missing)
        extra = {**SAMPLES[capability], "unknown": 1}
        with pytest.raises(ValueError):
            _parse(capability, extra)


def test_parse_rejects_unknown_missing_and_bool_numbers() -> None:
    for capability in PlaygroundCapability:
        _parse(capability, SAMPLES[capability])
        numeric_key = next(
            (
                key
                for key in ("seed", "frame_index", "start_seconds", "end_seconds")
                if key in _keys(capability)
            ),
            None,
        )
        if numeric_key is None:
            continue
        with pytest.raises(ValueError, match="必须是"):
            _parse(capability, {**SAMPLES[capability], numeric_key: True})


def test_parse_normalizes_whitespace_and_does_not_mutate_input() -> None:
    raw = {**SAMPLES[PlaygroundCapability.IMAGE_GENERATE], "prompt": "  雨夜街道  "}
    parsed = _parse(PlaygroundCapability.IMAGE_GENERATE, raw)
    assert parsed["prompt"] == "雨夜街道"
    assert raw["prompt"] == "  雨夜街道  "


def test_fl2va_requires_at_least_one_frame() -> None:
    base = SAMPLES[PlaygroundCapability.VIDEO_FL2VA]
    with pytest.raises(ValueError, match="至少需要首帧或尾帧"):
        _parse(
            PlaygroundCapability.VIDEO_FL2VA,
            {**base, "first_frame_asset_id": None, "last_frame_asset_id": None},
        )
    assert (
        _parse(
            PlaygroundCapability.VIDEO_FL2VA,
            {**base, "first_frame_asset_id": None, "last_frame_asset_id": ID_B},
        )["last_frame_asset_id"]
        == ID_B
    )


def test_ref2va_accepts_no_images_when_audio_is_present() -> None:
    base = SAMPLES[PlaygroundCapability.VIDEO_REF2VA]
    parsed = _parse(
        PlaygroundCapability.VIDEO_REF2VA,
        {
            **base,
            "first_frame_asset_id": None,
            "last_frame_asset_id": None,
            "additional_images": [],
            "reference_audios": [_described(ID_B, "对白参考")],
            "reference_videos": [],
        },
    )
    assert parsed["first_frame_asset_id"] is None
    assert parsed["last_frame_asset_id"] is None
    assert parsed["additional_images"] == []
    assert parsed["reference_audios"] == [_described(ID_B, "对白参考")]
    assert parsed["reference_videos"] == []
    with pytest.raises(ValueError, match="至少需要"):
        _parse(
            PlaygroundCapability.VIDEO_REF2VA,
            {
                **base,
                "first_frame_asset_id": None,
                "last_frame_asset_id": None,
                "additional_images": [],
                "reference_audios": [],
                "reference_videos": [],
            },
        )


def test_video_duration_has_no_upper_limit() -> None:
    # 15 秒只是 Agent 侧软约束（可能 OOM），Core 不做硬限制。
    for capability in (PlaygroundCapability.VIDEO_FL2VA, PlaygroundCapability.VIDEO_REF2VA):
        base = SAMPLES[capability]
        assert _parse(capability, {**base, "duration_seconds": 30.0})["duration_seconds"] == 30.0
        with pytest.raises(ValueError, match="超出允许范围"):
            _parse(capability, {**base, "duration_seconds": 0.1})


def test_ref2va_list_limits_and_required_descriptions() -> None:
    base = SAMPLES[PlaygroundCapability.VIDEO_REF2VA]
    with pytest.raises(ValueError, match="0 到 4 项"):
        _parse(
            PlaygroundCapability.VIDEO_REF2VA,
            {**base, "additional_images": [_described(ID_B)] * 5},
        )
    with pytest.raises(ValueError, match="0 到 8 项"):
        _parse(
            PlaygroundCapability.VIDEO_REF2VA,
            {**base, "reference_audios": [_described(ID_B)] * 9},
        )
    with pytest.raises(ValueError, match="0 到 3 项"):
        _parse(
            PlaygroundCapability.VIDEO_REF2VA,
            {**base, "reference_videos": [_described(ID_B)] * 4},
        )
    with pytest.raises(ValueError, match="填写说明"):
        _parse(
            PlaygroundCapability.VIDEO_REF2VA,
            {**base, "reference_audios": [{"asset_id": ID_B, "description": "  "}]},
        )
    with pytest.raises(ValueError, match="不能重复"):
        _parse(
            PlaygroundCapability.VIDEO_REF2VA,
            {**base, "reference_audios": [_described(ID_B), _described(ID_B)]},
        )


def test_ref2va_labels_match_production_mapping() -> None:
    parameters = _parse(
        PlaygroundCapability.VIDEO_REF2VA,
        {
            **SAMPLES[PlaygroundCapability.VIDEO_REF2VA],
            "last_frame_asset_id": ID_B,
            "additional_images": [_described(ID_C, "角色正面"), _described(ID_D, "道具特写")],
            "reference_audios": [_described(ID_A, "音色参考"), _described(ID_B, "对白")],
            "reference_videos": [_described(ID_C, "运镜参考")],
        },
    )
    labels = ref2va_input_labels(parameters)
    context = H3PromptContext(
        mode=H3PromptMode.REF2VA,
        duration_seconds=8.0,
        aspect_ratio="16:9",
        scene_title="雨夜",
        scene_setting="街道",
        shots=(
            H3ShotInput(
                composition="中景",
                camera_movement="推近",
                action="等待",
                audio_direction="雨声",
                visible_character_names=("小满",),
            ),
        ),
        segment_action="上车",
        historical_prompt="",
        user_direction="",
        start_frame_description="首帧描述",
        end_frame_description="尾帧描述",
        dialogue=(),
        additional_image_descriptions=("角色正面", "道具特写"),
        audio_reference_descriptions=("音色参考", "对白"),
        video_reference_descriptions=("运镜参考",),
    )
    # Playground 没有 Scene，单 Shot 也走同一个 shots 列表。
    payload = h3_prompt_payload(context)
    assert payload["scene"]["driver"] is None
    assert payload["shots"] == [
        {
            "composition": "中景",
            "camera_movement": "推近",
            "action": "等待",
            "audio_direction": "雨声",
            "visible_character_names": ["小满"],
        }
    ]
    provider = _actual_provider_inputs(context)
    assert [item["label"] for item in labels if item["label"].startswith("<Picture")] == [
        item["label"] for item in provider["pictures"]
    ]
    assert [item["label"] for item in labels if item["label"].startswith("<Audio")] == [
        item["label"] for item in provider["audios"]
    ]
    assert [item["label"] for item in labels if item["label"].startswith("<Video")] == [
        item["label"] for item in provider["videos"]
    ]
    assert [item["label"] for item in labels] == provider["allowed_asset_reference_labels"]

    last_only = _parse(
        PlaygroundCapability.VIDEO_REF2VA,
        {
            **SAMPLES[PlaygroundCapability.VIDEO_REF2VA],
            "first_frame_asset_id": None,
            "last_frame_asset_id": ID_B,
        },
    )
    assert [item["label"] for item in ref2va_input_labels(last_only)] == ["<Picture 1>"]


def _reader(*assets: tuple[PlaygroundAsset, bytes]):
    table = {asset.id: (asset, content) for asset, content in assets}

    def read(asset_id: str) -> tuple[PlaygroundAsset, bytes]:
        if asset_id not in table:
            raise FileNotFoundError("Asset 不存在。")
        return table[asset_id]

    return read


def test_resolve_request_builds_production_shaped_fl2va(wav_bytes: bytes) -> None:
    image = _asset(ID_A, "image/png", duration=None, label="雨夜街道")
    request = _resolve(
        PlaygroundCapability.VIDEO_FL2VA,
        SAMPLES[PlaygroundCapability.VIDEO_FL2VA],
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((image, PNG)),
    )
    provider_request = request.provider_request
    assert isinstance(provider_request, FL2VARequest)
    # 未装配全局设置时使用默认组合：720p、20 步、Sage、SelfLift。
    assert (provider_request.width, provider_request.height) == (1280, 704)
    assert provider_request.save_audio is True
    assert (provider_request.steps, provider_request.sage_attention, provider_request.selflift) == (
        20,
        True,
        True,
    )
    assert provider_request.cfg == FL2VARequest.__dataclass_fields__["cfg"].default
    assert request.submit_method == "submit_recipe"
    assert request.source_assets == (image,)

    portrait = _resolve(
        PlaygroundCapability.VIDEO_FL2VA,
        {**SAMPLES[PlaygroundCapability.VIDEO_FL2VA], "aspect_ratio": "9:16"},
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((image, PNG)),
    ).provider_request
    assert isinstance(portrait, FL2VARequest)
    assert (portrait.width, portrait.height) == (704, 1280)

    wide = _resolve(
        PlaygroundCapability.VIDEO_FL2VA,
        {**SAMPLES[PlaygroundCapability.VIDEO_FL2VA], "aspect_ratio": "2:1"},
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((image, PNG)),
    ).provider_request
    assert isinstance(wide, FL2VARequest)
    assert (wide.width, wide.height) == (1408, 704)

    turbo = _resolve(
        PlaygroundCapability.VIDEO_FL2VA,
        SAMPLES[PlaygroundCapability.VIDEO_FL2VA],
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((image, PNG)),
        h3_render=H3RenderSettings(H3Resolution.P480, 8, False, False),
    ).provider_request
    assert isinstance(turbo, FL2VARequest)
    assert (turbo.width, turbo.height, turbo.steps) == (864, 480, 8)
    assert (turbo.sage_attention, turbo.selflift) == (False, False)


def test_resolve_request_builds_ref2va_with_labels(wav_bytes: bytes) -> None:
    image = _asset(ID_A, "image/png", duration=None, label="首帧")
    audio = _asset(ID_B, "audio/wav", duration=3.0, label="音色")
    video = _asset(ID_C, "video/mp4", duration=4.0, label="运镜")
    parameters = _parse(
        PlaygroundCapability.VIDEO_REF2VA,
        {
            **SAMPLES[PlaygroundCapability.VIDEO_REF2VA],
            "reference_audios": [_described(ID_B, "音色参考")],
            "reference_videos": [_described(ID_C, "运镜参考")],
        },
    )
    request = _resolve(
        PlaygroundCapability.VIDEO_REF2VA,
        parameters,
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((image, PNG), (audio, wav_bytes), (video, real_mp4_bytes(48, 4.0))),
    )
    provider_request = request.provider_request
    assert isinstance(provider_request, Ref2VARequest)
    assert provider_request.save_audio is True
    assert provider_request.width == 1280
    assert len(provider_request.reference_audios) == 1
    assert len(provider_request.reference_videos) == 1
    assert request.source_assets == (image, audio, video)


def test_resolve_request_rejects_reference_video_out_of_window(wav_bytes: bytes) -> None:
    image = _asset(ID_A, "image/png", duration=None, label="首帧")
    short_video = _asset(ID_C, "video/mp4", duration=1.0, label="太短")
    parameters = _parse(
        PlaygroundCapability.VIDEO_REF2VA,
        {
            **SAMPLES[PlaygroundCapability.VIDEO_REF2VA],
            "reference_videos": [_described(ID_C, "运镜参考")],
        },
    )
    with pytest.raises(ValueError, match="2 到 15 秒"):
        _resolve(
            PlaygroundCapability.VIDEO_REF2VA,
            parameters,
            document=PlaygroundDocument(schema_version=2, revision=1),
            read_asset=_reader((image, PNG), (short_video, real_mp4_bytes(24, 1.0))),
        )


def test_resolve_request_rejects_wrong_media_type(wav_bytes: bytes) -> None:
    audio = _asset(ID_A, "audio/wav", duration=1.0, label="音频")
    with pytest.raises(ValueError, match="首帧只接受 image/png、image/jpeg、image/webp。"):
        _resolve(
            PlaygroundCapability.VIDEO_FL2VA,
            SAMPLES[PlaygroundCapability.VIDEO_FL2VA],
            document=PlaygroundDocument(schema_version=2, revision=1),
            read_asset=_reader((audio, wav_bytes)),
        )
    with pytest.raises(ValueError, match="参数引用的 Asset 不存在"):
        _resolve(
            PlaygroundCapability.VIDEO_FL2VA,
            SAMPLES[PlaygroundCapability.VIDEO_FL2VA],
            document=PlaygroundDocument(schema_version=2, revision=1),
            read_asset=_reader(),
        )


def test_resolve_request_builds_image_requests() -> None:
    first = _asset(ID_A, "image/png", duration=None, label="底图")
    second = _asset(ID_B, "image/png", duration=None, label="参考")
    generated = _resolve(
        PlaygroundCapability.IMAGE_GENERATE,
        {**SAMPLES[PlaygroundCapability.IMAGE_GENERATE], "reference_image_asset_ids": [ID_B]},
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((first, PNG), (second, PNG + b"reference")),
    )
    assert isinstance(generated.provider_request, RecipeRequest)
    assert generated.submit_method == "submit_recipe"
    assert to_generate_request(generated.provider_request).model == "gpt-5.6-terra"

    edited = _resolve(
        PlaygroundCapability.IMAGE_EDIT,
        SAMPLES[PlaygroundCapability.IMAGE_EDIT],
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((first, PNG), (second, PNG + b"reference")),
    )
    assert edited.submit_method == "submit_recipe"


def test_extract_frame_index_out_of_range() -> None:
    video = _asset(ID_A, "video/mp4", duration=2.0, label="来源")
    request = _resolve(
        PlaygroundCapability.VIDEO_EXTRACT_FRAME,
        {**SAMPLES[PlaygroundCapability.VIDEO_EXTRACT_FRAME], "frame_index": 47},
        document=PlaygroundDocument(schema_version=2, revision=1),
        read_asset=_reader((video, real_mp4_bytes(48, 2.0))),
    )
    assert isinstance(request.provider_request, VideoFrameRequest)
    assert request.provider_request.frame_index == 47
    with pytest.raises(ValueError, match="帧号超出范围 0-47。"):
        _resolve(
            PlaygroundCapability.VIDEO_EXTRACT_FRAME,
            {**SAMPLES[PlaygroundCapability.VIDEO_EXTRACT_FRAME], "frame_index": 48},
            document=PlaygroundDocument(schema_version=2, revision=1),
            read_asset=_reader((video, real_mp4_bytes(48, 2.0))),
        )


def test_local_capabilities_have_no_provider_request() -> None:
    audio = _asset(ID_A, "audio/wav", duration=4.0, label="旁白")
    for capability in (PlaygroundCapability.AUDIO_EFFECT, PlaygroundCapability.AUDIO_TRIM):
        request = _resolve(
            capability,
            SAMPLES[capability],
            document=PlaygroundDocument(schema_version=2, revision=1),
            read_asset=_reader((audio, b"RIFF____WAVE")),
        )
        assert request.provider_request is None
        assert request.submit_method == ""
        assert request.source_assets == (audio,)


def test_input_asset_ids_order_and_dedupe() -> None:
    parameters = _parse(
        PlaygroundCapability.VIDEO_REF2VA,
        {
            **SAMPLES[PlaygroundCapability.VIDEO_REF2VA],
            "first_frame_asset_id": ID_C,
            "last_frame_asset_id": ID_B,
            "additional_images": [_described(ID_A)],
        },
    )
    assert input_asset_ids(PlaygroundCapability.VIDEO_REF2VA, parameters) == (ID_C, ID_B, ID_A)

    deduped = _parse(
        PlaygroundCapability.AUDIO_REMIX,
        {**SAMPLES[PlaygroundCapability.AUDIO_REMIX], "background_asset_id": ID_B},
    )
    assert input_asset_ids(PlaygroundCapability.AUDIO_REMIX, deduped) == (ID_A, ID_B)

    assert (
        parameter_seed(PlaygroundCapability.AUDIO_TRIM, SAMPLES[PlaygroundCapability.AUDIO_TRIM])
        is None
    )
    assert (
        parameter_seed(PlaygroundCapability.VIDEO_FL2VA, SAMPLES[PlaygroundCapability.VIDEO_FL2VA])
        == 1234
    )


def test_effect_preset_must_be_known() -> None:
    with pytest.raises(ValueError, match="preset"):
        _parse(
            PlaygroundCapability.AUDIO_EFFECT,
            {**SAMPLES[PlaygroundCapability.AUDIO_EFFECT], "preset": "nope"},
        )
    with pytest.raises(ValueError, match="0 到 1"):
        _parse(
            PlaygroundCapability.AUDIO_EFFECT,
            {**SAMPLES[PlaygroundCapability.AUDIO_EFFECT], "strength": 1.5},
        )


def test_audio_gain_windows_and_ranges() -> None:
    base = SAMPLES[PlaygroundCapability.AUDIO_REMIX]
    with pytest.raises(ValueError, match="同时提供或同时省略"):
        _parse(
            PlaygroundCapability.AUDIO_REMIX,
            {**base, "voice_gain_start_seconds": 1.0, "voice_gain_end_seconds": None},
        )
    with pytest.raises(ValueError, match="-100 到 24"):
        _parse(PlaygroundCapability.AUDIO_REMIX, {**base, "voice_gain_db": 30.0})
    with pytest.raises(ValueError, match="时间范围不合法"):
        _parse(
            PlaygroundCapability.AUDIO_REMIX,
            {
                **base,
                "voice_gain_start_seconds": 2.0,
                "voice_gain_end_seconds": 2.0,
            },
        )
    with pytest.raises(ValueError, match="0 ≤ start < end"):
        _parse(
            PlaygroundCapability.AUDIO_TRIM,
            {**SAMPLES[PlaygroundCapability.AUDIO_TRIM], "end_seconds": 0.5},
        )


def test_source_must_not_repeat_in_image_edit() -> None:
    with pytest.raises(ValueError, match="不能.*重复"):
        _parse(
            PlaygroundCapability.IMAGE_EDIT,
            {**SAMPLES[PlaygroundCapability.IMAGE_EDIT], "reference_image_asset_ids": [ID_A]},
        )


def test_run_output_labels_follow_capability_naming() -> None:
    document = PlaygroundDocument(schema_version=2, revision=1)
    run_id = "5c9e1a2b3c4d5e6f708192a3b4c5d6e7"
    assert (
        run_output_label(
            PlaygroundCapability.VIDEO_FL2VA,
            SAMPLES[PlaygroundCapability.VIDEO_FL2VA],
            run_id=run_id,
            document=document,
            recipe=_recipe(PlaygroundCapability.VIDEO_FL2VA),
        )
        == "FL2VA-5c9e1a2b"
    )
    upscale = run_output_label(
        PlaygroundCapability.VIDEO_UPSCALE,
        SAMPLES[PlaygroundCapability.VIDEO_UPSCALE],
        run_id=run_id,
        document=document,
        recipe=_recipe(PlaygroundCapability.VIDEO_UPSCALE),
    )
    assert upscale == "720p 超分-5c9e1a2b"

    asset = _asset(ID_A, "video/mp4", duration=2.0, label="镜头")
    named = run_output_label(
        PlaygroundCapability.VIDEO_EXTRACT_FRAME,
        SAMPLES[PlaygroundCapability.VIDEO_EXTRACT_FRAME],
        run_id=run_id,
        document=replace(document, assets=(asset,)),
    )
    assert named == "镜头-第0帧"


def test_pano_view_schema_reuses_contract_ranges() -> None:
    from core.model_providers.contracts import (
        PANO_HFOV_RANGE,
        PANO_PITCH_RANGE,
        PANO_YAW_RANGE,
    )

    properties = PARAMETER_SCHEMAS[PlaygroundCapability.IMAGE_PANO_VIEW]["properties"]
    assert (properties["yaw_deg"]["minimum"], properties["yaw_deg"]["exclusiveMaximum"]) == (
        PANO_YAW_RANGE
    )
    assert (properties["pitch_deg"]["minimum"], properties["pitch_deg"]["maximum"]) == (
        PANO_PITCH_RANGE
    )
    assert (properties["hfov_deg"]["minimum"], properties["hfov_deg"]["maximum"]) == (
        PANO_HFOV_RANGE
    )
    assert properties["aspect_ratio"]["enum"] == ["16:9", "9:16", "2:1"]
    spec = CAPABILITY_SPECS[PlaygroundCapability.IMAGE_PANO_VIEW]
    assert (spec.group, spec.execution, spec.registry_capability) == ("image", "async", "pano_view")


def test_pano_view_parameters_normalize_and_reject_invalid() -> None:
    sample = SAMPLES[PlaygroundCapability.IMAGE_PANO_VIEW]
    parsed = _parse(
        PlaygroundCapability.IMAGE_PANO_VIEW,
        {**sample, "yaw_deg": 0, "pitch_deg": -60, "hfov_deg": 120},
    )
    assert parsed == {
        "image_asset_id": ID_A,
        "yaw_deg": 0.0,
        "pitch_deg": -60.0,
        "hfov_deg": 120.0,
        "aspect_ratio": "16:9",
    }
    assert _parse(PlaygroundCapability.IMAGE_PANO_VIEW, {**sample, "yaw_deg": 359.9})[
        "yaw_deg"
    ] == pytest.approx(359.9)
    missing = {key: value for key, value in sample.items() if key != "hfov_deg"}
    with pytest.raises(ValueError, match="缺少 hfov_deg"):
        _parse(PlaygroundCapability.IMAGE_PANO_VIEW, missing)
    with pytest.raises(ValueError, match="多出 roll_deg"):
        _parse(PlaygroundCapability.IMAGE_PANO_VIEW, {**sample, "roll_deg": 0})
    for key, value, message in (
        ("yaw_deg", 360, r"yaw 必须在 \[0, 360\)"),
        ("yaw_deg", -0.1, r"yaw 必须在 \[0, 360\)"),
        ("pitch_deg", 60.5, r"pitch 必须在 \[-60, 60\]"),
        ("pitch_deg", -61, r"pitch 必须在 \[-60, 60\]"),
        ("hfov_deg", 19.9, r"水平视场角必须在 \[20, 120\]"),
        ("hfov_deg", 121, r"水平视场角必须在 \[20, 120\]"),
        ("aspect_ratio", "4:3", "画幅只允许"),
        ("aspect_ratio", ["16:9"], "画幅只允许"),
        ("yaw_deg", True, "yaw_deg 必须是有限数字"),
        ("pitch_deg", "0", "pitch_deg 必须是有限数字"),
        ("image_asset_id", "x", "32 位十六进制"),
    ):
        with pytest.raises(ValueError, match=message):
            _parse(PlaygroundCapability.IMAGE_PANO_VIEW, {**sample, key: value})


def test_pano_view_resolve_requires_two_to_one_panorama() -> None:
    from core.model_providers.contracts import PanoViewRequest
    from tests.playground_fixtures import png_header_bytes

    document = PlaygroundDocument(schema_version=2, revision=1)
    image = _asset(ID_A, "image/png", duration=None, label="全景")
    parameters = _parse(
        PlaygroundCapability.IMAGE_PANO_VIEW, SAMPLES[PlaygroundCapability.IMAGE_PANO_VIEW]
    )
    resolved = _resolve(
        PlaygroundCapability.IMAGE_PANO_VIEW,
        parameters,
        document=document,
        read_asset=_reader((image, png_header_bytes(2048, 1024))),
    )
    assert resolved.submit_method == "submit"
    assert resolved.source_assets == (image,)
    request = resolved.provider_request
    assert isinstance(request, PanoViewRequest)
    assert (request.yaw_deg, request.pitch_deg, request.hfov_deg, request.aspect_ratio) == (
        90.0,
        0.0,
        90.0,
        "16:9",
    )
    for content in (png_header_bytes(2048, 1152), png_header_bytes(1000, 500), PNG):
        with pytest.raises(ValueError, match="2:1 等距柱状图"):
            _resolve(
                PlaygroundCapability.IMAGE_PANO_VIEW,
                parameters,
                document=document,
                read_asset=_reader((image, content)),
            )
    audio = _asset(ID_A, "audio/wav", duration=1.0, label="音频")
    with pytest.raises(ValueError, match="image_asset_id 必须是图片"):
        _resolve(
            PlaygroundCapability.IMAGE_PANO_VIEW,
            parameters,
            document=document,
            read_asset=_reader((audio, b"RIFF")),
        )


def test_pano_view_output_label_names_source_and_yaw() -> None:
    document = PlaygroundDocument(
        schema_version=2,
        revision=1,
        assets=(_asset(ID_A, "image/png", duration=None, label="客厅全景"),),
    )
    run_id = "5c9e1a2b3c4d5e6f708192a3b4c5d6e7"
    for yaw, expected in ((90.0, "yaw90"), (0.0, "yaw0"), (187.5, "yaw187.5")):
        label = run_output_label(
            PlaygroundCapability.IMAGE_PANO_VIEW,
            {**SAMPLES[PlaygroundCapability.IMAGE_PANO_VIEW], "yaw_deg": yaw},
            run_id=run_id,
            document=document,
        )
        assert label == f"客厅全景-全景裁切-{expected}"
