"""PG1-T4：Playground run 生命周期与项目侧语义逐项对齐。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.model_providers.boundary import ModelProviderError
from core.playground.lifecycle import (
    RUN_TRANSITIONS,
    link_retry,
    recover_interrupted,
    run_recovery,
    submission_failure,
    transition_run,
    update_run_durable,
    utc_timestamp,
)
from core.playground.models import PlaygroundDocument, PlaygroundRun, RunPhase, canonical_json
from core.structured_director.generation_lifecycle import (
    _generation_recovery,
    _submission_failure,
)
from core.structured_director.models import (
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)
from core.structured_director.models.generation import _GENERATION_TRANSITIONS
from tests.playground_recipes import PlaygroundCapability, recipe_for

TS = "2026-09-28T03:12:45.123456+00:00"
RUN_ID = "5c9e1a2b3c4d5e6f708192a3b4c5d6e7"
OTHER_RUN_ID = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
CAPABILITY_LABEL = "首尾帧视频"


def make_run(**overrides) -> PlaygroundRun:
    values: dict[str, object] = {
        "id": RUN_ID,
        "capability": PlaygroundCapability.VIDEO_FL2VA,
        "phase": RunPhase.QUEUED,
        "progress": 0.0,
        "message": "首尾帧视频任务已提交。",
        "parameters_json": canonical_json(
            {
                "prompt": "雨夜街道",
                "aspect_ratio": "16:9",
                "duration_seconds": 6.0,
                "seed": 1234,
                "first_frame_asset_id": "9" * 32,
                "last_frame_asset_id": None,
            }
        ),
        "input_asset_ids": ("9" * 32,),
        "seed": 1234,
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


def project_generation(
    *,
    phase: ReferenceGenerationPhase = ReferenceGenerationPhase.QUEUED,
    error_code: str | None = None,
    cancellation_requested: bool = False,
) -> ReferenceGeneration:
    """构造一个通过项目侧全部校验的 Generation，用于对照 recovery 形状。"""
    succeeded = phase is ReferenceGenerationPhase.SUCCEEDED
    has_handle = phase in {
        ReferenceGenerationPhase.QUEUED,
        ReferenceGenerationPhase.RUNNING,
        ReferenceGenerationPhase.SUCCEEDED,
        ReferenceGenerationPhase.CANCELLED,
    } or (phase is ReferenceGenerationPhase.FAILED and error_code != "submission_rejected")
    return ReferenceGeneration(
        id=RUN_ID,
        kind=ReferenceGenerationKind.SEGMENT_VIDEO,
        operation=GenerationOperation.ATTACH,
        target_id="b" * 32,
        phase=phase,
        progress=1.0 if succeeded else 0.0,
        message="",
        prompt_text="提示词",
        input_asset_ids=(),
        sample_text=None,
        seed=None,
        plugin_id="test.provider" if has_handle else None,
        plugin_version=1 if has_handle else None,
        external_id="external-1" if has_handle else None,
        output_asset_id="9" * 32 if succeeded else None,
        error_code=error_code,
        cancellation_requested=cancellation_requested,
        retry_of=None,
        duration_seconds=6.0,
        dismissed=False,
        created_at=None,
        updated_at=None,
        video_frame_request=None,
        video_input_snapshot=None,
    )


def test_transition_table_matches_project() -> None:
    assert set(RUN_TRANSITIONS) == set(_GENERATION_TRANSITIONS)
    for phase, targets in _GENERATION_TRANSITIONS.items():
        playground_phase = RunPhase(phase.value)
        assert {item.value for item in RUN_TRANSITIONS[playground_phase]} == {
            item.value for item in targets
        }


@pytest.mark.parametrize(
    "exc",
    [
        ModelProviderError("external_error", "服务拒绝"),
        ModelProviderError("invalid_response", "响应格式不符"),
        ModelProviderError("transport_error", "网络中断"),
        RuntimeError("插件内部错误"),
    ],
)
def test_submission_failure_matches_project_classification(exc: Exception) -> None:
    project = _submission_failure(
        project_generation(phase=ReferenceGenerationPhase.SUBMITTING),
        exc,
        capability=CAPABILITY_LABEL,
    )
    playground = submission_failure(
        make_run(phase=RunPhase.SUBMITTING, external_id=None, plugin_id=None, plugin_version=None),
        exc,
        capability_label=CAPABILITY_LABEL,
    )
    assert playground.phase.value == project.phase.value
    assert playground.error_code == project.error_code
    assert playground.message == project.message


@pytest.mark.parametrize(
    ("phase", "error_code", "cancellation_requested"),
    [
        (RunPhase.SUBMITTING, None, False),
        (RunPhase.QUEUED, None, False),
        (RunPhase.RUNNING, None, False),
        (RunPhase.SUCCEEDED, None, False),
        (RunPhase.FAILED, "provider_error", False),
        (RunPhase.FAILED, "submission_rejected", False),
        (RunPhase.FAILED, "artifact_import_failed", False),
        (RunPhase.CANCELLED, None, True),
        (RunPhase.SUBMISSION_UNCERTAIN, "transport_error", False),
    ],
)
def test_recovery_shape_matches_project(
    phase: RunPhase, error_code: str | None, cancellation_requested: bool
) -> None:
    playground = make_run(
        phase=phase,
        progress=1.0 if phase is RunPhase.SUCCEEDED else 0.0,
        error_code=error_code,
        cancellation_requested=cancellation_requested,
        output_asset_id="9" * 32 if phase is RunPhase.SUCCEEDED else None,
        result_json=None,
    )
    project = project_generation(
        phase=ReferenceGenerationPhase(phase.value),
        error_code=error_code,
        cancellation_requested=cancellation_requested,
    )
    assert run_recovery(playground) == _generation_recovery(project)


def test_transition_run_overwrites_error_code_and_output() -> None:
    run = make_run(phase=RunPhase.RUNNING, error_code="provider_unreachable")
    moved = transition_run(run, RunPhase.RUNNING, message="仍在生成。")
    assert moved.error_code is None
    assert moved.message == "仍在生成。"
    with pytest.raises(ValueError, match="不能从 failed 迁移到 running"):
        transition_run(
            make_run(phase=RunPhase.FAILED, error_code="provider_error"), RunPhase.RUNNING
        )
    with pytest.raises(ValueError, match="不能从 succeeded 迁移到 running"):
        transition_run(
            make_run(phase=RunPhase.SUCCEEDED, progress=1.0, output_asset_id="9" * 32),
            RunPhase.RUNNING,
        )


def test_link_retry_auto_links_same_signature_after_failure() -> None:
    failed = make_run(id=RUN_ID, phase=RunPhase.FAILED, error_code="provider_error")
    candidate = make_run(id=OTHER_RUN_ID, phase=RunPhase.SUBMITTING, external_id=None)
    document = PlaygroundDocument(schema_version=1, revision=2, runs=(failed,))

    linked = link_retry(document, candidate, None)
    assert linked.retry_of == RUN_ID

    different = make_run(
        id=OTHER_RUN_ID,
        phase=RunPhase.SUBMITTING,
        external_id=None,
        parameters_json=canonical_json({"prompt": "另一个提示词"}),
    )
    assert link_retry(document, different, None).retry_of is None

    succeeded = make_run(id=RUN_ID, phase=RunPhase.SUCCEEDED, output_asset_id="9" * 32)
    assert (
        link_retry(
            PlaygroundDocument(schema_version=1, revision=2, runs=(succeeded,)),
            candidate,
            None,
        ).retry_of
        is None
    )


def test_link_retry_explicit_rejects_changed_parameters() -> None:
    failed = make_run(id=RUN_ID, phase=RunPhase.FAILED, error_code="provider_error")
    document = PlaygroundDocument(schema_version=1, revision=2, runs=(failed,))
    matching = make_run(id=OTHER_RUN_ID, phase=RunPhase.SUBMITTING, external_id=None)
    assert link_retry(document, matching, failed).retry_of == RUN_ID

    changed = replace(matching, parameters_json=canonical_json({"prompt": "换一个"}))
    with pytest.raises(ValueError, match="参数已变化"):
        link_retry(document, changed, failed)

    missing = make_run(id="c" * 32, phase=RunPhase.SUBMITTING, external_id=None)
    with pytest.raises(ValueError, match="已变化或不存在"):
        link_retry(document, matching, missing)


def test_link_retry_explicit_rejects_dismissed_or_non_retryable() -> None:
    active = make_run(id=RUN_ID, phase=RunPhase.RUNNING)
    with pytest.raises(ValueError, match="只有失败、已取消或提交结果未知"):
        link_retry(
            PlaygroundDocument(schema_version=1, revision=2, runs=(active,)),
            make_run(id=OTHER_RUN_ID, phase=RunPhase.SUBMITTING, external_id=None),
            active,
        )

    dismissed = make_run(
        id=RUN_ID, phase=RunPhase.FAILED, error_code="provider_error", dismissed=True
    )
    with pytest.raises(ValueError, match="已隐藏的实验不能直接重试"):
        link_retry(
            PlaygroundDocument(schema_version=1, revision=2, runs=(dismissed,)),
            make_run(id=OTHER_RUN_ID, phase=RunPhase.SUBMITTING, external_id=None),
            dismissed,
        )


def test_recover_interrupted_marks_submitting_uncertain() -> None:
    document = PlaygroundDocument(
        schema_version=1,
        revision=3,
        runs=(
            make_run(id=RUN_ID, phase=RunPhase.SUBMITTING, external_id=None),
            make_run(id=OTHER_RUN_ID, phase=RunPhase.RUNNING),
        ),
    )
    updated, changed = recover_interrupted(document, timestamp=TS)
    assert changed is True
    assert updated.revision == 4
    recovered = updated.runs[0]
    assert recovered.phase is RunPhase.SUBMISSION_UNCERTAIN
    assert recovered.error_code == "core_restarted_during_submit"
    assert recovered.updated_at == TS
    assert updated.runs[1] == document.runs[1]

    assert recover_interrupted(updated, timestamp=TS) == (updated, False)


def test_update_run_durable_ignores_progress_only_changes() -> None:
    stored = make_run(phase=RunPhase.RUNNING, progress=0.25, message="正在生成。")
    document = PlaygroundDocument(schema_version=1, revision=4, runs=(stored,))

    transient = replace(stored, progress=0.75)
    assert update_run_durable(document, transient, timestamp=TS) == (document, False)

    advanced = replace(
        stored, progress=0.9, message="采样中。", phase=RunPhase.SUCCEEDED, output_asset_id="9" * 32
    )
    updated, changed = update_run_durable(document, advanced, timestamp=TS)
    assert changed is True
    assert updated.revision == 5
    assert updated.runs[0].progress == 0.25
    assert updated.runs[0].message == "采样中。"
    assert updated.runs[0].updated_at == TS

    with pytest.raises(ValueError, match="实验不存在"):
        update_run_durable(document, make_run(id="c" * 32), timestamp=TS)


def test_utc_timestamp_is_timezone_aware() -> None:
    from datetime import datetime

    assert datetime.fromisoformat(utc_timestamp()).utcoffset() is not None
