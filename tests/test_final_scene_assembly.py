"""最终成片只拼接 Scene 成片：缺失或过期的 Scene 成片必须阻止装配。"""

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from test_architecture_acceptance import mixed_acceptance
from test_director_commands import _visual_project

from core.director_commands import GenerationTarget
from core.structured_director import (
    FinalAssemblyClip,
    FinalAssemblyPlan,
    GenerationOperation,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    StructuredDirectorStatus,
)
from core.structured_director.assembly_timeline import (
    _build_final_assembly_plan,
    _current_scene_final_asset_id,
    _scenes_missing_final,
    scene_final_input_asset_ids,
)
from core.structured_director.models import (
    NARRATION_LANGUAGES,
    FinalNarrationPlacement,
    NarrationLanguage,
    SceneAssemblyClip,
    SceneAssemblyPlan,
)


def _mp4(marker: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftypisom" + marker + b"\x00" * 32


def test_final_assembly_plan_references_scene_finals_in_script_order(tmp_path):
    document = asyncio.run(mixed_acceptance(tmp_path))

    plan = _build_final_assembly_plan(document)

    assert [clip.scene_id for clip in plan.clips] == [
        scene.id for scene in document.director_script.scenes
    ]
    assert plan.source_script_revision == document.director_script.revision
    # 成片计划不再携带 Segment 或旁白；它们已经固化在 Scene 成片字节里。
    assert not hasattr(plan, "narrations")
    for clip in plan.clips:
        for language in NARRATION_LANGUAGES:
            assert _current_scene_final_asset_id(
                document, clip.scene_id, language
            ) == clip.asset_id(language)
    assert _scenes_missing_final(document) == ()


def test_final_assembly_plan_lists_scenes_without_a_current_scene_final(tmp_path):
    document = asyncio.run(mixed_acceptance(tmp_path))
    missing_scene = document.director_script.scenes[0]

    hidden = replace(
        document,
        generations=tuple(
            replace(item, dismissed=True)
            if item.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO
            and item.target_id == missing_scene.id
            else item
            for item in document.generations
        ),
    )

    assert _scenes_missing_final(hidden) == (missing_scene.id,)
    with pytest.raises(ValueError, match="Scene 成片"):
        _build_final_assembly_plan(hidden)


def test_stale_scene_final_is_rejected_even_though_it_exists(tmp_path):
    document = asyncio.run(mixed_acceptance(tmp_path))
    first_scene, second_scene = document.director_script.scenes[:2]
    stale_segment = first_scene.shots[0].segments[0].id
    # 把第一个 Scene 的 Segment 选择换成另一个 MP4，使它的 Scene 成片过期。
    replacement_asset_id = next(
        generation.output_asset_id
        for generation in document.generations
        if generation.kind is ReferenceGenerationKind.SCENE_FINAL_VIDEO
        and generation.target_id == second_scene.id
        and not generation.dismissed
    )
    stale = replace(
        document,
        video_plan=replace(
            document.video_plan,
            segments=tuple(
                replace(item, selected_asset_id=replacement_asset_id, upscaled_asset_id=None)
                if item.segment_id == stale_segment
                else item
                for item in document.video_plan.segments
            ),
        ),
    )

    assert _current_scene_final_asset_id(stale, first_scene.id, NarrationLanguage.ZH) is None
    assert _current_scene_final_asset_id(stale, first_scene.id, NarrationLanguage.EN) is None
    assert _scenes_missing_final(stale) == (first_scene.id,)
    with pytest.raises(ValueError, match="Scene 成片"):
        _build_final_assembly_plan(stale)


def _seeded_final_document(tmp_path: Path, content: bytes):
    store, _service, document, _route = asyncio.run(_visual_project(str(tmp_path)))
    document, asset = store._ingest_asset(
        document,
        "video/mp4",
        content,
        duration_seconds=1.0,
        directory="videos/scene-final",
        label="Scene-01-最终装配测试-Scene成片",
    )
    document = replace(
        document,
        revision=document.revision + 1,
        status=StructuredDirectorStatus.REVIEWING_FINAL,
        workspace_layers=replace(document.workspace_layers, final_assembly_unlocked=True),
        final_assembly=FinalAssemblyPlan(
            document.director_script.revision,
            tuple(
                FinalAssemblyClip(scene.id, asset.id, asset.id, None)
                for scene in document.director_script.scenes
            ),
        ),
    )
    store._atomic_write(document)
    return store, document, asset


def _queued_generation(
    scene_id: str,
    *,
    input_asset_ids: tuple[str, ...],
    phase: ReferenceGenerationPhase = ReferenceGenerationPhase.QUEUED,
    output_asset_id: str | None = None,
) -> ReferenceGeneration:
    return ReferenceGeneration(
        id="c" * 32,
        kind=ReferenceGenerationKind.SCENE_FINAL_VIDEO,
        operation=GenerationOperation.ASSEMBLE,
        target_id=scene_id,
        phase=phase,
        progress=0.0,
        message="Scene 成片装配",
        prompt_text="最终装配失效测试",
        input_asset_ids=input_asset_ids,
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
        language=NarrationLanguage.ZH,
    )


def test_each_language_scene_final_depends_on_both_narrations():
    """画面按中英较长旁白对齐：任一语言旁白变化都要让两版 Scene 成片过期。"""
    zh_audio, en_audio, clip_asset = "1" * 32, "2" * 32, "3" * 32
    plan = SceneAssemblyPlan(
        1,
        (SceneAssemblyClip("4" * 32, clip_asset, None),),
        (FinalNarrationPlacement("5" * 32, zh_audio, "4" * 32, 6.0),),
        NarrationLanguage.ZH,
        (zh_audio, en_audio),
    )
    assert scene_final_input_asset_ids(plan) == (clip_asset, zh_audio, en_audio)


def test_completing_a_scene_final_invalidates_the_derived_final_plan(tmp_path: Path) -> None:
    store, document, asset = _seeded_final_document(tmp_path, _mp4(b"scene-final"))
    scene_id = document.director_script.scenes[0].id
    generation = _queued_generation(scene_id, input_asset_ids=(asset.id,))
    document = replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, generation),
    )
    store._atomic_write(document)

    content = _mp4(b"completed")
    completed = store.complete_generation(
        generation,
        media_type="video/mp4",
        content=content,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_byte_count=len(content),
        actual_duration_seconds=1.0,
    )

    assert completed.final_assembly is None


def test_dismissing_a_scene_final_invalidates_the_derived_final_plan(tmp_path: Path) -> None:
    store, document, asset = _seeded_final_document(tmp_path, _mp4(b"scene-final"))
    scene_id = document.director_script.scenes[0].id
    generation = _queued_generation(
        scene_id,
        input_asset_ids=(asset.id,),
        phase=ReferenceGenerationPhase.SUCCEEDED,
        output_asset_id=asset.id,
    )
    document = replace(
        document,
        revision=document.revision + 1,
        generations=(*document.generations, generation),
    )
    store._atomic_write(document)

    dismissed, _receipt = store.dismiss_generation_command(
        GenerationTarget(generation.id),
        expected_revision=document.revision,
        command_id=f"test-final-scene-assembly:{document.revision}:{generation.id}",
    )

    assert dismissed.final_assembly is None
