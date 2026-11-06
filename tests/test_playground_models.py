"""PG1-T2：Playground 领域模型的自洽校验。"""

from __future__ import annotations

import pytest

from core.playground.models import (
    PLAYGROUND_SCHEMA_VERSION,
    AssetOrigin,
    PlaygroundAsset,
    PlaygroundDocument,
    PlaygroundRequestRecord,
    PlaygroundRun,
    RunPhase,
    canonical_json,
)
from tests.playground_recipes import PlaygroundCapability, recipe_for

SHA256 = "9f2c0c3b6a1e4d7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f"
ASSET_ID = SHA256[:32]
RUN_ID = "5c9e1a2b3c4d5e6f708192a3b4c5d6e7"
OTHER_RUN_ID = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
TS = "2026-09-28T03:12:45.123456+00:00"


def make_asset(**overrides) -> PlaygroundAsset:
    values: dict[str, object] = {
        "id": ASSET_ID,
        "media_type": "image/png",
        "byte_count": 1024,
        "sha256": SHA256,
        "relative_path": "assets/images/imported/雨夜街道-9f2c0c3b6a.png",
        "duration_seconds": None,
        "origin": AssetOrigin("imported"),
        "created_at": TS,
    }
    values.update(overrides)
    return PlaygroundAsset(**values)  # type: ignore[arg-type]


def make_run(**overrides) -> PlaygroundRun:
    values: dict[str, object] = {
        "id": RUN_ID,
        "capability": PlaygroundCapability.VIDEO_FL2VA,
        "phase": RunPhase.QUEUED,
        "progress": 0.0,
        "message": "首尾帧视频任务已提交。",
        "parameters_json": canonical_json({"prompt": "雨夜街道"}),
        "input_asset_ids": (),
        "seed": None,
        "plugin_id": "fake_fl2va",
        "plugin_version": 1,
        "external_id": "external-1",
        "output_asset_id": None,
        "result_json": None,
        "error_code": None,
        "cancellation_requested": False,
        "retry_of": None,
        "note": None,
        "dismissed": False,
        "created_at": TS,
        "updated_at": TS,
    }
    values.update(overrides)
    return PlaygroundRun(**values, recipe=recipe_for(values["capability"]))  # type: ignore[arg-type]


def make_sync_run(capability: PlaygroundCapability, **overrides) -> PlaygroundRun:
    values: dict[str, object] = {
        "capability": capability,
        "phase": RunPhase.SUCCEEDED,
        "progress": 1.0,
        "external_id": None,
        "plugin_id": None,
        "plugin_version": None,
    }
    values.update(overrides)
    return make_run(**values)


def test_asset_id_must_match_sha_prefix() -> None:
    with pytest.raises(ValueError, match="sha256 的前 32 位"):
        make_asset(id=OTHER_RUN_ID)


def test_asset_path_directory_must_match_media_type() -> None:
    with pytest.raises(ValueError, match="媒体目录"):
        make_asset(
            media_type="audio/wav",
            relative_path="assets/images/imported/雨夜街道-9f2c0c3b6a.wav",
            duration_seconds=3.0,
        )
    with pytest.raises(ValueError, match="扩展名"):
        make_asset(relative_path="assets/images/imported/雨夜街道-9f2c0c3b6a.jpg")
    with pytest.raises(ValueError, match="relative_path"):
        make_asset(relative_path="assets/other/imported/雨夜街道-9f2c0c3b6a.png")


def test_asset_origin_shapes_are_exact() -> None:
    assert AssetOrigin("imported").run_id is None
    assert AssetOrigin("run_output", run_id=RUN_ID).run_id == RUN_ID
    origin = AssetOrigin("copied_from_project", project_id=RUN_ID, asset_id=ASSET_ID)
    assert origin.project_id == RUN_ID

    with pytest.raises(ValueError, match="imported 形状"):
        AssetOrigin("imported", run_id=RUN_ID)
    with pytest.raises(ValueError, match="run_output 形状"):
        AssetOrigin("run_output")
    with pytest.raises(ValueError, match="run_output 形状"):
        AssetOrigin("run_output", run_id=RUN_ID, asset_id=ASSET_ID)
    with pytest.raises(ValueError, match="copied_from_project 形状"):
        AssetOrigin("copied_from_project", project_id=RUN_ID)
    with pytest.raises(ValueError, match="kind 不受支持"):
        AssetOrigin("unknown")  # type: ignore[arg-type]


def test_media_duration_rules() -> None:
    with pytest.raises(ValueError, match="duration_seconds 不能为空"):
        make_asset(
            media_type="video/mp4",
            relative_path="assets/videos/runs/FL2VA-9f2c0c3b6a.mp4",
            byte_count=1024,
        )
    with pytest.raises(ValueError, match="必须为空"):
        make_asset(duration_seconds=1.0)
    with pytest.raises(ValueError, match="必须大于 0"):
        make_asset(
            media_type="audio/wav",
            relative_path="assets/audio/imported/参考-9f2c0c3b6a.wav",
            duration_seconds=0.0,
        )
    assert (
        make_asset(
            media_type="audio/wav",
            relative_path="assets/audio/imported/参考-9f2c0c3b6a.wav",
            duration_seconds=3.5,
        ).duration_seconds
        == 3.5
    )
    assert make_asset().display_name == "雨夜街道"
    assert make_asset().media_kind == "image"


def test_run_handle_fields_pairing() -> None:
    with pytest.raises(ValueError, match="必须同时存在或同时为空"):
        make_run(plugin_version=None)
    with pytest.raises(ValueError, match="必须同时存在或同时为空"):
        make_run(plugin_id=None)
    with pytest.raises(ValueError, match="必须有 external_id"):
        make_run(external_id=None)
    with pytest.raises(ValueError, match="必须有 external_id"):
        make_run(phase=RunPhase.RUNNING, external_id=None)


def test_sync_run_cannot_have_external_id() -> None:
    with pytest.raises(ValueError, match="同步能力不能有 external_id"):
        make_sync_run(PlaygroundCapability.ASR_TRANSCRIBE, external_id="external-1")


def test_succeeded_output_rules_per_capability() -> None:
    with pytest.raises(ValueError, match="必须有产物"):
        make_run(phase=RunPhase.SUCCEEDED, progress=1.0, output_asset_id=None)
    succeeded = make_run(phase=RunPhase.SUCCEEDED, progress=1.0, output_asset_id=ASSET_ID)
    assert succeeded.output_asset_id == ASSET_ID

    with pytest.raises(ValueError, match="异步能力不能有 result"):
        make_run(
            phase=RunPhase.SUCCEEDED,
            progress=1.0,
            output_asset_id=ASSET_ID,
            result_json=canonical_json({"transcript": "你好"}),
        )
    with pytest.raises(ValueError, match="不产生 Asset 产物"):
        make_sync_run(PlaygroundCapability.ASR_TRANSCRIBE, output_asset_id=ASSET_ID)
    with pytest.raises(ValueError, match="必须有 transcript"):
        make_sync_run(PlaygroundCapability.ASR_TRANSCRIBE, result_json=canonical_json({"x": 1}))
    asr = make_sync_run(
        PlaygroundCapability.ASR_TRANSCRIBE,
        result_json=canonical_json({"transcript": "你好"}),
    )
    assert asr.result == {"transcript": "你好"}

    with pytest.raises(ValueError, match="必须有产物"):
        make_sync_run(
            PlaygroundCapability.AUDIO_TRIM,
            result_json=canonical_json({"duration_seconds": 1.0}),
        )
    with pytest.raises(ValueError, match="本地音频处理必须有 result"):
        make_sync_run(PlaygroundCapability.AUDIO_TRIM, output_asset_id=ASSET_ID)
    trim = make_sync_run(
        PlaygroundCapability.AUDIO_TRIM,
        output_asset_id=ASSET_ID,
        result_json=canonical_json({"duration_seconds": 1.0}),
    )
    assert trim.result == {"duration_seconds": 1.0}


def test_failed_requires_error_code() -> None:
    with pytest.raises(ValueError, match="必须有 error_code"):
        make_run(phase=RunPhase.FAILED, error_code=None)
    failed = make_run(phase=RunPhase.FAILED, error_code="submission_rejected")
    assert failed.error_code == "submission_rejected"


def test_dismissed_only_for_terminal() -> None:
    with pytest.raises(ValueError, match="只有已结束的实验可以被隐藏"):
        make_run(dismissed=True)
    assert make_run(phase=RunPhase.CANCELLED, dismissed=True).dismissed is True
    assert make_run(phase=RunPhase.SUBMISSION_UNCERTAIN, dismissed=True).dismissed is True


def test_note_bounds() -> None:
    assert make_run(note=None).note is None
    assert make_run(note="cfg 默认，镜头推近").note == "cfg 默认，镜头推近"
    assert make_run(note="a" * 200).note is not None
    with pytest.raises(ValueError, match="1 到 200 字符"):
        make_run(note="   ")
    with pytest.raises(ValueError, match="1 到 200 字符"):
        make_run(note="a" * 201)


def test_document_unique_ids_and_retry_reference() -> None:
    asset = make_asset()
    assert PlaygroundDocument(schema_version=PLAYGROUND_SCHEMA_VERSION, revision=1).assets == ()

    with pytest.raises(ValueError, match="assets 的 id 不能重复"):
        PlaygroundDocument(schema_version=1, revision=1, assets=(asset, asset))
    with pytest.raises(ValueError, match="runs 的 id 不能重复"):
        PlaygroundDocument(schema_version=1, revision=1, runs=(make_run(), make_run()))
    with pytest.raises(ValueError, match="retry_of 必须指向已存在的实验"):
        PlaygroundDocument(
            schema_version=1,
            revision=1,
            runs=(make_run(id=OTHER_RUN_ID, retry_of=RUN_ID),),
        )

    retried = make_run(id=OTHER_RUN_ID, retry_of=RUN_ID)
    assert PlaygroundDocument(schema_version=1, revision=2, runs=(make_run(), retried)).runs[1]


def _record(index: int) -> PlaygroundRequestRecord:
    return PlaygroundRequestRecord(
        request_id=f"{index:064x}",
        caller_id="agent-1",
        idempotency_key=f"key-{index}",
        request_digest=f"{index + 1:064x}",
        operation="playground.submit_run",
        receipt_json="{}",
        created_at=TS,
    )


def test_request_record_limit() -> None:
    records = tuple(_record(index) for index in range(1000))
    PlaygroundDocument(schema_version=1, revision=1, application_requests=records)
    with pytest.raises(ValueError, match="最多保留 1000 条"):
        PlaygroundDocument(
            schema_version=1, revision=1, application_requests=(*records, _record(1000))
        )
    with pytest.raises(ValueError, match="request_id 不能重复"):
        PlaygroundDocument(
            schema_version=1, revision=1, application_requests=(_record(1), _record(1))
        )
