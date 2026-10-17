"""store/domains/asset：asset 域 collaborator（P2-D1）。

方法体自 store facade 逐字迁移（行为保持）；未在域上定义的名字经
__getattr__ 回退到 StructuredDirectorStore（read/_editable_document/
persistence 私有助手等）。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from core.structured_director.application_requests import prune_generation_references
from core.structured_director.asset_metadata import _uploaded_asset_label as _uploaded_asset_label
from core.structured_director.models import (
    CharacterCard,
    ImageAssetCategory,
    NarrationLanguage,
    NarratorProfile,
    StructuredDirectorDocument,
)
from core.structured_director.mutations import asset as _asset_mutations
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


class AssetDomain(_DomainBase):
    def save_character(
        self,
        card: CharacterCard,
        *,
        expected_revision: int,
        must_exist: bool,
        created_look_ids: frozenset[str] = frozenset(),
    ) -> StructuredDirectorDocument:
        """整卡保存；造型 ID 只能是该卡已有的，或本次由 Core 新分配的。"""

        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            existing = {item.id: item for item in document.reference_library.characters}
            if (card.id in existing) is not must_exist:
                raise ValueError("角色卡不存在。" if must_exist else "角色卡 ID 已存在。")
            previous = existing.get(card.id)
            known = {item.id: item for item in previous.looks} if previous is not None else {}
            if not {item.id for item in card.looks} <= set(known) | created_look_ids:
                raise ValueError("造型 ID 不存在；新造型的 id 必须为 null。")
            # 整卡保存只改造型文字；造型图只经人类选择入口改变，这里沿用已有选择。
            saved = replace(
                card,
                looks=tuple(
                    replace(
                        item,
                        selected_asset_id=known[item.id].selected_asset_id
                        if item.id in known
                        else None,
                    )
                    for item in card.looks
                ),
            )
            existing[card.id] = saved
            return MutationResult(
                self._save_library(
                    document,
                    replace(document.reference_library, characters=tuple(existing.values())),
                ),
                None,
            )

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def save_narrator(
        self, profile: NarratorProfile, *, expected_revision: int
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            current = document.reference_library.narrator
            if current is None or current.id != profile.id:
                raise ValueError("旁白音色身份不存在。")
            return MutationResult(
                self._save_library(document, replace(document.reference_library, narrator=profile)),
                None,
            )

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def discard_card(
        self, card_id: str, *, kind: str, expected_revision: int
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            if kind == "characters":
                cards = tuple(
                    item for item in document.reference_library.characters if item.id != card_id
                )
                if len(cards) == len(document.reference_library.characters):
                    raise ValueError("角色卡不存在。")
                library = replace(document.reference_library, characters=cards)
            else:
                raise ValueError("未知的卡片类型。")
            return MutationResult(self._save_library(document, library), None)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def import_image_asset(
        self,
        *,
        media_type: str,
        content: bytes,
        category: ImageAssetCategory,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            directory = _asset_mutations.validate_image_import(media_type, category)
            updated, asset = self._ingest_asset(
                document,
                media_type,
                content,
                directory=directory,
                label=_uploaded_asset_label(filename, "导入图片"),
            )
            _asset_mutations.check_imported_category(asset, category)
            bumped = _asset_mutations.bump_ingested(document, updated)
            return MutationResult(bumped, None, write=bumped is not document)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._unlocked_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def import_media_asset(
        self,
        *,
        media_type: str,
        content: bytes,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            directory = _asset_mutations.validate_media_import(media_type)
            updated, _asset = self._ingest_asset(
                document,
                media_type,
                content,
                directory=directory,
                label=_uploaded_asset_label(
                    filename, "导入音频" if media_type == "audio/wav" else "导入视频"
                ),
            )
            bumped = _asset_mutations.bump_ingested(document, updated)
            return MutationResult(bumped, None, write=bumped is not document)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._unlocked_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def create_audio_effect_copy(
        self,
        *,
        source_asset_id: str,
        output_content: bytes,
        effect_record: str,
        preset: str,
        seed: int,
        processor_version: int,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            source = _asset_mutations.validate_audio_effect_request(
                document, source_asset_id=source_asset_id, effect_record=effect_record
            )
            document, output = self._ingest_asset(
                document,
                "audio/wav",
                output_content,
                directory="audio/effects",
                label=f"{source.display_name.rsplit('.', 1)[0]}-{preset}",
            )
            generation_id = uuid4().hex
            generation = _asset_mutations.build_audio_effect_generation(
                source=source,
                output_asset_id=output.id,
                effect_record=effect_record,
                seed=seed,
                processor_version=processor_version,
                generation_id=generation_id,
                now=_generation_timestamp(),
            )
            return MutationResult(_asset_mutations.append_generation(document, generation), None)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def create_audio_trim_copy(
        self,
        *,
        source_asset_id: str,
        output_content: bytes,
        trim_record: str,
        start_seconds: float,
        end_seconds: float,
        output_duration_seconds: float,
        processor_version: int,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            source = _asset_mutations.validate_audio_trim_request(
                document, source_asset_id=source_asset_id, trim_record=trim_record
            )
            document, output = self._ingest_asset(
                document,
                "audio/wav",
                output_content,
                directory="audio/trims",
                label=(
                    f"{source.display_name.rsplit('.', 1)[0]}-截取-"
                    f"{start_seconds:.2f}-{end_seconds:.2f}秒"
                ),
            )
            generation_id = uuid4().hex
            generation = _asset_mutations.build_audio_trim_generation(
                source=source,
                output_asset_id=output.id,
                trim_record=trim_record,
                output_duration_seconds=output_duration_seconds,
                processor_version=processor_version,
                generation_id=generation_id,
                now=_generation_timestamp(),
            )
            return MutationResult(_asset_mutations.append_generation(document, generation), None)

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def delete_asset(self, asset_id: str, *, expected_revision: int) -> StructuredDirectorDocument:
        return self.delete_assets((asset_id,), expected_revision=expected_revision)

    def delete_assets(
        self, asset_ids: tuple[str, ...], *, expected_revision: int
    ) -> StructuredDirectorDocument:
        # 删除的文件 stage/回滚包裹写入本身，无法收敛进 commit_mutation，
        # 此处保留显式 _atomic_write；文档计划已纯函数化入 L2。
        document = self._editable_document(expected_revision)
        updated, deleted_assets = _asset_mutations.plan_asset_deletion(
            document, asset_ids, prune_generation_references
        )
        sources = tuple(
            (item, self._project_directory / item.relative_path) for item in deleted_assets
        )
        for _, source in sources:
            if source.is_symlink() or not source.is_file():
                raise ValueError("Asset 文件不存在或类型不合法。")
        staged_files: list[tuple[Path, Path]] = []
        try:
            for item, source in sources:
                staged = self._assets_directory / f".deleting-{item.sha256}-{uuid4().hex}"
                os.replace(source, staged)
                staged_files.append((staged, source))
        except Exception:
            for staged, source in reversed(staged_files):
                os.replace(staged, source)
            raise
        try:
            self._atomic_write(updated)
        except Exception:
            for staged, source in reversed(staged_files):
                os.replace(staged, source)
            raise
        for staged, _ in staged_files:
            staged.unlink(missing_ok=True)
        return updated

    def select_look_asset(
        self,
        *,
        card_id: str,
        look_id: str,
        asset_id: str,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=lambda document: MutationResult(
                _asset_mutations.select_look_asset(
                    document, card_id=card_id, look_id=look_id, asset_id=asset_id
                ),
                None,
            ),
        )
        return updated

    def attach_uploaded_voice(
        self,
        *,
        card_id: str,
        media_type: str,
        content: bytes,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            _asset_mutations.validate_uploaded_voice_media(media_type)
            prospective_asset_id = hashlib.sha256(content).hexdigest()[:32]
            prospective_library = _asset_mutations.prospective_voice_library(
                document, card_id=card_id, prospective_asset_id=prospective_asset_id
            )
            prepared, asset = self._ingest_asset(
                document,
                media_type,
                content,
                directory="audio/voice-references",
                label=_uploaded_asset_label(
                    filename, _asset_mutations.uploaded_voice_label(document, card_id)
                ),
            )
            _asset_mutations.check_prospective_voice_asset(asset, prospective_asset_id)
            return MutationResult(
                _asset_mutations.apply_uploaded_voice(prepared, library=prospective_library),
                None,
            )

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated

    def attach_uploaded_narrator_voice(
        self,
        *,
        narrator_id: str,
        language: NarrationLanguage,
        media_type: str,
        content: bytes,
        filename: str | None = None,
        expected_revision: int,
    ) -> StructuredDirectorDocument:
        def mutate(document: StructuredDirectorDocument) -> MutationResult:
            _asset_mutations.validate_narrator_voice_target(
                document, narrator_id=narrator_id, media_type=media_type
            )
            if language not in document.narration_languages:
                raise ValueError("项目未启用该旁白语言。")
            document, asset = self._ingest_asset(
                document,
                media_type,
                content,
                directory="audio/voice-references",
                label=_uploaded_asset_label(
                    filename, _asset_mutations.narrator_voice_label(document, language)
                ),
            )
            return MutationResult(
                _asset_mutations.apply_uploaded_narrator_voice(
                    document, narrator_id=narrator_id, language=language, asset_id=asset.id
                ),
                None,
            )

        updated, _receipt = commit_mutation(
            self,
            loader=lambda: self._editable_document(expected_revision),
            mutator=mutate,
        )
        return updated
