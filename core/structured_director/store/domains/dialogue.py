"""store dialogue 域：对白 TTS 候选选择与真实时序写入。"""

from __future__ import annotations

from core.director_commands import CommandReceipt, DialogueTimingUpdate
from core.model_providers.recipe import RecipeParams
from core.structured_director.errors import RevisionConflictError
from core.structured_director.models import StructuredDirectorDocument
from core.structured_director.mutations import dialogue as _dialogue
from core.structured_director.repair_mutations import _repair_invalidated_items
from core.structured_director.store.pipeline import MutationResult, commit_mutation


class _DomainBase:
    def __init__(self, store) -> None:
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name):
        if name == "_store":
            raise AttributeError(name)
        return getattr(object.__getattribute__(self, "_store"), name)


class DialogueDomain(_DomainBase):
    def update_dialogue_recipe_params(
        self,
        *,
        dialogue_line_id: str,
        recipe_params: RecipeParams,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        return self._commit(
            expected_revision,
            lambda document: _dialogue.update_dialogue_recipe_params(
                document,
                dialogue_line_id=dialogue_line_id,
                recipe_params=recipe_params,
            ),
        )

    def select_dialogue_audio(
        self,
        *,
        dialogue_line_id: str,
        generation_id: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        return self._commit(
            expected_revision,
            lambda document: _dialogue.select_dialogue_audio(
                document,
                dialogue_line_id=dialogue_line_id,
                generation_id=generation_id,
            ),
        )

    def set_dialogue_timing(
        self,
        *,
        segment_id: str,
        starts: dict[str, float],
        duration_seconds: float,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        return self._commit(
            expected_revision,
            lambda document: _dialogue.set_dialogue_timing(
                document,
                segment_id=segment_id,
                starts=starts,
                duration_seconds=duration_seconds,
            ),
        )

    def auto_calibrate_dialogue_timings(
        self, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        return self._commit(
            expected_revision,
            _dialogue.auto_calibrate_dialogue_timings,
        )

    def set_dialogue_timing_command(
        self,
        update: DialogueTimingUpdate,
        *,
        expected_revision: int,
        command_id: str,
    ) -> tuple[StructuredDirectorDocument, CommandReceipt]:
        def mutate(document):
            containing = (
                next(
                    (
                        scene.id
                        for scene in document.director_script.scenes
                        for segment in scene.segments
                        if segment.id == update.segment_id
                    ),
                    None,
                )
                if document.director_script is not None
                else None
            )
            if containing is None or containing not in update.scope_scene_ids:
                raise ValueError("dialogue.set_timing 超出已授权 Scene scope。")
            updated = _dialogue.set_dialogue_timing(
                document,
                segment_id=update.segment_id,
                starts=dict(update.starts),
                duration_seconds=update.duration_seconds,
            )
            return MutationResult(
                updated,
                CommandReceipt(
                    command_id,
                    "succeeded",
                    document.revision,
                    updated.revision,
                    changed_ids=(update.segment_id, *(line_id for line_id, _ in update.starts)),
                    invalidated=_repair_invalidated_items(document, updated),
                    preserved=("asset_history", "generation_history"),
                    decision_summary="已按真实 TTS 音频保存对白起点并校准 Segment 时长。",
                    next_allowed_actions=("video.generate",),
                ),
            )

        return commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )

    def _commit(self, expected_revision, mutate):
        def load():
            document = self.read()
            if not self.revision_matches(document, expected_revision):
                raise RevisionConflictError("项目已更新，请刷新后重试对白操作。")
            return document

        def apply(document):
            candidate = mutate(document)
            return MutationResult(candidate, None, write=candidate is not document)

        updated, _receipt = commit_mutation(
            self,
            loader=load,
            mutator=apply,
        )
        return updated
