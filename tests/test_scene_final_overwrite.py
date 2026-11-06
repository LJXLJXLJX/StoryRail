import hashlib
from dataclasses import replace
from pathlib import Path

from core.director_commands import GenerationTarget
from core.project_settings import ProjectAspectRatio
from core.structured_director import (
    GenerationOperation,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorStatus,
    StructuredDirectorStore,
)


def _mp4(marker: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + marker + b"\x00" * 32


def _generation(
    generation_id: str,
    *,
    kind: ReferenceGenerationKind = ReferenceGenerationKind.SCENE_FINAL_VIDEO,
    phase: ReferenceGenerationPhase,
    output_asset_id: str | None,
    target_id: str,
    input_asset_id: str | None,
) -> ReferenceGeneration:
    return ReferenceGeneration(
        id=generation_id,
        kind=kind,
        operation=GenerationOperation.ASSEMBLE,
        target_id=target_id,
        phase=phase,
        progress=1.0 if phase is ReferenceGenerationPhase.SUCCEEDED else 0.0,
        message="完成" if phase is ReferenceGenerationPhase.SUCCEEDED else "提交中",
        prompt_text="Scene 成片文件覆盖测试",
        input_asset_ids=() if input_asset_id is None else (input_asset_id,),
        sample_text=None,
        seed=None,
        plugin_id="test.ffmpeg",
        plugin_version=1,
        external_id="external",
        output_asset_id=output_asset_id,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=1.0,
        language=(
            NarrationLanguage.ZH if kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO else None
        ),
    )


def test_scene_final_replaces_current_file_and_archives_previous_bytes(tmp_path: Path) -> None:
    project_id = "a" * 32
    project = tmp_path / project_id
    project.mkdir()
    store = StructuredDirectorStore(project, project_id)
    document = store.create_project(
        title="覆盖测试",
        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案\n\nScene 成片覆盖。",
        narration_languages=tuple(NarrationLanguage),
    )
    old_content = _mp4(b"old")
    new_content = _mp4(b"new")
    document, old_asset = store._ingest_asset(
        document,
        "video/mp4",
        old_content,
        duration_seconds=1.0,
        directory="videos/scene-final",
        label="Scene-01-覆盖测试-Scene成片",
    )
    target_id = "b" * 32
    previous = _generation(
        "c" * 32,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        output_asset_id=old_asset.id,
        target_id=target_id,
        input_asset_id=old_asset.id,
    )
    document = replace(document, revision=document.revision + 1, generations=(previous,))
    store._atomic_write(document)

    current = _generation(
        "d" * 32,
        phase=ReferenceGenerationPhase.QUEUED,
        output_asset_id=None,
        target_id=target_id,
        input_asset_id=old_asset.id,
    )
    document = replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, current),
    )
    store._atomic_write(document)
    document = store.complete_generation(
        current,
        media_type="video/mp4",
        content=new_content,
        expected_sha256=hashlib.sha256(new_content).hexdigest(),
        expected_byte_count=len(new_content),
        actual_duration_seconds=1.0,
    )

    assert next(item for item in document.generations if item.id == previous.id).dismissed
    completed = next(item for item in document.generations if item.id == current.id)
    assert completed.output_asset_id is not None
    output = next(item for item in document.assets if item.id == completed.output_asset_id)
    archived = next(item for item in document.assets if item.id == old_asset.id)
    assert output.relative_path == "assets/videos/scene-final/Scene-未定位-Scene成片-中文.mp4"
    assert "-history-" in archived.relative_path
    assert (project / output.relative_path).read_bytes() == new_content
    assert (project / archived.relative_path).read_bytes() == old_content
    assert not (project / old_asset.relative_path).exists()

    newest_content = _mp4(b"newest")
    newest = _generation(
        "e" * 32,
        phase=ReferenceGenerationPhase.QUEUED,
        output_asset_id=None,
        target_id=target_id,
        input_asset_id=old_asset.id,
    )
    document = replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, newest),
    )
    store._atomic_write(document)
    document = store.complete_generation(
        newest,
        media_type="video/mp4",
        content=newest_content,
        expected_sha256=hashlib.sha256(newest_content).hexdigest(),
        expected_byte_count=len(newest_content),
        actual_duration_seconds=1.0,
    )

    newest_completed = next(item for item in document.generations if item.id == newest.id)
    assert next(item for item in document.generations if item.id == current.id).dismissed
    assert not newest_completed.dismissed
    newest_output = next(
        item for item in document.assets if item.id == newest_completed.output_asset_id
    )
    replaced_output = next(item for item in document.assets if item.id == output.id)
    assert newest_output.relative_path == output.relative_path
    assert (project / newest_output.relative_path).read_bytes() == newest_content
    assert "-history-" in replaced_output.relative_path
    assert (project / replaced_output.relative_path).read_bytes() == new_content

    document = replace(
        document,
        revision=document.revision + 1,
        status=StructuredDirectorStatus.REVIEWING,
    )
    store._atomic_write(document)
    hidden, _receipt = store.dismiss_generation_command(
        GenerationTarget(newest.id),
        expected_revision=document.revision,
        command_id=f"test-scene-final-overwrite:{document.revision}:{newest.id}",
    )
    assert all(
        item.dismissed
        for item in hidden.generations
        if item.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO and item.target_id == target_id
    )


def test_scene_animatic_replaces_current_file_and_deletes_history_as_one_output(
    tmp_path: Path,
) -> None:
    project_id = "f" * 32
    project = tmp_path / project_id
    project.mkdir()
    store = StructuredDirectorStore(project, project_id)
    document = store.create_project(
        title="Animatic 覆盖测试",
        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案\n\nAnimatic 覆盖。",
        narration_languages=tuple(NarrationLanguage),
    )
    old_content = _mp4(b"animatic-old")
    new_content = _mp4(b"animatic-new")
    document, old_asset = store._ingest_asset(
        document,
        "video/mp4",
        old_content,
        duration_seconds=1.0,
        directory="videos/animatics",
        label="Scene-01-覆盖测试-Animatic预览",
    )
    document, input_asset = store._ingest_asset(
        document,
        "image/png",
        b"\x89PNG\r\n\x1a\nanimatic-input",
        directory="images/keyframes",
        label="Animatic 输入",
    )
    target_id = "e" * 32
    previous = _generation(
        "1" * 32,
        kind=ReferenceGenerationKind.SCENE_ANIMATIC,
        phase=ReferenceGenerationPhase.SUCCEEDED,
        output_asset_id=old_asset.id,
        target_id=target_id,
        input_asset_id=input_asset.id,
    )
    document = replace(document, revision=document.revision + 1, generations=(previous,))
    store._atomic_write(document)

    current = _generation(
        "2" * 32,
        kind=ReferenceGenerationKind.SCENE_ANIMATIC,
        phase=ReferenceGenerationPhase.QUEUED,
        output_asset_id=None,
        target_id=target_id,
        input_asset_id=input_asset.id,
    )
    document = replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, current),
    )
    store._atomic_write(document)
    document = store.complete_generation(
        current,
        media_type="video/mp4",
        content=new_content,
        expected_sha256=hashlib.sha256(new_content).hexdigest(),
        expected_byte_count=len(new_content),
        actual_duration_seconds=1.0,
    )

    assert next(item for item in document.generations if item.id == previous.id).dismissed
    completed = next(item for item in document.generations if item.id == current.id)
    assert completed.output_asset_id is not None
    output = next(item for item in document.assets if item.id == completed.output_asset_id)
    archived = next(item for item in document.assets if item.id == old_asset.id)
    assert output.relative_path == "assets/videos/animatics/Scene-未定位-Animatic预览.mp4"
    assert "-history-" in archived.relative_path
    assert (project / output.relative_path).read_bytes() == new_content
    assert (project / archived.relative_path).read_bytes() == old_content

    document = replace(
        document,
        revision=document.revision + 1,
        status=StructuredDirectorStatus.REVIEWING,
    )
    store._atomic_write(document)
    hidden, _receipt = store.dismiss_generation_command(
        GenerationTarget(completed.id),
        expected_revision=document.revision,
        command_id=f"test-scene-final-overwrite:{document.revision}:{completed.id}",
    )
    assert all(
        item.dismissed
        for item in hidden.generations
        if item.kind is ReferenceGenerationKind.SCENE_ANIMATIC and item.target_id == target_id
    )
