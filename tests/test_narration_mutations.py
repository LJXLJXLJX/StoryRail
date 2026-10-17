"""旁白域 mutations characterization（P2-C2）。

补齐 test_structured_director_narration.py 未覆盖的"触发即抛"负例：
6 个旁白方法的守卫错误消息逐字锁定（re.escape）。正例与失效级联由既有
narration/driver-invariants/oracle 测试锁定。
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from core.structured_director.models import (
    Asset,
    DirectorAuthorization,
    DirectorRun,
    DirectorRunCursor,
    DirectorRunKind,
    DirectorRunStatus,
    DirectorScript,
    GenerationOperation,
    NarrationCue,
    NarrationLanguage,
    NarrationTrack,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
    Scene,
    SegmentBoundary,
    SegmentBoundaryReason,
    Shot,
    ShotSegment,
    StructuredDirectorDocument,
    StructuredDirectorStatus,
    WorkspaceLayers,
)
from core.structured_director.mutations import narration as narration_mutations_module
from core.structured_director.narration_timing import conform_production_scenes
from core.structured_director.schema import PROJECT_SCHEMA_VERSION

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
ID_D = "d" * 32
SHA = "f" * 64

_narration = narration_mutations_module


def _voice_asset() -> Asset:
    return Asset(
        "1" * 32, "audio/wav", 8, "1" * 32 + "f" * 32, "assets/audio/voice-references/v.wav", 1.0
    )


def _wav_asset(asset_id: str = ID_D, duration: float = 4.0) -> Asset:
    return Asset(
        asset_id, "audio/wav", 8, asset_id + "f" * 32, "assets/audio/narration/n.wav", duration
    )


def _cue(
    cue_id: str = ID_C, selected: str | None = None, selected_en: str | None = None
) -> NarrationCue:
    return NarrationCue(
        cue_id,
        NarrationTrack("旁白文本", 1, selected),
        NarrationTrack("Narration text.", 1, selected_en),
    )


def _scene(cue: NarrationCue, scene_id: str = ID_B) -> Scene:
    return Scene(scene_id, "场景", "摘要", "环境", (), (), (cue,), "narration", None)


def _library():
    from core.structured_director.models import NarratorProfile, NarratorVoice, ReferenceLibrary

    return ReferenceLibrary(
        (), NarratorProfile("e" * 32, "旁白", NarratorVoice("描述"), NarratorVoice("描述"))
    )


def _document(
    *,
    status: StructuredDirectorStatus = StructuredDirectorStatus.REVIEWING_NARRATION,
    cue: NarrationCue | None = None,
    assets: tuple[Asset, ...] = (),
    generations: tuple[ReferenceGeneration, ...] = (),
) -> StructuredDirectorDocument:
    layers = WorkspaceLayers(narration_unlocked=True)
    keep_script = status not in {
        StructuredDirectorStatus.AWAITING_PROPOSAL,
        StructuredDirectorStatus.REVIEWING,
    }
    scenes = (_scene(cue or _cue()),) if keep_script else ()
    script = DirectorScript(1, 1, None, None, scenes) if scenes else None
    library = _library()
    return StructuredDirectorDocument(
        schema_version=PROJECT_SCHEMA_VERSION,
        project_id=ID_A,
        revision=3,
        title="旁白校验",
        aspect_ratio=__import__(
            "core.project_settings", fromlist=["ProjectAspectRatio"]
        ).ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 方案",
        status=status,
        workspace_layers=layers,
        reference_library=library,
        assets=assets,
        generations=generations,
        director_script=script,
        narration_languages=tuple(NarrationLanguage),
    )


def _narration_generation(
    *,
    prompt_text: str = "旁白文本",
    succeeded: bool = True,
    dismissed: bool = False,
    language: NarrationLanguage = NarrationLanguage.ZH,
    generation_id: str = ID_D,
    output: str = ID_D,
) -> ReferenceGeneration:
    return ReferenceGeneration(
        id=generation_id,
        kind=ReferenceGenerationKind.NARRATION_AUDIO,
        operation=GenerationOperation.SYNTHESIZE,
        target_id=ID_C,
        phase=ReferenceGenerationPhase.SUCCEEDED if succeeded else ReferenceGenerationPhase.RUNNING,
        progress=1.0 if succeeded else 0.5,
        message="",
        prompt_text=prompt_text,
        input_asset_ids=("1" * 32,),
        sample_text="完整文字稿",
        seed=1,
        plugin_id="test.voice",
        plugin_version=1,
        external_id="e",
        output_asset_id=output if succeeded else None,
        error_code=None,
        cancellation_requested=False,
        retry_of=None,
        duration_seconds=None,
        dismissed=dismissed,
        language=language,
    )


def _expect(fn, expected: str, **kwargs):
    with pytest.raises(ValueError, match=re.escape(expected)):
        fn(**kwargs)


def test_save_narration_cue_guards():
    document = _document()
    _expect(
        lambda **kw: _narration.save_narration_cue(document, **kw),
        "旁白 Cue 不存在。",
        scene_id=ID_B,
        cue=_cue("e" * 32),
    )
    _expect(
        lambda **kw: _narration.save_narration_cue(document, **kw),
        "Scene 不存在。",
        scene_id="0" * 32,
        cue=_cue(),
    )
    blocked = _document(status=StructuredDirectorStatus.REVIEWING)
    _expect(
        lambda **kw: _narration.save_narration_cue(blocked, **kw),
        "当前不能修改旁白。",
        scene_id=ID_B,
        cue=_cue(),
    )


def test_update_and_clear_scope_guards():
    document = _document()
    other_scene = _scene(_cue("e" * 32), scene_id="2" * 32)
    document = replace(
        document,
        director_script=replace(
            document.director_script,
            scenes=(*document.director_script.scenes, other_scene),
        ),
    )
    update = __import__(
        "core.director_commands", fromlist=["NarrationCueUpdate"]
    ).NarrationCueUpdate((ID_B,), ID_C, {}, {"zh": {"text": "新文本"}})
    _expect(
        lambda **kw: _narration.update_narration_cue(document, **kw),
        "旁白 Cue 不存在或不唯一。",
        update=__import__(
            "core.director_commands", fromlist=["NarrationCueUpdate"]
        ).NarrationCueUpdate((ID_B,), "3" * 32, {}, {"zh": {"text": "x"}}),
        command_id="cmd",
    )
    _expect(
        lambda **kw: _narration.update_narration_cue(document, **kw),
        "旁白 update 超出已授权 Scene scope。",
        update=__import__(
            "core.director_commands", fromlist=["NarrationCueUpdate"]
        ).NarrationCueUpdate(("2" * 32,), ID_C, {}, {"zh": {"text": "x"}}),
        command_id="cmd",
    )
    clear = __import__(
        "core.director_commands", fromlist=["NarrationSelectionClear"]
    ).NarrationSelectionClear((ID_B,), ID_C, "zh")
    _expect(
        lambda **kw: _narration.clear_narration_selection(document, **kw),
        "旁白 clear 超出已授权 Scene scope。",
        clear=__import__(
            "core.director_commands", fromlist=["NarrationSelectionClear"]
        ).NarrationSelectionClear(("2" * 32,), ID_C, "zh"),
        command_id="cmd",
    )
    # noop 路径：无选择时返回 write=False 且不抛错。
    outcome = _narration.clear_narration_selection(
        document,
        clear,
        "cmd",
    )
    assert outcome.write is False and outcome.receipt.status == "noop"
    assert update.cue_id == ID_C


def test_select_narration_audio_guards():
    document = _document(
        cue=_cue(selected=ID_D),
        assets=(_voice_asset(), _wav_asset()),
        generations=(_narration_generation(),),
    )
    _expect(
        lambda **kw: _narration.select_narration_audio(document, **kw),
        "旁白候选不存在或尚未完成。",
        cue_id=ID_C,
        generation_id="e" * 32,
    )
    running = _document(
        cue=_cue(),
        assets=(_voice_asset(),),
        generations=(_narration_generation(succeeded=False),),
    )
    _expect(
        lambda **kw: _narration.select_narration_audio(running, **kw),
        "旁白候选不存在或尚未完成。",
        cue_id=ID_C,
        generation_id=ID_D,
    )
    stale = _document(
        cue=_cue(selected=ID_D),
        assets=(_voice_asset(), _wav_asset()),
        generations=(_narration_generation(prompt_text="旧文本"),),
    )
    _expect(
        lambda **kw: _narration.select_narration_audio(stale, **kw),
        "该候选对应的是旧版旁白正文，不能用于当前 Cue。",
        cue_id=ID_C,
        generation_id=ID_D,
    )
    locked = _document(status=StructuredDirectorStatus.AWAITING_PROPOSAL)
    _expect(
        lambda **kw: _narration.select_narration_audio(locked, **kw),
        "当前不能选择旁白音频。",
        cue_id=ID_C,
        generation_id=ID_D,
    )


def test_conform_production_scenes_guards():
    unselected = (_scene(_cue(selected=None)),)
    with pytest.raises(ValueError, match="请先为每条旁白选择审核通过的所选语言音频。"):
        conform_production_scenes(unselected, {}, narrator_ready=True)
    with pytest.raises(ValueError, match="尚未建立旁白音色"):
        conform_production_scenes(unselected, {}, narrator_ready=False)
    selected = (_scene(_cue(selected=ID_D, selected_en=ID_D)),)
    with pytest.raises(ValueError, match="规划 Shot / Segment"):
        conform_production_scenes(selected, {ID_D: _wav_asset()}, narrator_ready=True)


def test_conform_production_scenes_is_idempotent_for_calibrated_timing():
    shot_id = "9" * 32
    shot = Shot(
        shot_id,
        (),
        "全景",
        "固定",
        "动作",
        "风声",
        None,
    )
    segments = (
        ShotSegment("7" * 32, (shot_id,), 1.1, "前半", (), None),
        ShotSegment(
            "8" * 32,
            (shot_id,),
            2.3,
            "后半",
            (),
            SegmentBoundary(SegmentBoundaryReason.CONTINUITY_ANCHOR, "动作连续。"),
        ),
    )
    cue = _cue(selected=ID_D, selected_en=ID_C)
    scenes = (Scene(ID_B, "场景", "摘要", "环境", (shot,), segments, (cue,), "narration", None),)
    assets = {ID_D: _wav_asset(ID_D, 4.7), ID_C: _wav_asset(ID_C, 3.1)}
    first = conform_production_scenes(scenes, assets, narrator_ready=True)
    durations = [s.duration_estimate_seconds for s in first[0].segments]
    assert sum(durations) == pytest.approx(4.7)
    # 每次脚本写入都会重新校准；已对齐的时长必须逐位保持，不能因浮点重算让视频选择失效。
    assert conform_production_scenes(first, assets, narrator_ready=True) == first


def test_begin_narration_edit_guards():
    document = _document()
    _expect(
        lambda **kw: _narration.begin_narration_edit(document, **kw),
        "当前不能请求旁白 Agent。",
        message=None,
    )
    other_run = _document()
    run = DirectorRun(
        id="e" * 32,
        kind=DirectorRunKind.SCRIPT_EDIT,
        goal="其他任务",
        status=DirectorRunStatus.RUNNING,
        waiting_reason=None,
        authorization=DirectorAuthorization((), (), "disabled", False),
        cursor=DirectorRunCursor(0, (), ()),
        completed_command_ids=(),
        command_receipts=(),
        last_project_revision=3,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )
    busy = replace(
        other_run,
        director_runs=(run,),
        pending_script_edit=__import__(
            "core.structured_director.models", fromlist=["PendingScriptEdit"]
        ).PendingScriptEdit(1, "请求"),
    )
    _expect(
        lambda **kw: _narration.begin_narration_edit(busy, **kw),
        "另一个 Director Agent 任务正在执行。",
        message="调整旁白",
    )


def test_apply_narration_review_proposal_guards():
    document = _document()
    _expect(
        lambda **kw: _narration.apply_narration_review_proposal(document, **kw),
        "当前没有等待保存的旁白 Agent proposal。",
        proposal=__import__(
            "core.director_proposals", fromlist=["NarrationReviewProposal"]
        ).NarrationReviewProposal("总结", ()),
    )


def test_bilingual_selection_and_edits_are_per_language():
    """英文候选只落到英文轨道；改一种语言的正文只清除该语言的选择。"""
    from core.director_commands import NarrationCueUpdate, NarrationSelectionClear

    en_asset = _wav_asset("9" * 32, 5.5)
    document = _document(
        cue=_cue(selected=ID_D),
        assets=(_voice_asset(), _wav_asset(), en_asset),
        generations=(
            _narration_generation(),
            _narration_generation(
                prompt_text="Narration text.",
                language=NarrationLanguage.EN,
                generation_id="8" * 32,
                output=en_asset.id,
            ),
        ),
    )
    selected = _narration.select_narration_audio(document, cue_id=ID_C, generation_id="8" * 32)
    cue = selected.director_script.scenes[0].narration_cues[0]
    assert (cue.zh.selected_audio_asset_id, cue.en.selected_audio_asset_id) == (ID_D, en_asset.id)
    assert cue.fully_selected

    edited = _narration.update_narration_cue(
        selected,
        NarrationCueUpdate((ID_B,), ID_C, {}, {"en": {"text": "Different English."}}),
        "cmd",
    ).document
    cue = edited.director_script.scenes[0].narration_cues[0]
    assert cue.zh.selected_audio_asset_id == ID_D
    assert cue.en.selected_audio_asset_id is None

    cleared = _narration.clear_narration_selection(
        selected, NarrationSelectionClear((ID_B,), ID_C, "zh"), "cmd"
    )
    cue = cleared.document.director_script.scenes[0].narration_cues[0]
    assert cue.zh.selected_audio_asset_id is None
    assert cue.en.selected_audio_asset_id == en_asset.id
    assert cleared.receipt.invalidated == (f"narration_selection:{ID_C}:zh",)


def test_timing_uses_the_longer_language():
    from core.structured_director.narration_timing import (
        narration_timing_language,
        narration_timing_seconds,
    )

    cue = _cue(selected=ID_D, selected_en="9" * 32)
    assets = {ID_D: _wav_asset(ID_D, 4.0), "9" * 32: _wav_asset("9" * 32, 5.5)}
    assert narration_timing_seconds(cue, assets) == 5.5
    assert narration_timing_language(cue, assets) is NarrationLanguage.EN
    assets["9" * 32] = _wav_asset("9" * 32, 3.0)
    assert narration_timing_seconds(cue, assets) == 4.0
    assert narration_timing_language(cue, assets) is NarrationLanguage.ZH
    with pytest.raises(ValueError, match="英文音频"):
        narration_timing_seconds(_cue(selected=ID_D), assets)
