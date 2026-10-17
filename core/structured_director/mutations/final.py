"""Final 域 mutations：纯函数化的成片装配/批准/重开逻辑（P2-C6）。

从 store final 方法原样抽取：进入成片阶段、候选选择/清除、Approval、重开视频生产。
P7-T1 已删除 store 上的 legacy 命令包装，调用方统一走 `*_command` 正式入口。
"""

from __future__ import annotations

from dataclasses import replace

from core.director_commands import (
    CommandReceipt,
    FinalApprovalRequest,
    FinalCandidateSelection,
)

from ..errors import RevisionConflictError
from ..models import (
    FinalApproval,
    FinalAssemblyPlan,
    NarrationLanguage,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
)

_LABELS = {NarrationLanguage.ZH: "中文", NarrationLanguage.EN: "英文"}


def enter_final_stage(
    document: StructuredDirectorDocument, plan: FinalAssemblyPlan
) -> StructuredDirectorDocument:
    """进入成片审核阶段并保存装配计划。"""
    if not document.is_reviewing or not document.workspace_layers.videos_unlocked:
        raise ValueError("当前不能进入成片装配。")
    return replace(
        document,
        revision=document.revision + 1,
        status=StructuredDirectorStatus.REVIEWING_FINAL,
        workspace_layers=replace(
            document.workspace_layers,
            final_assembly_unlocked=True,
        ),
        final_assembly=plan,
    )


def select_final_candidate(
    document: StructuredDirectorDocument,
    selection: FinalCandidateSelection,
    *,
    command_id: str,
) -> tuple[StructuredDirectorDocument, CommandReceipt, bool]:
    """采用成功且未隐藏的成片 Generation 输出。"""
    plan = document.final_assembly
    if plan is None:
        raise ValueError("成片装配计划尚未建立。")
    generation = next(
        (item for item in document.generations if item.id == selection.generation_id), None
    )
    if generation is None:
        raise ValueError("Generation 不存在。")
    if (
        generation.kind is not ReferenceGenerationKind.FINAL_VIDEO
        or generation.phase is not ReferenceGenerationPhase.SUCCEEDED
        or generation.output_asset_id is None
        or generation.dismissed
        or generation.language is None
    ):
        raise ValueError("只能选择成功且未隐藏的成片 Generation。")
    language = generation.language
    if plan.selected_asset_id(language) == generation.output_asset_id:
        return (
            document,
            CommandReceipt(
                command_id,
                "noop",
                document.revision,
                document.revision,
                decision_summary="该成片 Generation 已经是当前选择。",
            ),
            False,
        )
    updated = replace(
        document,
        revision=document.revision + 1,
        final_assembly=plan.with_selection(language, generation.output_asset_id),
    )
    return (
        updated,
        CommandReceipt(
            command_id,
            "succeeded",
            document.revision,
            updated.revision,
            changed_ids=(selection.generation_id, generation.output_asset_id),
            preserved=("final_generation_history",),
            decision_summary=f"已采用指定 Generation 的{_LABELS[language]}成片 Asset。",
            next_allowed_actions=("final.approve", "final.clear_selection"),
        ),
        True,
    )


def clear_final_selection(
    document: StructuredDirectorDocument, *, command_id: str
) -> tuple[StructuredDirectorDocument, CommandReceipt, bool]:
    """清除当前成片选择；历史候选与 Asset 保留。"""
    plan = document.final_assembly
    if plan is None:
        raise ValueError("成片装配计划尚未建立。")
    selected_asset_ids = tuple(
        asset_id
        for language in document.narration_languages
        if (asset_id := plan.selected_asset_id(language)) is not None
    )
    if not selected_asset_ids:
        return (
            document,
            CommandReceipt(
                command_id,
                "noop",
                document.revision,
                document.revision,
                decision_summary="当前没有已采用的成片候选。",
            ),
            False,
        )
    updated = replace(
        document,
        revision=document.revision + 1,
        final_assembly=replace(plan, selected_zh_asset_id=None, selected_en_asset_id=None),
    )
    return (
        updated,
        CommandReceipt(
            command_id,
            "succeeded",
            document.revision,
            updated.revision,
            changed_ids=selected_asset_ids,
            preserved=("final_generation_history", "final_assets"),
            decision_summary="已清除当前成片选择，历史候选与 Asset 保留。",
            next_allowed_actions=("final.select_candidate", "final.assemble"),
        ),
        True,
    )


def approve_final(
    document: StructuredDirectorDocument,
    approval: FinalApprovalRequest,
    *,
    command_id: str,
) -> tuple[StructuredDirectorDocument, CommandReceipt, bool]:
    """批准当前精确成片 Asset，绑定成功 Generation 与项目 revision。"""
    plan = document.final_assembly
    requested = {
        NarrationLanguage.ZH: approval.zh_asset_id,
        NarrationLanguage.EN: approval.en_asset_id,
    }
    if any(
        (asset_id is not None) != (language in document.narration_languages)
        for language, asset_id in requested.items()
    ):
        raise ValueError("Approval 必须完整对应项目所选语言，未选语言的 Asset 必须为 null。")
    requested = {language: requested[language] for language in document.narration_languages}
    if (
        document.status is StructuredDirectorStatus.APPROVED
        and plan is not None
        and document.final_approval is not None
        and all(
            plan.selected_asset_id(language) == asset_id
            and document.final_approval.asset_id(language) == asset_id
            for language, asset_id in requested.items()
        )
    ):
        return (
            document,
            CommandReceipt(
                command_id,
                "noop",
                document.revision,
                document.revision,
                preserved=("final_assembly", "final_approval"),
                decision_summary="所选语言的成片 Asset 已经批准。",
                next_allowed_actions=("final.reopen_production",),
            ),
            False,
        )
    if document.status is not StructuredDirectorStatus.REVIEWING_FINAL or plan is None:
        raise ValueError("当前不能批准成片。")
    missing = [
        _LABELS[language] for language in requested if plan.selected_asset_id(language) is None
    ]
    if missing:
        raise ValueError(f"请先选择{'、'.join(missing)}成片候选，再执行批准。")
    if any(
        plan.selected_asset_id(language) != asset_id for language, asset_id in requested.items()
    ):
        raise RevisionConflictError("当前成片选择已变化，请确认精确 Asset 后重新批准。")
    generations: dict[NarrationLanguage, str] = {}
    for language, asset_id in requested.items():
        generation = next(
            (
                item
                for item in document.generations
                if item.kind is ReferenceGenerationKind.FINAL_VIDEO
                and item.language is language
                and item.phase is ReferenceGenerationPhase.SUCCEEDED
                and item.output_asset_id == asset_id
                and not item.dismissed
            ),
            None,
        )
        if generation is None:
            raise ValueError(f"当前{_LABELS[language]}选择没有可批准的成功 Generation。")
        generations[language] = generation.id
    revision = document.revision + 1
    updated = replace(
        document,
        revision=revision,
        status=StructuredDirectorStatus.APPROVED,
        final_approval=FinalApproval(
            zh_asset_id=approval.zh_asset_id,
            zh_generation_id=generations.get(NarrationLanguage.ZH),
            en_asset_id=approval.en_asset_id,
            en_generation_id=generations.get(NarrationLanguage.EN),
            source_script_revision=plan.source_script_revision,
            approved_project_revision=revision,
        ),
    )
    return (
        updated,
        CommandReceipt(
            command_id,
            "succeeded",
            document.revision,
            updated.revision,
            changed_ids=(
                *requested.values(),
                *generations.values(),
            ),
            preserved=("final_assembly", "final_generation_history"),
            decision_summary="已一次批准当前精确的所选语言成片 Asset 与项目 revision。",
            next_allowed_actions=("final.reopen_production",),
        ),
        True,
    )


def reopen_final_production(
    document: StructuredDirectorDocument, *, command_id: str
) -> tuple[StructuredDirectorDocument, CommandReceipt, bool]:
    """清除当前装配与 Approval，重开视频生产；成片历史保留。"""
    if document.status is StructuredDirectorStatus.REVIEWING_VIDEOS:
        return (
            document,
            CommandReceipt(
                command_id,
                "noop",
                document.revision,
                document.revision,
                decision_summary="视频生产已经开放。",
            ),
            False,
        )
    if document.status not in {
        StructuredDirectorStatus.REVIEWING_FINAL,
        StructuredDirectorStatus.APPROVED,
    }:
        raise ValueError("当前不需要返回视频生产。")
    updated = replace(
        document,
        revision=document.revision + 1,
        status=StructuredDirectorStatus.REVIEWING_VIDEOS,
        final_assembly=None,
        final_approval=None,
    )
    invalidated = tuple(
        item
        for item, present in (
            ("final_assembly", document.final_assembly is not None),
            ("final_approval", document.final_approval is not None),
        )
        if present
    )
    return (
        updated,
        CommandReceipt(
            command_id,
            "succeeded",
            document.revision,
            updated.revision,
            invalidated=invalidated,
            preserved=("final_generation_history", "final_assets", "workspace_layers"),
            decision_summary="已重新开放视频生产；成片历史保留，当前装配与 Approval 已清除。",
            next_allowed_actions=("video.generate", "video.upscale", "final.assemble"),
        ),
        True,
    )
