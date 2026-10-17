"""Final 域 mutations characterization（P2-C6）。

补齐 final 守卫负例的逐字消息锁定：12 条 L2 守卫消息此前零测试锁定。
Approval 语义正例由 oracle O1 全旅程与 final_scene_assembly 测试锁定。
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from video_recipes import make_video

from core.director_commands import FinalApprovalRequest, FinalCandidateSelection
from core.structured_director.errors import RevisionConflictError
from core.structured_director.models import (
    Asset,
    FinalApproval,
    FinalAssemblyClip,
    FinalAssemblyPlan,
    GenerationOperation,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    WorkspaceLayers,
)
from core.structured_director.mutations import final as _final_module
from core.structured_director.schema import PROJECT_SCHEMA_VERSION

_final = _final_module

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32
ID_E = "e" * 32
ID_F = "f" * 32
SEGMENT_ID = "7" * 32
# 中文成片 Asset ID_C / Generation ID_D；英文成片 Asset ID_E / Generation ID_F。
PLAN = FinalAssemblyPlan(1, (FinalAssemblyClip(ID_B, ID_C, ID_E, None),))
SELECTED = replace(PLAN, selected_zh_asset_id=ID_C, selected_en_asset_id=ID_E)
APPROVED = FinalApproval(ID_C, ID_D, ID_E, ID_F, 1, 3)


def _full_fixture_document(**kw) -> StructuredDirectorDocument:
    """带完整脚本/视频计划的合法 final 域 document。"""
    from core.structured_director.models import (
        DirectorScript,
        Keyframe,
        KeyframePlan,
        Scene,
        SegmentKeyframes,
        Shot,
        ShotSegment,
        VideoPlan,
    )

    shot = Shot("8" * 32, (), "构图", "固定", "动作", "环境声", None)
    segment = ShotSegment(SEGMENT_ID, (shot.id,), 4.0, "动作", (), None)
    scene = Scene(ID_B, "场景", "摘要", "环境", (shot,), (segment,), (), "drama", None)
    script = DirectorScript(1, 1, 1, (scene,), (scene,))
    keyframe_plan = KeyframePlan(
        1,
        (
            Keyframe("9" * 32, SEGMENT_ID, None, "首帧", ()),
            Keyframe("a" * 32, SEGMENT_ID, "9" * 32, "尾帧", ()),
        ),
        (SegmentKeyframes(SEGMENT_ID, "9" * 32, "a" * 32),),
    )
    base = dict(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=ID_A,
        revision=3,
        title="final 校验",
        aspect_ratio=__import__(
            "core.project_settings", fromlist=["ProjectAspectRatio"]
        ).ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案",
        status=StructuredDirectorStatus.REVIEWING_FINAL,
        workspace_layers=WorkspaceLayers(
            narration_unlocked=True,
            keyframes_unlocked=True,
            videos_unlocked=True,
            final_assembly_unlocked=True,
        ),
        reference_library=__import__(
            "core.structured_director.models", fromlist=["ReferenceLibrary"]
        ).ReferenceLibrary(),
        assets=(_mp4_asset(), _mp4_asset(ID_E)),
        director_script=script,
        keyframe_plan=keyframe_plan,
        video_plan=VideoPlan(1, (make_video(SEGMENT_ID, "提示词"),)),
        narration_languages=tuple(NarrationLanguage),
    )
    if "plan" in kw:
        kw["final_assembly"] = kw.pop("plan")
    if "approval" in kw:
        kw["final_approval"] = kw.pop("approval")
    base.update(kw)
    return StructuredDirectorDocument(**base)


def _mp4_asset(asset_id: str = ID_C) -> Asset:
    return Asset(
        asset_id, "video/mp4", 24, asset_id + "f" * 32, "assets/videos/segments/s.mp4", 4.0
    )


def _final_generation(
    generation_id: str = ID_D,
    output: str = ID_C,
    language: NarrationLanguage = NarrationLanguage.ZH,
) -> ReferenceGeneration:
    return ReferenceGeneration(
        id=generation_id,
        kind=ReferenceGenerationKind.FINAL_VIDEO,
        operation=GenerationOperation.ASSEMBLE,
        target_id=ID_A,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        progress=1.0,
        message="",
        prompt_text="成片装配",
        input_asset_ids=(ID_C,),
        sample_text=None,
        seed=None,
        plugin_id="test.final",
        plugin_version=1,
        external_id="e",
        output_asset_id=output,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=22.0,
        dismissed=False,
        language=language,
    )


def _both_generations() -> tuple[ReferenceGeneration, ReferenceGeneration]:
    return (
        _final_generation(),
        _final_generation(ID_F, ID_E, NarrationLanguage.EN),
    )


BOTH_ASSETS = (_mp4_asset(), _mp4_asset(ID_E))


def _document(
    *,
    status: StructuredDirectorStatus = StructuredDirectorStatus.REVIEWING_FINAL,
    plan: FinalAssemblyPlan | None = PLAN,
    approval: FinalApproval | None = None,
    generations: tuple = (),
    assets: tuple | None = None,
) -> StructuredDirectorDocument:
    if plan is not None:
        return _full_fixture_document(
            status=status,
            plan=plan,
            approval=approval,
            generations=generations,
            assets=assets if assets is not None else (_mp4_asset(), _mp4_asset(ID_E)),
        )
    return StructuredDirectorDocument(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=ID_A,
        revision=3,
        title="final 校验",
        aspect_ratio=__import__(
            "core.project_settings", fromlist=["ProjectAspectRatio"]
        ).ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案",
        status=status,
        workspace_layers=WorkspaceLayers(
            narration_unlocked=True,
            keyframes_unlocked=True,
            videos_unlocked=True,
            final_assembly_unlocked=True,
        ),
        reference_library=__import__(
            "core.structured_director.models", fromlist=["ReferenceLibrary"]
        ).ReferenceLibrary(),
        assets=assets or (),
        generations=generations,
        final_assembly=plan,
        final_approval=approval,
        narration_languages=tuple(NarrationLanguage),
    )


def _expect(fn, expected: str, **kwargs):
    with pytest.raises(ValueError, match=re.escape(expected)):
        fn(**kwargs)


def test_enter_final_stage_guard():
    locked = _document(status=StructuredDirectorStatus.REVIEWING, plan=None)
    locked = replace(
        locked,
        workspace_layers=WorkspaceLayers(narration_unlocked=True, keyframes_unlocked=True),
    )
    _expect(
        lambda **kw: _final.enter_final_stage(kw.pop("document"), kw.pop("plan")),
        "当前不能进入成片装配。",
        document=locked,
        plan=PLAN,
    )
    entered = _final.enter_final_stage(_document(), PLAN)
    assert entered.status is StructuredDirectorStatus.REVIEWING_FINAL
    assert entered.workspace_layers.final_assembly_unlocked is True


def test_select_final_candidate_guards():
    no_plan = _document(status=StructuredDirectorStatus.REVIEWING, plan=None)
    _expect(
        lambda **kw: _final.select_final_candidate(
            kw.pop("document"), kw.pop("selection"), command_id="cmd"
        ),
        "成片装配计划尚未建立。",
        document=no_plan,
        selection=FinalCandidateSelection(ID_D),
    )
    document = _document(generations=(_final_generation(),), assets=BOTH_ASSETS)
    _expect(
        lambda **kw: _final.select_final_candidate(
            kw.pop("document"), kw.pop("selection"), command_id="cmd"
        ),
        "Generation 不存在。",
        document=document,
        selection=FinalCandidateSelection("e" * 32),
    )
    running = replace(
        _final_generation(), phase=ReferenceGenerationPhase.RUNNING, output_asset_id=None
    )
    doc_running = _document(generations=(running,), assets=BOTH_ASSETS)
    _expect(
        lambda **kw: _final.select_final_candidate(
            kw.pop("document"), kw.pop("selection"), command_id="cmd"
        ),
        "只能选择成功且未隐藏的成片 Generation。",
        document=doc_running,
        selection=FinalCandidateSelection(ID_D),
    )
    dismissed = replace(_final_generation(), dismissed=True)
    doc_dismissed = _document(generations=(dismissed,), assets=BOTH_ASSETS)
    _expect(
        lambda **kw: _final.select_final_candidate(
            kw.pop("document"), kw.pop("selection"), command_id="cmd"
        ),
        "只能选择成功且未隐藏的成片 Generation。",
        document=doc_dismissed,
        selection=FinalCandidateSelection(ID_D),
    )
    # noop：已是当前选择。
    selected_plan = replace(PLAN, selected_zh_asset_id=ID_C)
    doc_selected = _document(
        plan=selected_plan, generations=(_final_generation(),), assets=BOTH_ASSETS
    )
    updated, receipt, write = _final.select_final_candidate(
        doc_selected, FinalCandidateSelection(ID_D), command_id="cmd"
    )
    assert write is False and receipt.status == "noop"
    # 选择按 Generation 语言落到对应槽位，另一语言不受影响。
    doc_both = _document(generations=_both_generations(), assets=BOTH_ASSETS)
    updated, receipt, write = _final.select_final_candidate(
        doc_both, FinalCandidateSelection(ID_F), command_id="cmd"
    )
    assert write is True
    assert updated.final_assembly.selected_en_asset_id == ID_E
    assert updated.final_assembly.selected_zh_asset_id is None


def test_clear_final_selection_guards():
    no_plan = _document(status=StructuredDirectorStatus.REVIEWING, plan=None)
    _expect(
        lambda **kw: _final.clear_final_selection(kw.pop("document"), command_id="cmd"),
        "成片装配计划尚未建立。",
        document=no_plan,
    )
    empty = _document(plan=PLAN)
    updated, receipt, write = _final.clear_final_selection(empty, command_id="cmd")
    assert write is False and "当前没有已采用的成片候选。" in receipt.decision_summary
    selected = _document(plan=SELECTED, generations=_both_generations(), assets=BOTH_ASSETS)
    cleared, receipt, write = _final.clear_final_selection(selected, command_id="cmd")
    assert write is True and set(receipt.changed_ids) == {ID_C, ID_E}
    assert cleared.final_assembly.selected_zh_asset_id is None
    assert cleared.final_assembly.selected_en_asset_id is None


def test_approve_final_guards():
    no_plan = _document(status=StructuredDirectorStatus.REVIEWING, plan=None)
    _expect(
        lambda **kw: _final.approve_final(kw.pop("document"), kw.pop("approval"), command_id="cmd"),
        "当前不能批准成片。",
        document=no_plan,
        approval=FinalApprovalRequest(ID_C, ID_E),
    )
    # 只选了中文，英文尚未选择时不能批准。
    zh_only = _document(
        plan=replace(PLAN, selected_zh_asset_id=ID_C),
        generations=_both_generations(),
        assets=BOTH_ASSETS,
    )
    _expect(
        lambda **kw: _final.approve_final(kw.pop("document"), kw.pop("approval"), command_id="cmd"),
        "请先选择英文成片候选，再执行批准。",
        document=zh_only,
        approval=FinalApprovalRequest(ID_C, ID_E),
    )
    changed = _document(plan=SELECTED, generations=_both_generations(), assets=BOTH_ASSETS)
    with pytest.raises(
        RevisionConflictError,
        match=re.escape("当前成片选择已变化，请确认精确 Asset 后重新批准。"),
    ):
        _final.approve_final(changed, FinalApprovalRequest(ID_E, ID_C), command_id="cmd")
    # noop：已批准同一对 Asset。
    doc_approved = _document(
        status=StructuredDirectorStatus.APPROVED,
        plan=SELECTED,
        approval=APPROVED,
        generations=_both_generations(),
        assets=BOTH_ASSETS,
    )
    updated, receipt, write = _final.approve_final(
        doc_approved, FinalApprovalRequest(ID_C, ID_E), command_id="cmd"
    )
    assert write is False and receipt.status == "noop"
    # 成功路径：一次 Approval 同时绑定中英两个 Generation 与精确 revision。
    doc_ready = _document(plan=SELECTED, generations=_both_generations(), assets=BOTH_ASSETS)
    updated, receipt, write = _final.approve_final(
        doc_ready, FinalApprovalRequest(ID_C, ID_E), command_id="cmd"
    )
    assert write is True and updated.status is StructuredDirectorStatus.APPROVED
    assert updated.final_approval.approved_project_revision == updated.revision
    assert updated.final_approval.zh_generation_id == ID_D
    assert updated.final_approval.en_generation_id == ID_F


def test_reopen_final_production_guards():
    open_doc = _full_fixture_document(status=StructuredDirectorStatus.REVIEWING_VIDEOS, plan=None)
    updated, receipt, write = _final.reopen_final_production(open_doc, command_id="cmd")
    assert write is False and "视频生产已经开放。" in receipt.decision_summary
    early = _document(status=StructuredDirectorStatus.REVIEWING, plan=None)
    _expect(
        lambda **kw: _final.reopen_final_production(kw.pop("document"), command_id="cmd"),
        "当前不需要返回视频生产。",
        document=early,
    )
    approved_doc = _document(
        status=StructuredDirectorStatus.APPROVED,
        plan=SELECTED,
        approval=APPROVED,
        generations=_both_generations(),
        assets=BOTH_ASSETS,
    )
    reopened, receipt, write = _final.reopen_final_production(approved_doc, command_id="cmd")
    assert write is True
    assert reopened.status is StructuredDirectorStatus.REVIEWING_VIDEOS
    assert reopened.final_assembly is None and reopened.final_approval is None
    assert set(receipt.invalidated) == {"final_assembly", "final_approval"}
    # 只有装配没有 Approval 时 invalidated 仅含装配。
    reopened2, receipt2, _ = _final.reopen_final_production(_document(), command_id="cmd")
    assert set(receipt2.invalidated) == {"final_assembly"}
