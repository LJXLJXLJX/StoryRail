"""store/domains/video：video 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from core.application.caller import current_caller
from core.director_commands import (
    CommandReceipt,
    VideoInputsUpdate,
    VideoPromptUpdate,
    VideoRecipeUpdate,
    VideoSelectionClear,
)
from core.model_providers.manifest import Capability, Role
from core.structured_director.errors import RevisionConflictError as RevisionConflictError
from core.structured_director.models import (
    DirectorCommandReceipt,
    DirectorRunCursor,
    DirectorRunKind,
    DirectorRunStatus,
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorDocument,
)
from core.structured_director.reference_image_mutations import (
    reference_image_slot,
    save_reference_image_plan,
    select_reference_image,
)
from core.structured_director.run_state import _active_run_is as _active_run_is
from core.structured_director.run_state import _start_director_run as _start_director_run
from core.structured_director.script_mutations import _finish_director_run as _finish_director_run
from core.structured_director.store import _generation_timestamp as _generation_timestamp
from core.structured_director.store import _require_generation as _require_generation
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation
from core.structured_director.video_inputs import video_inputs_digest
from core.structured_director.video_mutations import (
    _prepare_segment_video_plan_update as _prepare_segment_video_plan_update,
)
from core.structured_director.video_mutations import (
    _prepare_segment_video_prompt_update as _prepare_segment_video_prompt_update,
)
from core.structured_director.video_mutations import (
    _reject_active_segment_video_generation as _reject_active_segment_video_generation,
)
from core.structured_director.video_mutations import (
    _require_video_command_target as _require_video_command_target,
)
from core.structured_director.video_mutations import (
    _video_command_receipt as _video_command_receipt,
)


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class VideoDomain(_DomainBase):
    def save_video_reference_image_plan(self, update, *, expected_revision, command_id):
        def mutate(document):
            _, _, _, video = _require_video_command_target(
                document, update.scope_scene_ids, update.segment_id
            )
            updated = save_reference_image_plan(
                document, update, reference_image_slot(self._provider_catalog, video)
            )
            updated = replace(updated, revision=document.revision + 1)
            return MutationResult(
                updated,
                _video_command_receipt(
                    command_id, document, updated, update.segment_id, "已保存其他图片规划。"
                ),
            )

        return commit_mutation(
            self, loader=lambda: self._editable_document(expected_revision), mutator=mutate
        )

    def select_video_reference_image(self, update, *, expected_revision, command_id):
        def mutate(document):
            _, _, _, video = _require_video_command_target(
                document, update.scope_scene_ids, update.segment_id
            )
            updated = select_reference_image(
                document, update, reference_image_slot(self._provider_catalog, video)
            )
            if updated is document:
                return MutationResult(
                    document,
                    CommandReceipt(command_id, "noop", document.revision, document.revision),
                    write=False,
                )
            self._provider_catalog.validate_recipe_inputs(
                Capability.VIDEO_GENERATE,
                video.active_recipe,
                next(
                    item
                    for item in updated.video_plan.segments
                    if item.segment_id == video.segment_id
                ).recipe_inputs,
                document.assets,
            )
            updated = replace(updated, revision=document.revision + 1)
            return MutationResult(
                updated,
                _video_command_receipt(
                    command_id,
                    document,
                    updated,
                    update.segment_id,
                    "已更新其他图片的实际视频输入。",
                ),
            )

        return commit_mutation(
            self, loader=lambda: self._editable_document(expected_revision), mutator=mutate
        )

    def begin_production_instruction(
        self, message: str | None, *, expected_revision: int
    ) -> tuple[StructuredDirectorDocument, bool]:
        document = self.read()
        if document.revision != expected_revision:
            raise RevisionConflictError("项目已被更新，请重新读取后再请求 Director Agent。")
        active = document.active_director_run
        if active is not None:
            if active.kind is not DirectorRunKind.DIRECTOR:
                raise ValueError("另一个 Director Agent 任务正在执行。")
            if active.status is DirectorRunStatus.WAITING_USER:
                if message is None or not message.strip():
                    raise ValueError("Director 正在等待新的用户指令。")
                return (
                    self.resume_director_run(
                        run_id=active.id,
                        expected_revision=document.revision,
                        raw_user_request=message,
                    ),
                    False,
                )
            if active.status is DirectorRunStatus.WAITING_JOBS:
                raise ValueError("Director 正在等待 Provider Generation 完成。")
            return document, True

        def mutate(current: StructuredDirectorDocument) -> MutationResult:
            if not current.is_reviewing:
                raise ValueError("当前不能请求 Director Agent。")
            if message is None or not message.strip():
                raise ValueError("Director 请求不能为空。")
            started = _start_director_run(
                current,
                DirectorRunKind.DIRECTOR,
                goal=message.strip(),
                raw_user_request=message.strip(),
            )
            updated = replace(
                current,
                revision=current.revision + 1,
                director_runs=started.runs,
                director_directives=started.directives,
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=lambda: document, mutator=mutate)
        return updated, False

    def set_segment_video_prompt(
        self,
        update: VideoPromptUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, dict[str, object]]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, receipt = _prepare_segment_video_prompt_update(document, update, command_id)
            return MutationResult(updated, receipt, write=updated is not document)

        document, receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return (
            document,
            receipt,
            video_inputs_digest(
                document, update.segment_id, provider_catalog=self._provider_catalog
            ),
        )

    def set_segment_video_inputs(
        self,
        update: VideoInputsUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, dict[str, object]]:
        """原子保存视频正文、绑定与参数；返回写入后的紧凑输入摘要供 Agent 自查。"""

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            caller = current_caller.get()
            if caller is not None and caller.role == "agent":
                _, _, _, current = _require_video_command_target(
                    document, update.scope_scene_ids, update.segment_id
                )
                newly_bound = set(update.inputs.asset_ids) - set(current.recipe_inputs.asset_ids)
                if any(
                    generation.kind is ReferenceGenerationKind.VIDEO_REFERENCE_IMAGE
                    and generation.output_asset_id in newly_bound
                    for generation in document.generations
                ):
                    raise ValueError(
                        "新生成的其他图片候选必须先由人类在卡片选用，"
                        "Agent 不能通过视频输入绑定绕过选择。"
                    )

            dialogue_slot = None
            if update.attach_dialogue_audio:
                _, _, _, current = _require_video_command_target(
                    document, update.scope_scene_ids, update.segment_id
                )
                if self._provider_catalog is None or current.active_recipe is None:
                    raise ValueError("请先配置视频 Provider 并选择 recipe。")
                _, recipe = self._provider_catalog.recipe_definition(
                    Capability.VIDEO_GENERATE, current.active_recipe
                )
                dialogue_slot = next(
                    (slot for slot in recipe.slots if slot.role is Role.REFERENCE_AUDIO), None
                )
            updated, receipt = _prepare_segment_video_plan_update(
                document, update, command_id, dialogue_slot=dialogue_slot
            )
            return MutationResult(updated, receipt, write=updated is not document)

        document, receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return (
            document,
            receipt,
            video_inputs_digest(
                document, update.segment_id, provider_catalog=self._provider_catalog
            ),
        )

    def set_segment_video_prompt_with_run_progress(
        self,
        update: VideoPromptUpdate,
        *,
        expected_revision: int,
        command_id: str,
        run_id: str,
        cursor: DirectorRunCursor,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        """原子保存视频提示词正文、receipt 与剩余批次 cursor。"""

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            active = document.active_director_run
            if (
                active is None
                or active.id != run_id
                or active.status is not DirectorRunStatus.RUNNING
            ):
                raise ValueError("Director run 不存在或当前不能保存 视频提示词批次进度。")
            if cursor.step < active.cursor.step:
                raise ValueError("Director run cursor 不能回退。")
            if cursor.waiting_generation_ids:
                raise ValueError("视频提示词批次 cursor 不能保存等待 Generation。")
            if command_id in active.completed_command_ids:
                raise ValueError("视频提示词批次 command_id 已经完成，不能重复记录。")
            changed, receipt = _prepare_segment_video_prompt_update(document, update, command_id)
            next_revision = document.revision + 1
            if changed is document:
                changed = replace(document, revision=next_revision)
            now = datetime.now(UTC).isoformat()
            summary = DirectorCommandReceipt(
                command_id=receipt.command_id,
                status=receipt.status,
                old_revision=receipt.old_revision,
                new_revision=receipt.new_revision,
                decision_summary=receipt.decision_summary or "Core 命令已执行。",
                recorded_at=now,
            )
            updated_run = replace(
                active,
                cursor=cursor,
                completed_command_ids=(*active.completed_command_ids, command_id),
                command_receipts=(*active.command_receipts, summary),
                last_project_revision=next_revision,
                updated_at=now,
            )
            updated = replace(
                changed,
                revision=next_revision,
                director_runs=tuple(
                    updated_run if item.id == run_id else item for item in changed.director_runs
                ),
            )
            return MutationResult(updated, receipt)

        updated, receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated, receipt

    def set_segment_video_recipe(
        self,
        update: VideoRecipeUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            plan, _scene, _segment, current = _require_video_command_target(
                document, update.scope_scene_ids, update.segment_id
            )
            _reject_active_segment_video_generation(document, update.segment_id)
            if current.active_recipe == update.recipe_id:
                return MutationResult(
                    document,
                    CommandReceipt(
                        command_id,
                        "noop",
                        document.revision,
                        document.revision,
                        preserved=("video_selection", "video_upscale_selection"),
                        next_allowed_actions=("video.generate",),
                    ),
                    write=False,
                )
            self._validate_video_recipe_switch(document, current, update.recipe_id)
            replacement = replace(
                current,
                active_recipe=update.recipe_id,
                selected_asset_id=None,
                upscaled_asset_id=None,
            )
            updated = replace(
                document,
                revision=document.revision + 1,
                video_plan=replace(
                    plan,
                    segments=tuple(
                        replacement if item.segment_id == update.segment_id else item
                        for item in plan.segments
                    ),
                ),
                final_assembly=None,
            )
            return MutationResult(
                updated,
                _video_command_receipt(
                    command_id,
                    document,
                    updated,
                    update.segment_id,
                    f"已将 Segment 视频 recipe 设置为 {update.recipe_id}。",
                ),
            )

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def clear_segment_video_selection(
        self,
        clear: VideoSelectionClear,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            plan, _scene, _segment, current = _require_video_command_target(
                document, clear.scope_scene_ids, clear.segment_id
            )
            if current.selected_asset_id is None and current.upscaled_asset_id is None:
                return MutationResult(
                    document,
                    CommandReceipt(
                        command_id,
                        "noop",
                        document.revision,
                        document.revision,
                        decision_summary="Segment 当前没有视频或超分选择。",
                        next_allowed_actions=("video.generate",),
                    ),
                    write=False,
                )
            replacement = replace(current, selected_asset_id=None, upscaled_asset_id=None)
            updated = replace(
                document,
                revision=document.revision + 1,
                video_plan=replace(
                    plan,
                    segments=tuple(
                        replacement if item.segment_id == clear.segment_id else item
                        for item in plan.segments
                    ),
                ),
                final_assembly=None,
            )
            return MutationResult(
                updated,
                _video_command_receipt(
                    command_id,
                    document,
                    updated,
                    clear.segment_id,
                    "已清除当前视频与超分选择，历史候选仍保留。",
                ),
            )

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def finish_production_instruction(self, *, failed: bool = False) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if not _active_run_is(document, DirectorRunKind.DIRECTOR):
                raise ValueError("当前没有等待完成的 Director Agent 请求。")
            updated = replace(
                document,
                revision=document.revision + 1,
                director_runs=_finish_director_run(
                    document, DirectorRunKind.DIRECTOR, failed=failed
                ),
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def select_segment_video(
        self, *, segment_id: str, asset_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            plan = document.video_plan
            if plan is None:
                raise ValueError("视频计划尚未建立。")
            current = next((item for item in plan.segments if item.segment_id == segment_id), None)
            if current is None:
                raise ValueError("Segment 视频计划不存在。")
            if not any(
                item.kind is ReferenceGenerationKind.SEGMENT_VIDEO
                and item.target_id == segment_id
                and item.phase is ReferenceGenerationPhase.SUCCEEDED
                and item.output_asset_id == asset_id
                and not item.dismissed
                for item in document.generations
            ):
                raise ValueError("只能选择该 Segment 的成功视频候选。")
            found = False
            segments = []
            for item in plan.segments:
                if item.segment_id == segment_id:
                    item = replace(item, selected_asset_id=asset_id, upscaled_asset_id=None)
                    found = True
                segments.append(item)
            if not found:
                raise ValueError("Segment 视频计划不存在。")
            updated = replace(
                document,
                revision=document.revision + 1,
                video_plan=replace(plan, segments=tuple(segments)),
                final_assembly=None,
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def attach_segment_video_candidate(
        self, *, segment_id: str, asset_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            plan = document.video_plan
            if plan is None or not any(item.segment_id == segment_id for item in plan.segments):
                raise ValueError("Segment 视频计划不存在。")
            asset = next((item for item in document.assets if item.id == asset_id), None)
            if asset is None or asset.media_type != "video/mp4":
                raise ValueError("只能从项目资产库增加 MP4 视频候选。")
            if asset.duration_seconds is None or asset.duration_seconds < 0.2:
                raise ValueError("资产库视频候选必须是有真实时长的 MP4，且不短于 0.2 秒。")
            matching = [
                item
                for item in document.generations
                if item.kind is ReferenceGenerationKind.SEGMENT_VIDEO
                and item.target_id == segment_id
                and item.phase is ReferenceGenerationPhase.SUCCEEDED
                and item.output_asset_id == asset_id
            ]
            if any(not item.dismissed for item in matching):
                return MutationResult(document, None, write=False)
            if matching:
                revived = matching[-1]
                now = _generation_timestamp()
                generations = tuple(
                    replace(item, dismissed=False, updated_at=now)
                    if item.id == revived.id
                    else item
                    for item in document.generations
                )
            else:
                generation_id = uuid4().hex
                now = _generation_timestamp()
                generation = ReferenceGeneration(
                    id=generation_id,
                    kind=ReferenceGenerationKind.SEGMENT_VIDEO,
                    operation=GenerationOperation.ATTACH,
                    target_id=segment_id,
                    phase=ReferenceGenerationPhase.SUCCEEDED,
                    progress=1.0,
                    message="已从项目资产库增加为视频候选。",
                    prompt_text="从项目资产库增加视频候选。",
                    input_asset_ids=(),
                    sample_text=None,
                    seed=None,
                    plugin_id="storyrail.asset_library",
                    plugin_version=1,
                    external_id=generation_id,
                    output_asset_id=asset_id,
                    error_code=None,
                    cancellation_requested=False,
                    retry_of=None,
                    duration_seconds=asset.duration_seconds,
                    created_at=now,
                    updated_at=now,
                )
                generations = (*document.generations, generation)
            updated = replace(
                document,
                revision=document.revision + 1,
                generations=generations,
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def attach_upscaled_video(
        self, *, segment_id: str, generation_id: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            plan = document.video_plan
            generation = _require_generation(document, generation_id)
            if plan is None or generation.kind is not ReferenceGenerationKind.VIDEO_UPSCALE:
                raise ValueError("该 Generation 不是视频超分结果。")
            if generation.target_id != segment_id or generation.output_asset_id is None:
                raise ValueError("超分结果不属于该 Segment。")
            if generation.phase is not ReferenceGenerationPhase.SUCCEEDED or generation.dismissed:
                raise ValueError("只能采用成功且未删除的超分结果。")
            segments = []
            found = False
            for item in plan.segments:
                if item.segment_id == segment_id:
                    if item.selected_asset_id is None or generation.input_asset_ids != (
                        item.selected_asset_id,
                    ):
                        raise ValueError("超分源视频已变化，请重新提交。")
                    item = replace(item, upscaled_asset_id=generation.output_asset_id)
                    found = True
                segments.append(item)
            if not found:
                raise ValueError("Segment 视频计划不存在。")
            updated = replace(
                document,
                revision=document.revision + 1,
                video_plan=replace(plan, segments=tuple(segments)),
                final_assembly=None,
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated
