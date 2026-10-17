"""重构保护：schema、原子失败与恢复不依赖 Store 内部文件布局。"""

import copy
import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from core.project_settings import ProjectAspectRatio
from core.structured_director.codec import serialize_document
from core.structured_director.models import (
    GenerationOperation,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)
from core.structured_director.store import StructuredDirectorStore


@pytest.fixture
def store(tmp_path):
    result = StructuredDirectorStore(tmp_path, "a" * 32)
    result.create_project(
        title="序列化边界",
        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 原始方案\n完整保留。",
        narration_languages=tuple(NarrationLanguage),
    )
    return result


def test_roundtrip_preserves_active_run_and_original_directive(store):
    document, resumed = store.begin_reference_proposal()
    assert resumed is False
    reopened = StructuredDirectorStore(store.path.parent, document.project_id)
    restored = reopened.read()
    assert serialize_document(restored) == serialize_document(document)
    assert restored.active_director_run == document.active_director_run
    assert restored.director_directives == document.director_directives
    assert reopened.begin_reference_proposal() == (restored, True)


@pytest.mark.parametrize("location", ["root", "structured", "layers"])
def test_persistence_rejects_undeclared_fields(store, location):
    value = copy.deepcopy(serialize_document(store.read()))
    target = value if location == "root" else value["structured_director"]
    if location == "layers":
        target = target["workspace_layers"]
    target["untrusted_field"] = True
    store.path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        store.read()


def test_failed_replace_leaves_authority_and_recovery_unchanged(store):
    before = store.path.read_bytes()
    with (
        patch("core.structured_director.store.os.replace", side_effect=OSError("disk")),
        pytest.raises(OSError, match="disk"),
    ):
        store.begin_reference_proposal()
    assert store.path.read_bytes() == before
    assert store.read().active_director_run is None
    assert list(store.path.parent.glob(".project.json.*.tmp")) == []


@pytest.mark.parametrize("version", [22, 23, 24, 25, 26, 27, "28", True])
def test_schema_is_exactly_v28_without_migration(store, version):
    # v28 起环境库由 Location 原地替换；旧项目没有地点/视图结构，不迁移，需新建项目。
    value = serialize_document(store.read())
    value["schema_version"] = version
    store.path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        store.read()


def test_narrator_has_separate_zh_and_en_voices():
    from core.structured_director.codec.reference import _parse_narrator, _serialize_narrator
    from core.structured_director.models import NarratorProfile, NarratorVoice

    narrator = NarratorProfile(
        "a" * 32,
        "旁白",
        NarratorVoice("低沉的中文叙述", "b" * 32, "中文文字稿"),
        NarratorVoice("British RP narrator"),
    )
    assert _parse_narrator(_serialize_narrator(narrator)) == narrator
    assert narrator.voice_reference_asset_ids == ("b" * 32,)
    with pytest.raises(ValueError):
        _parse_narrator(
            {
                "id": "a" * 32,
                "name": "旁白",
                "voice_description": "旧的单一音色",
                "voice_reference_asset_id": None,
                "voice_reference_transcript": None,
            }
        )
    assert NarratorProfile("a" * 32, "旁白", narrator.zh, None).en is None
    with pytest.raises(ValueError, match="至少包含"):
        NarratorProfile("a" * 32, "旁白", None, None)


def test_bilingual_cue_and_language_tagged_generation_roundtrip():
    from core.model_providers.recipe import RecipeParams
    from core.structured_director.codec.narration import (
        _parse_narration_cue,
        _serialize_narration_cue,
    )
    from core.structured_director.models import NarrationCue, NarrationLanguage, NarrationTrack

    cue = NarrationCue(
        "c" * 32,
        NarrationTrack(
            "中文旁白。",
            1,
            None,
            RecipeParams.from_json({"breeze_tts2.clone": {"performance_instruction": "平静"}}),
        ),
        NarrationTrack("English narration.", 2),
    )
    assert _parse_narration_cue(_serialize_narration_cue(cue)) == cue
    with pytest.raises(ValueError):
        _parse_narration_cue({**_serialize_narration_cue(cue), "text": "旧单语字段"})
    generation = ReferenceGeneration(
        id="d" * 32,
        kind=ReferenceGenerationKind.NARRATION_AUDIO,
        operation=GenerationOperation.SYNTHESIZE,
        target_id=cue.id,
        phase=ReferenceGenerationPhase.FAILED,
        progress=0.0,
        message="失败",
        prompt_text="English narration.",
        input_asset_ids=("e" * 32,),
        sample_text="参考文字稿",
        seed=2,
        plugin_id="test.tts",
        plugin_version=1,
        external_id="job",
        output_asset_id=None,
        error_code="x",
        cancellation_requested=False,
        retry_of=None,
        language=NarrationLanguage.EN,
    )
    with pytest.raises(ValueError, match="语言"):
        replace(generation, language=None)
    with pytest.raises(ValueError, match="语言"):
        replace(generation, kind=ReferenceGenerationKind.KEYFRAME_IMAGE)
