"""store/domains/generation：generation 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

from core.director_commands import CommandReceipt, GenerationTarget
from core.structured_director.asset_metadata import _asset_filename as _asset_filename
from core.structured_director.asset_metadata import (
    _generation_asset_location as _generation_asset_location,
)
from core.structured_director.models import (
    ReferenceGeneration,
    ReferenceGenerationKind,
    StructuredDirectorDocument,
)
from core.structured_director.mutations import generation as _generation
from core.structured_director.reads.workflow_state import (
    require_workflow_action as require_workflow_action,
)
from core.structured_director.store import _generation_timestamp as _generation_timestamp
from core.structured_director.store.pipeline import MutationResult as MutationResult
from core.structured_director.store.pipeline import commit_mutation as commit_mutation


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class GenerationDomain(_DomainBase):
    def attach_generation_output(
        self,
        *,
        kind: str,
        card_id: str,
        generation_id: str,
        note: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=lambda document: MutationResult(
                _generation.attach_generation_output(
                    document,
                    kind=kind,
                    card_id=card_id,
                    generation_id=generation_id,
                    note=note,
                ),
                None,
            ),
        )
        return updated

    def select_look_sheet(
        self,
        *,
        card_id: str,
        look_id: str,
        generation_id: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=lambda document: MutationResult(
                _generation.select_look_sheet(
                    document,
                    card_id=card_id,
                    look_id=look_id,
                    generation_id=generation_id,
                ),
                None,
            ),
        )
        return updated

    def create_generation(
        self, generation: ReferenceGeneration, *, expected_revision: int
    ) -> StructuredDirectorDocument:

        def load() -> StructuredDirectorDocument:
            return self._editable_document(expected_revision)

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            _generation.validate_generation_target(document, generation)
            return MutationResult(
                _generation.stage_generation(
                    document, generation, timestamp=_generation_timestamp()
                ),
                None,
            )

        updated, _receipt = commit_mutation(self, loader=load, mutator=mutate)
        return updated

    def create_generations(
        self,
        generations: tuple[ReferenceGeneration, ...],
        *,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=lambda document: MutationResult(
                _generation.create_generations(
                    document, generations, timestamp=_generation_timestamp()
                ),
                None,
            ),
        )
        return updated

    def dismiss_generation_command(
        self,
        target: GenerationTarget,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            updated, receipt, write = _generation.dismiss_generation(
                document, target, command_id=command_id, timestamp=_generation_timestamp()
            )
            return MutationResult(updated, receipt, write=write)

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def complete_generation(
        self,
        generation: ReferenceGeneration,
        *,
        media_type: str,
        content: bytes,
        expected_sha256: str,
        expected_byte_count: int,
        actual_duration_seconds: float | None = None,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            _generation.validate_completion_payload(
                generation,
                media_type=media_type,
                content=content,
                expected_sha256=expected_sha256,
                expected_byte_count=expected_byte_count,
            )
            duration_seconds = actual_duration_seconds or generation.duration_seconds
            if (
                actual_duration_seconds is None
                and generation.kind is ReferenceGenerationKind.VIDEO_UPSCALE
            ):
                source = next(
                    item for item in document.assets if item.id == generation.input_asset_ids[0]
                )
                duration_seconds = source.duration_seconds
            directory, label = _generation_asset_location(document, generation)
            relative_path = None
            if generation.kind in {
                ReferenceGenerationKind.SCENE_FINAL_VIDEO,
                ReferenceGenerationKind.SCENE_ANIMATIC,
            }:
                document = self._prepare_scene_output_overwrite(
                    document,
                    generation,
                    directory,
                    label,
                    incoming_sha256=expected_sha256,
                )
                relative_path = f"assets/{directory}/{_asset_filename(label)}.mp4"
            document, asset = self._ingest_asset(
                document,
                media_type,
                content,
                duration_seconds=duration_seconds,
                directory=directory,
                label=label,
                relative_path=relative_path,
            )
            updated = _generation.complete_generation_document(
                document, generation, asset_id=asset.id, timestamp=_generation_timestamp()
            )
            return MutationResult(updated, None)

        updated, _receipt = commit_mutation(self, loader=self.read, mutator=mutate)
        return updated
