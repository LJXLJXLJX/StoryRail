"""共源投影只读契约：混合叙事、边界错误、分页与实际已选音频。"""

import asyncio
import json
from dataclasses import replace

import pytest
from test_director_commands import _visual_project
from test_scene_driver_invariants import MixedProposer, narration_project, select_audio

from core.structured_director.models import (
    LocationLibrary,
    SegmentBoundary,
    SegmentBoundaryReason,
)
from core.structured_director.reads.read_tools import execute_project_read
from core.structured_director.reads.semantic_projection import build_semantic_projection as build
from core.structured_director.reads.semantic_projection import build_semantic_tree
from core.structured_director.script_index import shot_segments
from core.structured_director.script_mutations import dialogue_plan_for_script


def test_mixed_projection_and_selected_real_audio(tmp_path):
    asyncio.run(_mixed(tmp_path))


async def _mixed(tmp_path):
    store, service, _, document = await narration_project(tmp_path, MixedProposer())
    before = store.path.read_bytes()
    request = {"level": "outline", "scope": {"project_id": document.project_id}, "limit": 1}
    first = build(document, request)
    assert first["items"][0]["driver"] == "narration"
    assert first["items"][0]["narration"][0]["zh"]["duration_seconds"] is None
    assert first["items"][0]["narration"][0]["en"]["duration_seconds"] is None
    second = build(document, {**request, "cursor": first["next_cursor"]})
    assert second["items"][0]["driver"] == "drama"
    assert second["next_cursor"] is None
    assert store.path.read_bytes() == before
    assert first == build(document, request)  # Human/Agent 无调用方特例。
    narration, drama = document.director_script.scenes
    scoped = {"scope": {"scene_ids": [drama.id]}}
    shot = build(document, {**scoped, "level": "shot"})["items"][0]
    assert shot["parent"] == {"kind": "scene", "id": drama.id}
    assert shot["action"] == drama.shots[0].action
    assert shot["segment_ids"] == [
        segment.id for segment in drama.segments if drama.shots[0].id in segment.shot_ids
    ]
    segment = build(document, {**scoped, "level": "segment"})["items"][0]
    assert segment["parent"] == {"kind": "scene", "id": drama.id}
    assert segment["shot_ids"] == list(drama.segments[0].shot_ids)
    assert segment["dialogue_lines"] == [
        {
            "character_id": line.character_id,
            "speaker_label": line.speaker_label,
            "text": line.text,
            "delivery": line.delivery,
        }
        for line in drama.segments[0].dialogue_lines
    ]
    assert "selection" not in segment and "dependencies" not in segment
    assert "director_script.scenes" in segment["provenance"]["field"]
    encoded = json.dumps(first)
    for hidden in ('"seed"', '"generations"', '"runtime"', '"relative_path"'):
        assert hidden not in encoded
    with pytest.raises(ValueError, match="越出"):
        build(
            document,
            {"level": "shot", "scope": {"scene_ids": [narration.id]}, "ids": [drama.shots[0].id]},
        )
    selected = await select_audio(service, document)
    result = build(selected, {"level": "scene", "scope": {"scene_ids": [narration.id]}})
    cue = result["items"][0]["narration"][0]
    selected_cue = selected.director_script.scenes[0].narration_cues[0]
    for language, track in selected_cue.tracks:
        assert cue[language.value]["duration_seconds"] == 16
        assert cue[language.value]["selected_audio_asset_id"] == track.selected_audio_asset_id
        assert cue[language.value]["duration_source"] == "selected_audio_asset"
    with pytest.raises(ValueError, match="revision"):
        build(selected, {**request, "cursor": first["next_cursor"]})
    with pytest.raises(ValueError, match="revision"):
        build(document, {**request, "limit": 2, "cursor": first["next_cursor"]})
    with pytest.raises(ValueError, match="范围"):
        build(document, {**request, "cursor": first["next_cursor"].split(":")[0] + ":99"})


def test_projection_bounds_text_extensions_and_invalid_scope(tmp_path):
    asyncio.run(_bounds(tmp_path))


async def _bounds(tmp_path):
    store, _, document, _ = await _visual_project(str(tmp_path))
    scene = document.director_script.scenes[0]
    scope = {"scene_ids": [scene.id]}
    before = store.path.read_bytes()
    result = build(
        document, {"level": "segment", "scope": scope, "extensions": ["selection", "dependencies"]}
    )
    item = result["items"][0]
    binding = document.keyframe_plan.segments[0]
    assert item["selection"]["keyframes"][0]["keyframe_id"] == binding.start_keyframe_id
    assert item["dependencies"]["informational_only"] is True
    for request in (
        {"level": "scene"},
        {"level": "outline", "scope": {"project_id": "b" * 32}},
        {"level": "scene", "scope": {"scene_ids": []}},
        {"level": "scene", "scope": {"scene_ids": [scene.id, scene.id]}},
        {"level": "scene", "scope": {"scene_ids": ["f" * 32]}},
        {"level": "shot", "scope": scope, "ids": ["f" * 32]},
        {"level": "shot", "scope": scope, "ids": [scene.shots[0].id] * 2},
        {"level": "scene", "scope": scope, "limit": True},
        {"level": "scene", "scope": scope, "limit": 101},
        {"level": "scene", "scope": scope, "cursor": "garbage"},
        {"level": "scene", "scope": scope, "extensions": ["text", "text"]},
        {"level": "scene", "scope": scope, "extensions": ["runtime"]},
        {"level": "scene", "scope": scope, "extra": True},
    ):
        with pytest.raises(ValueError):
            build(document, request)
    long_scene = replace(scene, summary="文" * 4000)
    synthetic = replace(
        document, director_script=replace(document.director_script, scenes=(long_scene,))
    )
    preview = build(synthetic, {"level": "scene", "scope": scope})
    full = build(synthetic, {"level": "scene", "scope": scope, "extensions": ["text"]})
    assert len(preview["items"][0]["summary"]) == 240
    assert len(full["items"][0]["summary"]) == 4000

    # 单页展开正文超出 128 KiB 时明确拒绝，可缩页。
    def numbered(index):
        shot_ids = {
            shot.id: f"{1000 + index * 10 + j:032x}" for j, shot in enumerate(long_scene.shots)
        }
        return replace(
            long_scene,
            id=f"{index + 1:032x}",
            shots=tuple(replace(shot, id=shot_ids[shot.id]) for shot in long_scene.shots),
            segments=tuple(
                replace(
                    segment,
                    id=f"{10000 + index * 100 + j * 10 + k:032x}",
                    shot_ids=tuple(shot_ids[item] for item in segment.shot_ids),
                    dialogue_lines=tuple(
                        replace(
                            line,
                            id=f"{200000 + index * 1000 + j * 100 + k * 10 + n:032x}",
                        )
                        for n, line in enumerate(segment.dialogue_lines)
                    ),
                )
                for j, shot in enumerate(long_scene.shots)
                for k, segment in enumerate(shot_segments(long_scene, shot.id))
            ),
        )

    many = tuple(numbered(index) for index in range(40))
    script = replace(document.director_script, scenes=many)
    large = replace(
        document,
        keyframe_plan=None,
        video_plan=None,
        location_library=LocationLibrary(),
        director_script=script,
        dialogue_plan=dialogue_plan_for_script(script),
    )
    request = {
        "level": "outline",
        "scope": {"project_id": large.project_id},
        "extensions": ["text"],
        "limit": 40,
    }
    with pytest.raises(ValueError, match="128 KiB"):
        build(large, request)
    assert build(large, {**request, "limit": 1})["next_cursor"]
    assert store.path.read_bytes() == before


def test_segment_parent_scope_is_strict_and_cursor_bound(tmp_path):
    asyncio.run(_parent_scope(tmp_path))


async def _parent_scope(tmp_path):
    _, _, document, _ = await _visual_project(str(tmp_path))
    scene = document.director_script.scenes[0]
    source = scene.shots[0]
    source_segments = shot_segments(scene, source.id)
    shots = tuple(replace(source, id=f"{i + 100:032x}") for i in range(4))
    segments = tuple(
        replace(
            source_segments[0],
            id=f"{1000 + i * 10 + j:032x}",
            shot_ids=(shot.id,),
            dialogue_lines=tuple(
                replace(line, id=f"{300000 + i * 100 + j * 10 + n:032x}")
                for n, line in enumerate(source_segments[0].dialogue_lines)
            ),
            boundary_from_previous=None
            if j == 0
            else SegmentBoundary(SegmentBoundaryReason.CONTINUITY_ANCHOR, "从上一边界继续。"),
        )
        for i, shot in enumerate(shots)
        for j in range(3)
    )
    scene = replace(scene, shots=shots, segments=segments)
    other = replace(
        scene,
        id="e" * 32,
        shots=(replace(source, id="f" * 32),),
        segments=tuple(
            replace(
                segment,
                shot_ids=("f" * 32,),
                dialogue_lines=tuple(
                    replace(line, id=f"{400000 + i * 10 + n:032x}")
                    for n, line in enumerate(segment.dialogue_lines)
                ),
            )
            for i, segment in enumerate(source_segments)
        ),
    )
    script = replace(document.director_script, scenes=(scene, other))
    document = replace(
        document,
        keyframe_plan=None,
        video_plan=None,
        location_library=LocationLibrary(),
        director_script=script,
        dialogue_plan=dialogue_plan_for_script(script),
    )
    request = {
        "level": "segment",
        "scope": {"scene_ids": [scene.id]},
        "parent_id": scene.id,
        "limit": 1,
    }
    first = build(document, request)
    assert first["total"] == 12 and first["parent_id"] == scene.id
    assert first["items"][0]["id"] == segments[0].id
    second = build(document, {**request, "cursor": first["next_cursor"]})
    assert second["items"][0]["id"] == segments[1].id
    for patch in (
        {"parent_id": shots[0].id},
        {"parent_id": other.id},
        {"parent_id": "0" * 32},
        {"parent_id": None},
        {"level": "scene"},
        {"ids": [other.segments[0].id]},
    ):
        with pytest.raises(ValueError):
            build(document, {**request, **patch})
    with pytest.raises(ValueError, match="revision"):
        build(
            replace(document, revision=document.revision + 1),
            {**request, "cursor": first["next_cursor"]},
        )
    # 同一合成快照下测量实际 JSON，不推断模型 token 或时延。
    outline = build(document, {"level": "outline", "scope": {"project_id": document.project_id}})
    scene_shots = build(document, {"level": "shot", "scope": request["scope"]})
    scene_segments = build(document, {"level": "segment", "scope": request["scope"]})
    # Shot 的 Segment 经 shot 层 segment_ids 精确读取。
    shot_page = build(
        document,
        {
            "level": "segment",
            "scope": request["scope"],
            "ids": scene_shots["items"][0]["segment_ids"],
        },
    )
    shot_detail = build(
        document,
        {"level": "shot", "scope": request["scope"], "ids": [shots[0].id], "extensions": ["text"]},
    )
    segment_detail = build(
        document,
        {
            "level": "segment",
            "scope": request["scope"],
            "ids": [segments[0].id],
            "extensions": ["text"],
        },
    )

    def measurement(pages):
        return {
            "requests": len(pages),
            "nodes": sum(len(p["items"]) for p in pages),
            "json_bytes": sum(
                len(json.dumps(p, ensure_ascii=False, separators=(",", ":")).encode())
                for p in pages
            ),
        }

    report = {
        "fixture": "2 Scenes; first Scene 4 Shots x 3 Segments; same snapshot for before/after",
        "excludes": "App initial snapshot and unchanged polling; no token/time claim",
        "web_additional_reads": {
            "outline": {"before": measurement([outline]), "after": measurement([])},
            "shot": {
                "before": measurement([outline, shot_detail, scene_shots, scene_segments]),
                "after": measurement([]),
            },
            "segment": {
                "before": measurement([outline, segment_detail, scene_shots, scene_segments]),
                "after": measurement([]),
            },
        },
        "agent_shot_children": {
            "before": measurement([scene_segments]),
            "after": measurement([shot_page]),
        },
    }
    assert report["agent_shot_children"]["before"]["nodes"] == 12
    assert report["agent_shot_children"]["after"]["nodes"] == 3
    print("PROJECTION_BENCHMARK=" + json.dumps(report, ensure_ascii=False))


def test_multi_shot_segment_and_long_shot_projection(tmp_path):
    asyncio.run(_multi_shot(tmp_path))


async def _multi_shot(tmp_path):
    _, _, document, _ = await _visual_project(str(tmp_path))
    scene = document.director_script.scenes[0]
    template = scene.segments[0]
    shots = tuple(replace(scene.shots[0], id=f"{i + 300:032x}") for i in range(3))
    boundary = SegmentBoundary(SegmentBoundaryReason.CONTINUITY_ANCHOR, "延续上一段。")
    # g0 段内切镜 s0–s1；s2 长镜头跨 g1、g2。
    segments = (
        replace(
            template,
            id=f"{400:032x}",
            shot_ids=(shots[0].id, shots[1].id),
            dialogue_lines=tuple(
                replace(line, id=f"{500000 + n:032x}")
                for n, line in enumerate(template.dialogue_lines)
            ),
        ),
        replace(
            template,
            id=f"{401:032x}",
            shot_ids=(shots[2].id,),
            boundary_from_previous=None,
            dialogue_lines=tuple(
                replace(line, id=f"{500100 + n:032x}")
                for n, line in enumerate(template.dialogue_lines)
            ),
        ),
        replace(
            template,
            id=f"{402:032x}",
            shot_ids=(shots[2].id,),
            boundary_from_previous=boundary,
            dialogue_lines=tuple(
                replace(line, id=f"{500200 + n:032x}")
                for n, line in enumerate(template.dialogue_lines)
            ),
        ),
    )
    scene = replace(scene, shots=shots, segments=segments)
    script = replace(document.director_script, scenes=(scene,))
    document = replace(
        document,
        keyframe_plan=None,
        video_plan=None,
        location_library=LocationLibrary(),
        director_script=script,
        dialogue_plan=dialogue_plan_for_script(script),
    )
    scope = {"scene_ids": [scene.id]}
    shot_items = build(document, {"level": "shot", "scope": scope})["items"]
    assert [item["segment_ids"] for item in shot_items] == [
        [segments[0].id],
        [segments[0].id],
        [segments[1].id, segments[2].id],
    ]
    segment_items = build(document, {"level": "segment", "scope": scope})["items"]
    assert [item["shot_ids"] for item in segment_items] == [list(s.shot_ids) for s in segments]
    assert {item["parent"]["id"] for item in segment_items} == {scene.id}
    tree = build_semantic_tree(document, (scene.id,))
    assert [item["id"] for item in tree["scenes"][0]["segments"]] == [s.id for s in segments]
    located = execute_project_read(document, "project.locate_story", {"location": "场景 1－片段 1"})
    assert located["segment"]["shot_ids"] == [shots[0].id, shots[1].id]
