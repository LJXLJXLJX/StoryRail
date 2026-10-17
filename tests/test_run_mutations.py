"""run 生命周期 mutations characterization（P2-C3）。

补齐 run 守卫负例的逐字消息锁定：recovery/oracle O2 测试锁定状态机正例与
恢复语义，但 18 条守卫错误消息此前无任何测试锁定。
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from core.director_commands import CommandReceipt
from core.structured_director.models import (
    DirectorAuthorization,
    DirectorRun,
    DirectorRunCursor,
    DirectorRunKind,
    DirectorRunStatus,
    GenerationOperation,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    WorkspaceLayers,
)
from core.structured_director.mutations import run as _mutations_pkg
from core.structured_director.schema import PROJECT_SCHEMA_VERSION

_run = _mutations_pkg

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32


def _run_fixture(
    run_id: str = ID_B,
    *,
    status: DirectorRunStatus = DirectorRunStatus.RUNNING,
    step: int = 1,
    waiting_generation_ids: tuple[str, ...] = (),
) -> DirectorRun:
    return DirectorRun(
        id=run_id,
        kind=DirectorRunKind.KEYFRAME_PLAN,
        goal="目标",
        status=status,
        waiting_reason=(
            "等待"
            if status in {DirectorRunStatus.WAITING_USER, DirectorRunStatus.WAITING_JOBS}
            else None
        ),
        authorization=DirectorAuthorization((), (), "disabled", False),
        cursor=DirectorRunCursor(step, (), waiting_generation_ids),
        completed_command_ids=(),
        command_receipts=(),
        last_project_revision=1,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )


def _document(
    run: DirectorRun, generations: tuple = (), assets: tuple = ()
) -> StructuredDirectorDocument:
    return StructuredDirectorDocument(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=ID_A,
        revision=3,
        title="run 校验",
        aspect_ratio=__import__(
            "core.project_settings", fromlist=["ProjectAspectRatio"]
        ).ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案",
        status=StructuredDirectorStatus.REVIEWING,
        workspace_layers=WorkspaceLayers(),
        reference_library=__import__(
            "core.structured_director.models", fromlist=["ReferenceLibrary"]
        ).ReferenceLibrary(),
        assets=assets,
        generations=generations,
        director_runs=(run,),
        narration_languages=tuple(NarrationLanguage),
    )


def _generation(generation_id: str, phase: ReferenceGenerationPhase) -> ReferenceGeneration:
    return ReferenceGeneration(
        id=generation_id,
        kind=ReferenceGenerationKind.KEYFRAME_IMAGE,
        operation=GenerationOperation.GENERATE,
        target_id="e" * 32,
        phase=phase,
        progress=1.0,
        message="",
        prompt_text="提示词",
        input_asset_ids=(),
        sample_text=None,
        seed=None,
        plugin_id="test.image",
        plugin_version=1,
        external_id="e",
        output_asset_id="f" * 32 if phase is ReferenceGenerationPhase.SUCCEEDED else None,
        error_code="submission_rejected" if phase is ReferenceGenerationPhase.FAILED else None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=None,
        dismissed=False,
    )


NOW = "2024-06-01T00:00:00+00:00"


def _expect(fn, expected: str, **kwargs):
    with pytest.raises(ValueError, match=re.escape(expected)):
        fn(**kwargs)


def test_set_director_run_cursor_guards():
    document = _document(_run_fixture())
    _expect(
        lambda **kw: _run.set_director_run_cursor(document, **kw),
        "Director run 不存在或当前不能更新 cursor。",
        run_id="0" * 32,
        cursor=DirectorRunCursor(2, (), ()),
        now=NOW,
    )
    _expect(
        lambda **kw: _run.set_director_run_cursor(document, **kw),
        "Director run cursor 不能回退。",
        run_id=ID_B,
        cursor=DirectorRunCursor(0, (), ()),
        now=NOW,
    )
    _expect(
        lambda **kw: _run.set_director_run_cursor(document, **kw),
        "运行中的 Director run cursor 不能保存等待 Generation。",
        run_id=ID_B,
        cursor=DirectorRunCursor(2, (), (ID_C,)),
        now=NOW,
    )


def test_record_director_run_progress_guards():
    document = _document(_run_fixture())
    receipt = CommandReceipt("cmd-1", "succeeded", 1, 2, decision_summary="完成。")
    _expect(
        lambda **kw: _run.record_director_run_progress(document, **kw),
        "Director run 不存在。",
        run_id="0" * 32,
        cursor=DirectorRunCursor(2, (), ()),
        receipt=receipt,
        now=NOW,
    )
    failed = _document(_run_fixture(status=DirectorRunStatus.FAILED))
    _expect(
        lambda **kw: _run.record_director_run_progress(failed, **kw),
        "失败或已取消的 Director run 不能追加 receipt。",
        run_id=ID_B,
        cursor=DirectorRunCursor(2, (), ()),
        receipt=receipt,
        now=NOW,
    )
    _expect(
        lambda **kw: _run.record_director_run_progress(document, **kw),
        "Director run cursor 不能回退。",
        run_id=ID_B,
        cursor=DirectorRunCursor(0, (), ()),
        receipt=receipt,
        now=NOW,
    )
    _expect(
        lambda **kw: _run.record_director_run_progress(document, **kw),
        "Director receipt 引用了尚未提交的 project revision。",
        run_id=ID_B,
        cursor=DirectorRunCursor(2, (), ()),
        receipt=CommandReceipt("cmd-1", "succeeded", 1, 99, decision_summary="完成。"),
        now=NOW,
    )
    # 幂等回放：相同内容返回 already_recorded=True，且不产生变更。
    recorded, already = _run.record_director_run_progress(
        document,
        run_id=ID_B,
        cursor=DirectorRunCursor(2, (), ()),
        receipt=receipt,
        now=NOW,
    )
    assert already is False and recorded.revision == 4
    replay, already = _run.record_director_run_progress(
        recorded,
        run_id=ID_B,
        cursor=DirectorRunCursor(2, (), ()),
        receipt=receipt,
        now=NOW,
    )
    assert already is True and replay is recorded
    _expect(
        lambda **kw: _run.record_director_run_progress(recorded, **kw),
        "同一 command_id 的 Director receipt 内容不一致。",
        run_id=ID_B,
        cursor=DirectorRunCursor(2, (), ()),
        receipt=CommandReceipt("cmd-1", "failed", 1, 2, decision_summary="完成。"),
        now=NOW,
    )


def test_wait_director_run_guards():
    document = _document(_run_fixture())
    _expect(
        lambda **kw: _run.wait_director_run(document, **kw),
        "Director run 不存在或当前不能暂停。",
        run_id="0" * 32,
        status=DirectorRunStatus.WAITING_USER,
        reason="等待",
        now=NOW,
    )
    _expect(
        lambda **kw: _run.wait_director_run(document, **kw),
        "Director run 只能暂停为 waiting_user 或 waiting_jobs。",
        run_id=ID_B,
        status=DirectorRunStatus.RUNNING,
        reason="等待",
        now=NOW,
    )
    _expect(
        lambda **kw: _run.wait_director_run(document, **kw),
        "waiting_user 不能绑定 Generation。",
        run_id=ID_B,
        status=DirectorRunStatus.WAITING_USER,
        reason="等待",
        waiting_generation_ids=(ID_C,),
        now=NOW,
    )
    _expect(
        lambda **kw: _run.wait_director_run(document, **kw),
        "waiting_jobs 必须绑定至少一个 Generation。",
        run_id=ID_B,
        status=DirectorRunStatus.WAITING_JOBS,
        reason="等待",
        now=NOW,
    )
    _expect(
        lambda **kw: _run.wait_director_run(document, **kw),
        "waiting_jobs 引用了不存在的 Generation。",
        run_id=ID_B,
        status=DirectorRunStatus.WAITING_JOBS,
        reason="等待",
        waiting_generation_ids=(ID_C,),
        now=NOW,
    )
    terminal = _document(
        _run_fixture(),
        generations=(_generation(ID_C, ReferenceGenerationPhase.SUCCEEDED),),
        assets=(
            __import__("core.structured_director.models", fromlist=["Asset"]).Asset(
                "f" * 32, "image/png", 12, "f" * 64, "assets/images/library/out.png"
            ),
        ),
    )
    _expect(
        lambda **kw: _run.wait_director_run(terminal, **kw),
        "指定 Generation 已全部结束，无需进入 waiting_jobs。",
        run_id=ID_B,
        status=DirectorRunStatus.WAITING_JOBS,
        reason="等待",
        waiting_generation_ids=(ID_C,),
        now=NOW,
    )


def test_resume_director_run_guards():
    document = _document(_run_fixture())
    _expect(
        lambda **kw: _run.resume_director_run(document, **kw),
        "Director run 当前不在等待状态。",
        run_id=ID_B,
        raw_user_request=None,
        now=NOW,
        new_directive_id="d1",
    )
    waiting = _document(_run_fixture(status=DirectorRunStatus.WAITING_USER))
    _expect(
        lambda **kw: _run.resume_director_run(waiting, **kw),
        "waiting_user run 需要新的用户指令才能恢复。",
        run_id=ID_B,
        raw_user_request="  ",
        now=NOW,
        new_directive_id="d1",
    )
    waiting_jobs = _document(
        _run_fixture(status=DirectorRunStatus.WAITING_JOBS, waiting_generation_ids=(ID_C,)),
        generations=(_generation(ID_C, ReferenceGenerationPhase.RUNNING),),
    )
    _expect(
        lambda **kw: _run.resume_director_run(waiting_jobs, **kw),
        "仍有 Provider Generation 未结束。",
        run_id=ID_B,
        raw_user_request=None,
        now=NOW,
        new_directive_id="d1",
    )


def test_wait_resume_cancel_round_trip():
    document = _document(
        _run_fixture(), generations=(_generation(ID_C, ReferenceGenerationPhase.RUNNING),)
    )
    waiting = _run.wait_director_run(
        document,
        run_id=ID_B,
        status=DirectorRunStatus.WAITING_JOBS,
        reason="生成中",
        waiting_generation_ids=(ID_C,),
        now=NOW,
    )
    assert waiting.active_director_run.status is DirectorRunStatus.WAITING_JOBS
    done = replace(
        waiting,
        generations=(_generation(ID_C, ReferenceGenerationPhase.SUCCEEDED),),
        assets=(
            __import__("core.structured_director.models", fromlist=["Asset"]).Asset(
                "f" * 32, "image/png", 12, "f" * 64, "assets/images/library/out.png"
            ),
        ),
    )
    resumed = _run.resume_director_run(
        done, run_id=ID_B, raw_user_request=None, now=NOW, new_directive_id="d1"
    )
    assert resumed.active_director_run.status is DirectorRunStatus.RUNNING
    cancelled = _run.cancel_director_run(resumed, run_id=ID_B, now=NOW)
    assert cancelled.active_director_run is None
    _expect(
        lambda **kw: _run.cancel_director_run(cancelled, **kw),
        "Director run 不存在或已经结束。",
        run_id=ID_B,
        now=NOW,
    )
