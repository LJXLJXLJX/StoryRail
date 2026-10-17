"""读取 API 与任务上下文共源，完整专业输入和局部作用域不退化。"""

import asyncio
import json
from dataclasses import replace

import pytest
from test_director_commands import _visual_project

from core.director_commands import DirectorCommand
from core.structured_director import StructuredDirectorHttpApi
from core.structured_director.models import LocationLibrary
from core.structured_director.production_context import _director_state_json, _script_json
from core.structured_director.reads.read_tools import execute_project_read
from core.structured_director.reads.semantic_projection import (
    build_semantic_projection,
    build_semantic_tree,
)


def test_read_api_uses_same_projection_and_explicit_details(tmp_path):
    asyncio.run(_read_api(tmp_path))


def test_story_location_resolves_one_based_human_path_without_writing(tmp_path):
    asyncio.run(_story_location(tmp_path))


async def _story_location(tmp_path):
    store, service, document, _ = await _visual_project(str(tmp_path))
    scene = document.director_script.scenes[0]
    shot = scene.shots[0]
    segment = shot.segments[0]
    before = store.path.read_bytes()
    result = execute_project_read(
        document,
        "project.locate_story",
        {"location": "场景 1－镜头 1－片段 1"},
    )
    assert result == {
        "revision": document.revision,
        "location": "场景 1－镜头 1－片段 1",
        "target_type": "segment",
        "target_id": segment.id,
        "scene": {"id": scene.id, "index": 1, "title": scene.title},
        "shot": {"id": shot.id, "index": 1, "action": shot.action},
        "segment": {"id": segment.id, "index": 1, "action": segment.action},
    }
    assert (
        execute_project_read(document, "project.locate_story", {"location": "场景 1"})["target_id"]
        == scene.id
    )
    assert (
        execute_project_read(document, "project.locate_story", {"location": "场景 1-镜头 1"})[
            "target_id"
        ]
        == shot.id
    )
    with pytest.raises(ValueError, match="location"):
        execute_project_read(document, "project.locate_story", {"location": "场景 1－片段 1"})
    with pytest.raises(ValueError, match="不存在"):
        execute_project_read(document, "project.locate_story", {"location": "场景 99"})
    assert store.path.read_bytes() == before


async def _read_api(tmp_path):
    store, service, document, _ = await _visual_project(str(tmp_path))
    scene = document.director_script.scenes[0]
    request = {"level": "scene", "scope": {"scene_ids": [scene.id]}}
    before = store.path.read_bytes()
    result = await service.execute_director_command(
        DirectorCommand(
            "project.get_projection",
            document.revision,
            "shared-read",
            request,
        )
    )
    assert result.data == build_semantic_projection(document, request)
    api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
    response = await api.handle(
        "POST",
        "/structured-director/commands",
        json.dumps(
            {
                "name": "project.get_projection",
                "expected_revision": document.revision,
                "idempotency_key": "http-projection",
                "arguments": request,
            }
        ).encode(),
    )
    assert response.status == 200
    assert response.body["data"] == result.data
    default = execute_project_read(document, "project.get_scene", {"scene_id": scene.id})
    assert default["script"]["summary"] == result.data["items"][0]["summary"]
    assert "generations" not in default and "keyframes" not in default
    assert default["projection_version"] == result.data["projection_version"]
    outline = execute_project_read(document, "project.get_outline", {})
    assert "shots" not in outline["items"][0]
    assert outline["items"][0]["driver"] == scene.driver
    for level, node in (("shot", scene.shots[0]), ("segment", scene.shots[0].segments[0])):
        target = execute_project_read(document, "project.get_target", {"target_id": node.id})
        projection = build_semantic_projection(
            document,
            {
                "level": level,
                "scope": request["scope"],
                "ids": [node.id],
            },
        )
        assert target["target"] == projection["items"][0]
    with pytest.raises(ValueError, match="scope"):
        execute_project_read(document, "project.get_projection", {"level": "scene"})
    assert store.path.read_bytes() == before


def test_large_scoped_context_omits_unrelated_prose_and_keeps_full_compiler_text(tmp_path):
    asyncio.run(_large_context(tmp_path))


async def _large_context(tmp_path):
    store, _, document, _ = await _visual_project(str(tmp_path))
    source = document.director_script.scenes[0]
    scenes = tuple(
        replace(
            source,
            id=f"{index + 1:032x}",
            title=f"场次标题{index + 1}",
            summary=f"only-scene-{index + 1}-" + "情节" * 1500,
            shots=tuple(
                replace(
                    shot,
                    id=f"{1000 + index * 10 + j:032x}",
                    action="完整动作" * 300,
                    segments=tuple(
                        replace(
                            segment,
                            id=f"{10000 + index * 100 + j * 10 + k:032x}",
                            action=f"segment-{index + 1}-" + "动作" * 1000,
                        )
                        for k, segment in enumerate(shot.segments)
                    ),
                )
                for j, shot in enumerate(source.shots)
            ),
        )
        for index in range(60)
    )
    large = replace(
        document,
        keyframe_plan=None,
        video_plan=None,
        location_library=LocationLibrary(),
        director_script=replace(document.director_script, scenes=scenes),
    )
    before = store.path.read_bytes()
    state_json = _director_state_json(large, user_message="只讨论 scene1")
    state = json.loads(state_json)
    local_all = json.loads(_director_state_json(large, user_message="scene1 的全部片段"))
    assert local_all["scope"] == {"scene_ids": [scenes[0].id]}
    assert state["scope"] == {"scene_ids": [scenes[0].id]}
    assert "only-scene-1-" in state_json and "only-scene-2-" not in state_json
    assert "segment-2-" not in state_json
    assert "summary" not in state["scenes"][1]
    assert len(state_json.encode()) < 128 * 1024
    full = json.loads(_script_json((scenes[0],), large))
    assert full["scope"] == state["scope"] and full["text_mode"] == "full"
    assert full["scenes"][0]["summary"] == scenes[0].summary
    assert full["scenes"][0]["shots"][0]["action"] == scenes[0].shots[0].action
    assert "only-scene-2-" not in json.dumps(full)
    assert "provenance" not in full["scenes"][0]  # 专业 proposal entity 仍严格。
    # 大正文页会超过128KiB；缩页后必须保留完整顺序、scope和每个节点正文。
    all_text = build_semantic_tree(large, tuple(s.id for s in scenes), full_text=True)
    assert [s["id"] for s in all_text["scenes"]] == [s.id for s in scenes]
    for actual, expected in zip(all_text["scenes"], scenes, strict=True):
        assert actual["summary"] == expected.summary
        for shot, source_shot in zip(actual["shots"], expected.shots, strict=True):
            assert shot["id"] == source_shot.id
            assert [s["action"] for s in shot["segments"]] == [
                s.action for s in source_shot.segments
            ]
    with pytest.raises(ValueError, match="scope"):
        build_semantic_tree(large, ())
    assert store.path.read_bytes() == before
