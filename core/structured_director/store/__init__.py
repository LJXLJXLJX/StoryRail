from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from core.director_commands import (
    CommandReceipt,
)
from core.director_commands import (
    FinalApprovalRequest as FinalApprovalRequest,
)
from core.director_commands import (
    FinalCandidateSelection as FinalCandidateSelection,
)
from core.director_commands import (
    GenerationTarget as GenerationTarget,
)
from core.director_commands import (
    KeyframeOperation as KeyframeOperation,
)
from core.director_commands import (
    NarrationCueUpdate as NarrationCueUpdate,
)
from core.director_commands import (
    NarrationSelectionClear as NarrationSelectionClear,
)
from core.director_commands import (
    RepairPatch as RepairPatch,
)
from core.director_commands import (
    RepairReceipt as RepairReceipt,
)
from core.director_commands import (
    RunResume as RunResume,
)
from core.director_commands import (
    RunTarget as RunTarget,
)
from core.director_commands import (
    ScriptOperationsPatch as ScriptOperationsPatch,
)
from core.director_commands import (
    SetKeyframeActivation as SetKeyframeActivation,
)
from core.director_commands import (
    ShareKeyframeBoundary as ShareKeyframeBoundary,
)
from core.director_commands import (
    SplitKeyframeBoundary as SplitKeyframeBoundary,
)
from core.director_commands import (
    UpdateKeyframeFields as UpdateKeyframeFields,
)
from core.director_commands import (
    VideoInputsUpdate as VideoInputsUpdate,
)
from core.director_commands import (
    VideoPromptUpdate as VideoPromptUpdate,
)
from core.director_commands import (
    VideoRecipeUpdate as VideoRecipeUpdate,
)
from core.director_commands import (
    VideoSelectionClear as VideoSelectionClear,
)
from core.director_commands import (
    parse_keyframe_operations as parse_keyframe_operations,
)
from core.director_proposals import (
    KeyframeOperationsProposal as KeyframeOperationsProposal,
)
from core.director_proposals import (
    KeyframePlanProposal as KeyframePlanProposal,
)
from core.director_proposals import (
    NarrationReviewProposal as NarrationReviewProposal,
)
from core.director_proposals import (
    ReferenceLibraryProposal as ReferenceLibraryProposal,
)
from core.director_proposals import (
    StructuredDirectorScriptProposal,
)
from core.director_proposals import (
    StructuredDirectorScriptRevisionProposal as StructuredDirectorScriptRevisionProposal,
)
from core.model_providers.contracts import validate_pano_source
from core.model_providers.manifest import Capability, DomainPredicate, Role
from core.model_providers.recipe import RecipeParams
from core.project_settings import ProjectAspectRatio

from ..application_requests import attach_submission_request
from ..application_requests import prune_generation_references as prune_generation_references
from ..asset_metadata import (
    _MEDIA_EXTENSION as _MEDIA_EXTENSION,
)
from ..asset_metadata import (
    _asset_filename as _asset_filename,
)
from ..asset_metadata import (
    _generation_asset_location as _generation_asset_location,
)
from ..asset_metadata import (
    _image_category_label as _image_category_label,
)
from ..asset_metadata import (
    _mp4_duration as _mp4_duration,
)
from ..asset_metadata import (
    _uploaded_asset_label as _uploaded_asset_label,
)
from ..asset_metadata import (
    _validate_media_bytes as _validate_media_bytes,
)
from ..asset_metadata import (
    _wav_duration as _wav_duration,
)
from ..codec import (
    _parse_document as _parse_document,
)
from ..codec import (
    serialize_document as _serialize_document,
)
from ..errors import RevisionConflictError as RevisionConflictError
from ..keyframe_mutations import (
    _apply_keyframe_operations as _apply_keyframe_operations,
)
from ..keyframe_mutations import (
    _validate_planned_shared_boundaries as _validate_planned_shared_boundaries,
)
from ..manual_commands import (
    keyframe_activation_command as keyframe_activation_command,
)
from ..manual_commands import (
    keyframe_edit_command as keyframe_edit_command,
)
from ..manual_commands import (
    keyframe_references_command as keyframe_references_command,
)
from ..models import (
    Asset,
    KeyframePlan,
    ReferenceGeneration,
    ReferenceGenerationPhase,
    ReferenceLibrary,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    WorkspaceLayers,
    prune_reference_keyframes,
    prune_reference_location_images,
)
from ..models import (
    CapabilityGapAlert as CapabilityGapAlert,
)
from ..models import (
    CapabilityGapResult as CapabilityGapResult,
)
from ..models import (
    CapabilityGapStatus as CapabilityGapStatus,
)
from ..models import (
    DirectorCommandReceipt as DirectorCommandReceipt,
)
from ..models import (
    DirectorRunCursor as DirectorRunCursor,
)
from ..models import (
    DirectorRunKind as DirectorRunKind,
)
from ..models import (
    DirectorRunStatus as DirectorRunStatus,
)
from ..models import (
    FinalAssemblyPlan as FinalAssemblyPlan,
)
from ..models import (
    GenerationOperation as GenerationOperation,
)
from ..models import (
    ImageAssetCategory as ImageAssetCategory,
)
from ..models import (
    Keyframe as Keyframe,
)
from ..models import (
    NarrationCue as NarrationCue,
)
from ..models import (
    NarratorProfile as NarratorProfile,
)
from ..models import (
    PendingScriptEdit as PendingScriptEdit,
)
from ..models import (
    ReferenceGenerationKind as ReferenceGenerationKind,
)
from ..models import (
    Scene as Scene,
)
from ..models import (
    SegmentKeyframes as SegmentKeyframes,
)
from ..models import (
    SegmentVideo as SegmentVideo,
)
from ..models import (
    VideoPlan as VideoPlan,
)
from ..models._shared import NarrationLanguage
from ..mutations import generation as _generation
from ..mutations.asset import _require_card_target as _require_card_target
from ..mutations.generation import _map_card as _map_card
from ..reads.read_tools import execute_project_read
from ..reads.workflow_state import require_workflow_action as require_workflow_action
from ..repair_mutations import (
    _apply_repair_operations as _apply_repair_operations,
)
from ..repair_mutations import (
    _formal_script_command_names as _formal_script_command_names,
)
from ..repair_mutations import (
    _repair_gap_id as _repair_gap_id,
)
from ..repair_mutations import (
    _repair_invalidated_items as _repair_invalidated_items,
)
from ..repair_mutations import (
    _repair_operation_for_alert as _repair_operation_for_alert,
)
from ..repair_mutations import (
    _repair_operation_from_alert as _repair_operation_from_alert,
)
from ..repair_mutations import (
    _repair_operation_summary as _repair_operation_summary,
)
from ..repair_mutations import (
    _repair_request_summary as _repair_request_summary,
)
from ..run_state import (
    _RUN_WAIT_TERMINAL_PHASES as _RUN_WAIT_TERMINAL_PHASES,
)
from ..run_state import (
    _active_run_is as _active_run_is,
)
from ..run_state import (
    _start_director_run as _start_director_run,
)
from ..schema import PROJECT_SCHEMA_VERSION
from ..script_index import scene_segments
from ..script_mutations import (
    _apply_script_operations as _apply_script_operations,
)
from ..script_mutations import (
    _apply_script_scene_operations as _apply_script_scene_operations,
)
from ..script_mutations import (
    _finish_director_run as _finish_director_run,
)
from ..script_mutations import (
    _invalidate_production_after_script_revision as _invalidate_production_after_script_revision,
)
from ..script_mutations import (
    _materialize_script as _materialize_script,
)
from ..script_mutations import (
    _materialize_script_revision as _materialize_script_revision,
)
from ..script_mutations import (
    _rebase_keyframe_plan as _rebase_keyframe_plan,
)
from ..script_mutations import (
    _rebase_video_plan as _rebase_video_plan,
)
from ..script_mutations import (
    _validate_script_references as _validate_script_references,
)
from ..video_mutations import (
    _apply_reference_library_change as _apply_reference_library_change,
)
from ..video_mutations import (
    _prepare_segment_video_plan_update as _prepare_segment_video_plan_update,
)
from ..video_mutations import (
    _prepare_segment_video_prompt_update as _prepare_segment_video_prompt_update,
)
from ..video_mutations import (
    _reject_active_segment_video_generation as _reject_active_segment_video_generation,
)
from ..video_mutations import (
    _require_video_command_target as _require_video_command_target,
)
from ..video_mutations import (
    _video_command_receipt as _video_command_receipt,
)
from .pipeline import MutationResult as MutationResult
from .pipeline import commit_mutation as commit_mutation


class ProviderCatalog(Protocol):
    def validate_recipe_params(self, capability: Capability, recipe_id: str, params: object): ...

    def recipe_views(self) -> list[dict]: ...
    def recipe_for(self, capability, predicates=frozenset()): ...
    def validate_recipe_inputs(self, capability, recipe_id, inputs, assets): ...
    def validate_recipe_switch(self, capability, current, recipe_id, assets): ...
    def recipe_definition(self, capability, recipe_id): ...


def _narration_tracks(document: StructuredDirectorDocument):
    if document.director_script is None:
        return {}
    return {
        (cue.id, language): track
        for scene in document.director_script.scenes
        for cue in scene.narration_cues
        for language, track in cue.tracks
    }


def _dialogue_audio_items(document: StructuredDirectorDocument):
    return (
        {}
        if document.dialogue_plan is None
        else {item.dialogue_line_id: item for item in document.dialogue_plan.items}
    )


def _check_changed_recipe_params(
    catalog: ProviderCatalog | None,
    previous: StructuredDirectorDocument,
    document: StructuredDirectorDocument,
) -> None:
    """只校验本次新增或改变的 recipe 参数；未改动的旧值即使与升级后的 manifest 不符也原样保留。"""
    if catalog is None:
        return
    old_video = (
        {}
        if previous.video_plan is None
        else {item.segment_id: item for item in previous.video_plan.segments}
    )
    for video in () if document.video_plan is None else document.video_plan.segments:
        old = old_video.get(video.segment_id)
        old_recipes = {} if old is None else dict(old.recipes.entries)
        for recipe_id, inputs in video.recipes.entries:
            if old_recipes.get(recipe_id) != inputs:
                catalog.validate_recipe_inputs(
                    Capability.VIDEO_GENERATE, recipe_id, inputs, document.assets
                )
    before = _narration_tracks(previous)
    empty = RecipeParams()
    for key, track in _narration_tracks(document).items():
        old = before.get(key)
        for recipe_id in track.recipe_params.changed_entries(
            empty if old is None else old.recipe_params
        ):
            params = track.recipe_params.get(recipe_id)
            try:
                catalog.validate_recipe_params(Capability.SPEECH_SYNTHESIZE, recipe_id, params)
            except ValueError as exc:
                raise ValueError(f"旁白{key[1].value}轨道的合成参数不合法：{exc}") from exc
    before_dialogue = _dialogue_audio_items(previous)
    for line_id, item in _dialogue_audio_items(document).items():
        old = before_dialogue.get(line_id)
        for recipe_id in item.recipe_params.changed_entries(
            empty if old is None else old.recipe_params
        ):
            params = item.recipe_params.get(recipe_id)
            try:
                catalog.validate_recipe_params(Capability.SPEECH_SYNTHESIZE, recipe_id, params)
            except ValueError as exc:
                raise ValueError(f"对白 {line_id} 的合成参数不合法：{exc}") from exc


# Asset 不可变；进程内跨 Service/Store 实例复用，只缓存内容校验，不缓存 I/O 失败。
_LOCATION_PANO_SOURCES: dict[str, bool] = {}
_LOCATION_PANO_CACHE_LIMIT = 4096


class StructuredDirectorStore:
    filename = "project.json"

    def __init__(self, project_directory: Path, project_id: str) -> None:
        if project_directory.is_symlink() or not project_directory.is_dir():
            raise ValueError("项目目录必须是普通目录。")
        self._project_directory = project_directory.resolve(strict=True)
        self._project_id = project_id
        self._path = self._project_directory / self.filename
        self._assets_directory = self._project_directory / "assets"
        self._generation_observations: dict[str, ReferenceGeneration] = {}
        self._domains: tuple = (
            ProjectDomain(self),
            ReferenceDomain(self),
            ScriptDomain(self),
            NarrationDomain(self),
            DialogueDomain(self),
            KeyframeDomain(self),
            LocationDomain(self),
            VideoDomain(self),
            RunDomain(self),
            FinalDomain(self),
            AssetDomain(self),
            GenerationDomain(self),
        )
        self._application_capture: list[StructuredDirectorDocument] | None = None
        self._provider_catalog: ProviderCatalog | None = None

    def _validate_video_recipe_switch(self, document, current, recipe_id):
        if self._provider_catalog is None:
            raise ValueError("视频 Provider 尚未配置。")
        self._provider_catalog.validate_recipe_switch(
            Capability.VIDEO_GENERATE, current, recipe_id, document.assets
        )
        found = next(
            (
                segment
                for scene in (
                    () if document.director_script is None else document.director_script.scenes
                )
                for segment in scene.segments
                if segment.id == current.segment_id
            ),
            None,
        )
        if found is not None and found.dialogue_lines:
            _plugin, recipe = self._provider_catalog.recipe_definition(
                Capability.VIDEO_GENERATE, recipe_id
            )
            if not any(slot.role is Role.REFERENCE_AUDIO for slot in recipe.slots):
                raise ValueError("含对白的 Segment 必须使用支持参考音频的 Ref2VA recipe。")

    def _bind_new_video_recipes(self, previous, document):
        if self._provider_catalog is None or document.video_plan is None:
            return document
        old_ids = (
            set()
            if previous.video_plan is None
            else {item.segment_id for item in previous.video_plan.segments}
        )
        segments = {
            segment.id: segment
            for scene in document.director_script.scenes
            for segment in scene_segments(scene)
        }
        changed = []
        for item in document.video_plan.segments:
            if item.segment_id not in old_ids and item.active_recipe is None:
                predicates = (
                    frozenset({DomainPredicate.SEGMENT_HAS_DIALOGUE})
                    if segments[item.segment_id].dialogue_lines
                    else frozenset()
                )
                found = self._provider_catalog.recipe_for(Capability.VIDEO_GENERATE, predicates)
                if found is not None:
                    item = replace(item, active_recipe=found[1].id)
            changed.append(item)
        return replace(document, video_plan=replace(document.video_plan, segments=tuple(changed)))

    def attach_provider_catalog(self, catalog: ProviderCatalog) -> None:
        """由 Service 注入已安装插件目录：写入时校验新增或改变的 recipe 参数，读取时提供
        当前生效的 recipe 声明。"""
        self._provider_catalog = catalog

    def provider_recipe_views(self) -> list[dict]:
        return [] if self._provider_catalog is None else self._provider_catalog.recipe_views()

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file() and not self._path.is_symlink()

    def create_project(
        self,
        *,
        title: str,
        aspect_ratio: ProjectAspectRatio,
        director_plan_markdown: str,
        narration_languages: tuple[NarrationLanguage, ...],
    ) -> StructuredDirectorDocument:
        if self._path.exists() or self._path.is_symlink():
            raise FileExistsError("项目状态已经建立。")
        document = StructuredDirectorDocument(
            schema_version=PROJECT_SCHEMA_VERSION,
            project_id=self._project_id,
            revision=1,
            title=title,
            aspect_ratio=aspect_ratio,
            director_plan_markdown=director_plan_markdown,
            narration_languages=narration_languages,
            status=StructuredDirectorStatus.AWAITING_PROPOSAL,
            workspace_layers=WorkspaceLayers(),
            reference_library=ReferenceLibrary(),
        )
        self._atomic_write(document, exclusive=True)
        return document

    def read(self) -> StructuredDirectorDocument:
        if self._path.is_symlink() or not self._path.is_file():
            raise FileNotFoundError("结构化导演台尚未建立。")
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("project.json 不是合法 JSON。") from exc
        document = _parse_document(value)
        if document.project_id != self._project_id:
            raise ValueError("project.json 的 project_id 与项目目录不一致。")
        return document

    def _unlocked_document(self, expected_revision: int) -> StructuredDirectorDocument:
        """项目未批准且没有 Director Agent 工作时可写；不限定审核阶段。"""
        document = self.read()
        if document.revision != expected_revision:
            raise RevisionConflictError("项目已更新，请重新读取后再保存。")
        if document.status is StructuredDirectorStatus.APPROVED:
            raise ValueError("请先显式重新开放生产。")
        if document.active_director_run is not None:
            raise ValueError("Director Agent 正在工作，请等待任务完成。")
        return document

    def execute_director_read(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt, dict[str, object]]:
        """在当前 revision 上返回裁剪事实，不写项目或推进 revision。

        读取不做 revision CAS：结果自带 revision，调用方据此决定后续写入的 expected_revision。
        """
        document = self.read()
        data = execute_project_read(
            document,
            name,
            arguments,
            provider_recipes=self.provider_recipe_views(),
            provider_catalog=self._provider_catalog,
        )
        return (
            document,
            CommandReceipt(
                command_id=command_id,
                status="noop",
                old_revision=document.revision,
                new_revision=document.revision,
                decision_summary="只读查询完成，项目没有发生修改。",
            ),
            data,
        )

    def update_generation(self, generation: ReferenceGeneration) -> StructuredDirectorDocument:
        aux_cell: dict[str, object] = {}

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, changed = _generation.update_generation(
                document, generation, timestamp=_generation_timestamp()
            )
            aux_cell["changed"] = changed
            return MutationResult(updated, None, write=changed)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        self._generation_observations[generation.id] = generation
        if not aux_cell["changed"]:
            return updated
        return updated

    def observed_generation(self, generation: ReferenceGeneration) -> ReferenceGeneration:
        """Disposable UI-only observation; never feed this projection back into domain decisions."""
        observed = self._generation_observations.get(generation.id)
        if observed is not None and observed.phase == generation.phase:
            return replace(generation, progress=observed.progress, message=observed.message)
        return generation

    def recover_interrupted_submissions(self) -> StructuredDirectorDocument:
        aux_cell: dict[str, bool] = {}

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, changed = _generation.recover_interrupted_submissions(
                document, timestamp=_generation_timestamp()
            )
            aux_cell["changed"] = changed
            return MutationResult(updated, None, write=changed)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated

    def read_asset(self, asset_id: str) -> tuple[Asset, bytes]:
        document = self.read()
        asset = next((item for item in document.assets if item.id == asset_id), None)
        if asset is None:
            raise FileNotFoundError("Asset 不存在。")
        path = self._project_directory / asset.relative_path
        if path.is_symlink() or not path.is_file():
            raise ValueError("Asset 文件不存在或类型不合法。")
        content = path.read_bytes()
        if len(content) != asset.byte_count or hashlib.sha256(content).hexdigest() != asset.sha256:
            raise ValueError("Asset 内容校验失败。")
        return asset, content

    def is_location_pano_source(self, asset: Asset) -> bool:
        if asset.media_type not in {"image/png", "image/jpeg"}:
            return False
        cached = _LOCATION_PANO_SOURCES.get(asset.sha256)
        if cached is None:
            try:
                _asset, content = self.read_asset(asset.id)
            except (OSError, ValueError):
                return False
            try:
                validate_pano_source(content)
                cached = True
            except ValueError:
                cached = False
            if len(_LOCATION_PANO_SOURCES) >= _LOCATION_PANO_CACHE_LIMIT:
                _LOCATION_PANO_SOURCES.pop(next(iter(_LOCATION_PANO_SOURCES)))
            _LOCATION_PANO_SOURCES[asset.sha256] = cached
        return cached

    def _editable_document(self, expected_revision: int) -> StructuredDirectorDocument:
        document = self.read()
        if document.revision != expected_revision:
            raise RevisionConflictError("项目已被更新，请重新读取后再保存。")
        if document.status not in {
            StructuredDirectorStatus.REVIEWING,
            StructuredDirectorStatus.REVIEWING_SCRIPT,
            StructuredDirectorStatus.REVIEWING_NARRATION,
            StructuredDirectorStatus.REVIEWING_KEYFRAMES,
            StructuredDirectorStatus.REVIEWING_VIDEOS,
            StructuredDirectorStatus.REVIEWING_FINAL,
        }:
            raise ValueError("引用库 proposal 完成前不能编辑卡片。")
        return document

    def _save_library(
        self, document: StructuredDirectorDocument, library: ReferenceLibrary
    ) -> StructuredDirectorDocument:
        """纯文档库保存（revision +1）；写入由调用方经 commit_mutation 负责。"""
        return replace(
            _apply_reference_library_change(document, library),
            revision=document.revision + 1,
        )

    def _ingest_asset(
        self,
        document: StructuredDirectorDocument,
        media_type: str,
        content: bytes,
        *,
        duration_seconds: float | None = None,
        directory: str,
        label: str,
        relative_path: str | None = None,
    ) -> tuple[StructuredDirectorDocument, Asset]:
        _validate_media_bytes(media_type, content)
        digest = hashlib.sha256(content).hexdigest()
        asset_id = digest[:32]
        existing = next((item for item in document.assets if item.id == asset_id), None)
        if existing is not None:
            if existing.sha256 != digest:
                raise ValueError("Asset ID 哈希冲突。")
            if relative_path is not None and existing.relative_path != relative_path:
                source = self._project_directory / existing.relative_path
                destination = self._project_directory / relative_path
                if destination.exists() or destination.is_symlink():
                    raise ValueError("Scene 成片覆盖目标已被其它文件占用。")
                os.replace(source, destination)
                moved = replace(existing, relative_path=relative_path)
                return replace(
                    document,
                    assets=tuple(
                        moved if item.id == existing.id else item for item in document.assets
                    ),
                ), moved
            return document, existing
        extension = _MEDIA_EXTENSION[media_type]
        safe_label = _asset_filename(label)
        relative_path = relative_path or (
            f"assets/{directory}/{safe_label}-{digest[:10]}.{extension}"
        )
        asset = Asset(
            asset_id,
            media_type,
            len(content),
            digest,
            relative_path,
            (
                _wav_duration(content)
                if media_type == "audio/wav"
                else (duration_seconds if duration_seconds is not None else _mp4_duration(content))
                if media_type == "video/mp4"
                else None
            ),
        )
        self._write_asset(asset, content)
        return replace(document, assets=(*document.assets, asset)), asset

    def _prepare_scene_output_overwrite(
        self,
        document: StructuredDirectorDocument,
        generation: ReferenceGeneration,
        directory: str,
        label: str,
        *,
        incoming_sha256: str,
    ) -> StructuredDirectorDocument:
        """Move the previous Scene output aside before replacing its physical file.

        Scene assembly and Animatic keep immutable Asset bytes and Generation history,
        but expose one stable current-output path per Scene/output kind. The previous
        file is archived under a hash-bearing name, so a re-render is a real filesystem
        replacement rather than only changing which card the Web UI displays.
        """
        current_path = f"assets/{directory}/{_asset_filename(label)}.mp4"
        # The current file remains authoritative even when its Generation card
        # has been dismissed from the UI. Prefer that physical path so a new
        # assembly can replace it without depending on card visibility.
        asset = next(
            (
                item
                for item in document.assets
                if item.relative_path == current_path and item.media_type == "video/mp4"
            ),
            None,
        )
        if asset is None:
            previous = next(
                (
                    item
                    for item in reversed(document.generations)
                    if item.kind is generation.kind
                    and item.target_id == generation.target_id
                    and item.language is generation.language
                    and item.phase is ReferenceGenerationPhase.SUCCEEDED
                    and item.output_asset_id is not None
                    and not item.dismissed
                ),
                None,
            )
            if previous is None or previous.output_asset_id is None:
                return document
            asset = next(
                (item for item in document.assets if item.id == previous.output_asset_id),
                None,
            )
        if asset is None or asset.sha256 == incoming_sha256:
            return document
        source = self._project_directory / asset.relative_path
        destination = self._project_directory / current_path
        if asset.relative_path != current_path and (
            destination.exists() or destination.is_symlink()
        ):
            raise ValueError("Scene 输出覆盖目标已被其它文件占用。")
        if source.is_symlink() or not source.is_file():
            raise ValueError("现有 Scene 输出文件不存在或类型不合法。")
        archive_path = (
            f"assets/{directory}/{_asset_filename(asset.display_name)}"
            f"-history-{asset.sha256[:10]}.mp4"
        )
        archive = self._project_directory / archive_path
        if archive.exists() or archive.is_symlink():
            raise ValueError("Scene 输出历史归档目标已被占用。")
        os.replace(source, archive)
        moved = replace(asset, relative_path=archive_path)
        return replace(
            document,
            assets=tuple(moved if item.id == asset.id else item for item in document.assets),
        )

    def _write_asset(self, asset: Asset, content: bytes) -> None:
        if self._assets_directory.is_symlink() or (
            self._assets_directory.exists() and not self._assets_directory.is_dir()
        ):
            raise ValueError("assets 必须是普通目录。")
        self._assets_directory.mkdir(exist_ok=True)
        destination = self._project_directory / asset.relative_path
        self._ensure_asset_directory(destination.parent)
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise ValueError("Asset 目标不是普通文件。")
            existing = destination.read_bytes()
            if hashlib.sha256(existing).hexdigest() != asset.sha256:
                raise ValueError("Asset 文件与内容哈希不一致。")
            return
        temporary = destination.parent / f".{asset.sha256}.{uuid4().hex}.tmp"
        try:
            with temporary.open("x+b") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _ensure_asset_directory(self, directory: Path) -> None:
        current = self._assets_directory
        for component in directory.relative_to(self._assets_directory).parts:
            current = current / component
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise ValueError("Asset 子目录必须是普通目录。")
            current.mkdir(exist_ok=True)

    def _atomic_write(
        self, document: StructuredDirectorDocument, *, exclusive: bool = False
    ) -> None:
        if self._application_capture is not None:
            self._application_capture.append(document)
            return
        document = attach_submission_request(self, document)
        pruned_plan = prune_reference_location_images(
            prune_reference_keyframes(document.keyframe_plan), document.location_library
        )
        if pruned_plan is not document.keyframe_plan:
            document = replace(document, keyframe_plan=pruned_plan)
        if not exclusive and self._path.is_file() and not self._path.is_symlink():
            previous = self.read()
            if document.narration_languages != previous.narration_languages:
                raise ValueError("项目旁白语言在创建后不可修改。")
            _assert_workspace_does_not_regress(previous, document)
            _check_changed_recipe_params(self._provider_catalog, previous, document)
            if document.revision != previous.revision + 1:
                raise RevisionConflictError("提交 revision 已失效，请重新读取项目后重试。")
        serialized = json.dumps(_serialize_document(document), ensure_ascii=False, indent=2) + "\n"
        temporary = self._project_directory / f".{self.filename}.{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as target:
                target.write(serialized)
                target.flush()
                os.fsync(target.fileno())
            if exclusive and (self._path.exists() or self._path.is_symlink()):
                raise FileExistsError("结构化导演台已经建立。")
            os.replace(temporary, self._path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def __getattr__(self, name: str):
        """P2-D1 facade 路由：public 方法已迁入 store/domains/ collaborator。

        同名同签名保留；实例属性未命中时按域顺序解析。私有助手仍定义在
        facade 上（正常属性查找优先，不经此路由）。
        """
        if name.startswith("_"):
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        domains = self.__dict__.get("_domains")
        if domains is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        for domain in domains:
            try:
                return object.__getattribute__(domain, name)
            except AttributeError:
                continue
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def __dir__(self) -> list[str]:
        return sorted({*super().__dir__(), *(d.__dir__() for d in self._domains)})


def _assert_workspace_does_not_regress(
    previous: StructuredDirectorDocument,
    current: StructuredDirectorDocument,
) -> None:
    layer_fields = (
        "narration_unlocked",
        "keyframes_unlocked",
        "videos_unlocked",
        "final_assembly_unlocked",
    )
    if any(
        getattr(previous.workspace_layers, field) and not getattr(current.workspace_layers, field)
        for field in layer_fields
    ):
        raise ValueError("已解锁的导演台内容层不能回退。")
    if (
        previous.keyframe_plan is not None
        and not _keyframe_plan_is_empty(previous.keyframe_plan)
        and current.keyframe_plan is None
    ):
        raise ValueError("已有内容的 Keyframe 计划不能在后续阶段消失。")
    if previous.video_plan is not None and current.video_plan is None:
        raise ValueError("已建立的视频计划不能在后续阶段消失。")


def _keyframe_plan_is_empty(plan: KeyframePlan) -> bool:
    return all(
        not item.prompt_text.strip() and item.selected_asset_id is None for item in plan.keyframes
    ) and all(
        not item.start_enabled and not item.end_enabled and not item.reference_asset_ids
        for item in plan.segments
    )


def _keyframe_is_enabled(plan: KeyframePlan, keyframe_id: str) -> bool:
    return any(
        (item.start_enabled and item.start_keyframe_id == keyframe_id)
        or (item.end_enabled and item.end_keyframe_id == keyframe_id)
        for item in plan.segments
    )


def _validate_proposal_references(
    proposal: StructuredDirectorScriptProposal,
    library: ReferenceLibrary,
) -> None:
    character_ids = {item.id for item in library.characters}
    for scene in proposal.scenes:
        for shot in scene.shots:
            if any(item not in character_ids for item in shot.visible_character_ids):
                raise ValueError("Shot 引用了不存在的可见角色卡。")
        for segment in scene.segments:
            if any(
                line.character_id is not None and line.character_id not in character_ids
                for line in segment.dialogue_lines
            ):
                raise ValueError("角色对白引用了不存在的角色卡。")


def _generation_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _scene_id_for_segment(
    document: StructuredDirectorDocument,
    segment_id: str,
) -> str:
    script = document.director_script
    if script is None:
        raise ValueError("结构化导演脚本尚未建立。")
    for scene in script.scenes:
        if any(segment.id == segment_id for segment in scene_segments(scene)):
            return scene.id
    raise ValueError("Segment 视频计划不存在。")


def _require_generation(
    document: StructuredDirectorDocument, generation_id: str
) -> ReferenceGeneration:
    generation = next((item for item in document.generations if item.id == generation_id), None)
    if generation is None:
        raise ValueError("Generation 不存在。")
    return generation


def _generation_timestamp() -> str:
    return datetime.now(UTC).isoformat()


# P2-D1：domains collaborator 在模块尾部导入（域方法经 __getattr__ 回退引用
# 本模块的 read/_editable_document/persistence 私有助手；尾部导入保证助手已绑定）。
from ._domains import (  # noqa: E402
    AssetDomain,
    DialogueDomain,
    FinalDomain,
    GenerationDomain,
    KeyframeDomain,
    LocationDomain,
    NarrationDomain,
    ProjectDomain,
    ReferenceDomain,
    RunDomain,
    ScriptDomain,
    VideoDomain,
)
