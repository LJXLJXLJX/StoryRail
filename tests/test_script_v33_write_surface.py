"""v33 脚本写入面：proposal 的 shot_indexes 物化、edit_script 操作集与 HTTP/MCP 形状。"""

from __future__ import annotations

import asyncio
import json

import pytest
from script_helpers import editable_scene_payload
from test_director_commands import (
    _script_new_segment_payload,
    _script_segment_payload,
    _script_shot_payload,
    _visual_project,
)

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_proposals import (
    EditableNarrationCueProposal,
    EditableSceneProposal,
    EditableShotProposal,
    EditableShotSegmentProposal,
    NarrationCueProposal,
    NarrationTrackProposal,
    SceneProposal,
    SegmentBoundaryProposal,
    ShotProposal,
    ShotSegmentProposal,
    StructuredDirectorScriptProposal,
)
from core.structured_director import StructuredDirectorHttpApi
from core.structured_director.script_index import shot_segments
from core.structured_director.script_mutations import (
    _materialize_script,
    _materialize_script_revision,
)

BOUNDARY = {"reason": "continuity_anchor", "continuity_instruction": "延续同一动作。"}
BOUNDARY_PROPOSAL = SegmentBoundaryProposal(**BOUNDARY)


def _shot(action: str = "动作。") -> ShotProposal:
    return ShotProposal(
        visible_character_ids=(),
        composition="中景。",
        camera_movement="固定。",
        action=action,
        audio_direction="环境声。",
        transition_in=None,
    )


def _segment(indexes, *, boundary=None, action="动作。") -> ShotSegmentProposal:
    return ShotSegmentProposal(
        shot_indexes=tuple(indexes),
        duration_estimate_seconds=3.0,
        action=action,
        dialogue_lines=(),
        boundary_from_previous=boundary,
    )


def _scene(shots, segments, *, driver="drama", cues=()) -> SceneProposal:
    return SceneProposal(
        title="站台",
        summary="等待末班车。",
        setting="傍晚站台。",
        shots=tuple(shots),
        segments=tuple(segments),
        narration_cues=tuple(cues),
        driver=driver,
    )


def _materialize(scene: SceneProposal):
    return _materialize_script(
        StructuredDirectorScriptProposal((scene,)), source_reference_revision=1
    )


def test_proposal_materializes_multi_shot_segment_and_three_segment_long_shot() -> None:
    # g0 段内切镜 s0–s1；s1 跨 g0/g1/g2 三个 Segment 的长镜头；g3 从 s2 继续切到 s3。
    scene = _scene(
        [_shot() for _ in range(4)],
        [
            _segment([0, 1]),
            _segment([1], boundary=BOUNDARY_PROPOSAL),
            _segment([1, 2], boundary=BOUNDARY_PROPOSAL),
            _segment([3], action="下一镜。"),
        ],
    )
    materialized = _materialize(scene).scenes[0]
    shots = materialized.shots
    assert [segment.shot_ids for segment in materialized.segments] == [
        (shots[0].id, shots[1].id),
        (shots[1].id,),
        (shots[1].id, shots[2].id),
        (shots[3].id,),
    ]
    assert [item.id for item in shot_segments(materialized, shots[1].id)] == [
        materialized.segments[0].id,
        materialized.segments[1].id,
        materialized.segments[2].id,
    ]
    assert materialized.segments[2].boundary_from_previous is not None


def test_narration_scene_is_empty_before_tts_and_planned_by_revision() -> None:
    cue = NarrationCueProposal(
        zh=NarrationTrackProposal("末班车到来以前，站台仍旧安静。", 42),
        en=NarrationTrackProposal("Before the last train, the platform stays quiet.", 42),
    )
    cold = _materialize(_scene([], [], driver="narration", cues=(cue,))).scenes[0]
    assert cold.shots == () and cold.segments == ()

    previous_cue = cold.narration_cues[0]
    editable = EditableSceneProposal(
        id=cold.id,
        title=cold.title,
        summary=cold.summary,
        setting=cold.setting,
        driver="narration",
        shots=(EditableShotProposal(None, (), "中景。", "固定。", "动作。", "", None),),
        segments=(EditableShotSegmentProposal(None, (0,), 3.0, "动作。", (), None),),
        narration_cues=(
            EditableNarrationCueProposal(
                previous_cue.id,
                NarrationTrackProposal(previous_cue.zh.text, previous_cue.zh.seed),
                NarrationTrackProposal(previous_cue.en.text, previous_cue.en.seed),
            ),
        ),
    )
    planned = _materialize_script_revision((editable,), (cold,))[0]
    assert len(planned.shots) == 1 and len(planned.segments) == 1
    assert planned.segments[0].shot_ids == (planned.shots[0].id,)

    with pytest.raises(ValueError, match="Narration Scene 初稿只提交旁白"):
        _materialize(_scene([_shot()], [_segment([0])], driver="narration", cues=(cue,)))


@pytest.mark.parametrize(
    ("shots", "segments", "message"),
    [
        (3, [(0,), (2,)], "Scene「站台」 的第 2 个 Segment 跳过了第 2 个 Shot"),
        (2, [(1,)], "第 1 个 Segment 必须从本 Scene 的第一个 Shot 开始"),
        (3, [(0, 1), (0, 1)], "第 2 个 Segment 重复覆盖了前面的 Shot"),
        (3, [(0, 2), (1,)], "第 1 个 Segment 必须按 Shot 顺序连续覆盖"),
    ],
)
def test_materialization_reports_scene_and_segment_for_coverage_violations(
    shots, segments, message
) -> None:
    scene = _scene([_shot() for _ in range(shots)], [_segment(item) for item in segments])
    with pytest.raises(ValueError, match=message):
        _materialize(scene)


def test_coverage_requires_boundary_flag_to_match_shared_boundary() -> None:
    missing = _scene([_shot(), _shot()], [_segment([0]), _segment([0])])
    with pytest.raises(ValueError, match="第 2 个 Segment 延续上一段镜头"):
        _materialize(missing)
    extra = _scene([_shot(), _shot()], [_segment([0]), _segment([1], boundary=BOUNDARY)])
    with pytest.raises(ValueError, match="第 2 个 Segment 不延续上一段镜头"):
        _materialize(extra)


def _execute(store, document, operations, key):
    return DirectorCommandRegistry(store).execute(
        DirectorCommand(
            "script.apply_operations",
            document.revision,
            key,
            {
                "scope": {"scene_ids": [document.director_script.scenes[0].id]},
                "operations": operations,
            },
        )
    )


def test_insert_shot_requires_and_honors_a_coverage_choice(tmp_path) -> None:
    async def run():
        store, _service, document, _route = await _visual_project(str(tmp_path))
        scene = document.director_script.scenes[0]
        first_shot, second_shot = scene.shots
        character_id = document.reference_library.characters[0].id
        first_segment = shot_segments(scene, first_shot.id)[0]
        with pytest.raises(ValueError, match="必须且只能给出"):
            _execute(
                store,
                document,
                [
                    {
                        "op": "insert_shot",
                        "scene_id": scene.id,
                        "after_shot_id": first_shot.id,
                        "shot": _script_shot_payload(character_id, "无归属。"),
                    }
                ],
                "insert-without-coverage",
            )
        inserted = _execute(
            store,
            document,
            [
                {
                    "op": "insert_shot",
                    "scene_id": scene.id,
                    "after_shot_id": second_shot.id,
                    "shot": _script_shot_payload(character_id, "独立镜头。"),
                    "new_segment": _script_new_segment_payload(
                        character_id, "独立镜头。", boundary=False
                    ),
                }
            ],
            "insert-new-shot",
        )
        inserted_scene = inserted.document.director_script.scenes[0]
        new_shot = inserted_scene.shots[-1]
        (own_segment,) = shot_segments(inserted_scene, new_shot.id)
        assert own_segment.shot_ids == (new_shot.id,)
        assert new_shot.id not in {first_shot.id, second_shot.id}
        attached = _execute(
            store,
            inserted.document,
            [
                {
                    "op": "insert_shot",
                    "scene_id": scene.id,
                    "after_shot_id": first_shot.id,
                    "shot": _script_shot_payload(character_id, "并入镜头。"),
                    "attach_to_segment_id": first_segment.id,
                }
            ],
            "insert-attach",
        )
        attached_scene = attached.document.director_script.scenes[0]
        attached_shot = attached_scene.shots[1]
        assert shot_segments(attached_scene, first_shot.id)[0].shot_ids == (
            first_shot.id,
            attached_shot.id,
        )

    asyncio.run(run())


def test_segment_crud_uses_scene_container(tmp_path) -> None:
    async def run():
        store, _service, document, _route = await _visual_project(str(tmp_path))
        scene = document.director_script.scenes[0]
        shot = scene.shots[0]
        original = shot_segments(scene, shot.id)[0]
        character_id = document.reference_library.characters[0].id
        inserted = _execute(
            store,
            document,
            [
                {
                    "op": "insert_segment",
                    "scene_id": scene.id,
                    "after_segment_id": original.id,
                    "segment": _script_segment_payload(
                        character_id,
                        "新增动作。",
                        boundary=True,
                        shot_ids=(shot.id,),
                    ),
                }
            ],
            "insert-segment",
        )
        inserted_scene = inserted.document.director_script.scenes[0]
        ordered = shot_segments(inserted_scene, shot.id)
        assert [item.id for item in ordered] == [original.id, inserted_scene.segments[1].id]
        added = ordered[1]
        moved = _execute(
            store,
            inserted.document,
            [
                {
                    "op": "move_segment",
                    "scene_id": scene.id,
                    "segment_id": original.id,
                    "after_segment_id": None,
                }
            ],
            "move-segment",
        )
        assert moved.document.director_script.scenes[0].segments[0].id == original.id
        updated = _execute(
            store,
            moved.document,
            [
                {
                    "op": "update_segment_fields",
                    "segment_id": added.id,
                    "fields": {
                        "duration_estimate_seconds": 5,
                        "action": "更新后的动作。",
                        "boundary_from_previous": BOUNDARY,
                    },
                }
            ],
            "update-segment",
        )
        updated_segment = next(
            item
            for item in updated.document.director_script.scenes[0].segments
            if item.id == added.id
        )
        assert updated_segment.duration_estimate_seconds == 5
        assert updated_segment.boundary_from_previous is not None
        deleted = _execute(
            store,
            updated.document,
            [{"op": "delete_segment", "scene_id": scene.id, "segment_id": added.id}],
            "delete-segment",
        )
        assert all(
            item.id != added.id for item in deleted.document.director_script.scenes[0].segments
        )

    asyncio.run(run())


def test_split_segment_inside_shot_and_at_shot_boundary(tmp_path) -> None:
    async def run():
        store, _service, document, _route = await _visual_project(str(tmp_path))
        scene = document.director_script.scenes[0]
        first_shot, second_shot = scene.shots
        character_id = document.reference_library.characters[0].id
        combined = _execute(
            store,
            document,
            [
                {
                    "op": "update_segment_fields",
                    "segment_id": shot_segments(scene, second_shot.id)[0].id,
                    "fields": {
                        "shot_ids": [first_shot.id, second_shot.id],
                        "boundary_from_previous": BOUNDARY,
                    },
                }
            ],
            "combine-segment",
        )
        combined_scene = combined.document.director_script.scenes[0]
        combined_segment = shot_segments(combined_scene, second_shot.id)[0]
        assert combined_segment.shot_ids == (first_shot.id, second_shot.id)

        # 拆在 Shot 内部：两段共享边界 Shot，第二段必须说明前置边界。
        inside = _execute(
            store,
            combined.document,
            [
                {
                    "op": "split_segment",
                    "segment_id": combined_segment.id,
                    "preserve_id": "first",
                    "first": _script_segment_payload(
                        character_id, "前半。", boundary=True, shot_ids=(first_shot.id,)
                    ),
                    "second": _script_segment_payload(
                        character_id,
                        "后半。",
                        boundary=True,
                        shot_ids=(first_shot.id, second_shot.id),
                    ),
                }
            ],
            "split-inside-shot",
        )
        inside_scene = inside.document.director_script.scenes[0]
        inside_index = [item.id for item in inside_scene.segments].index(combined_segment.id)
        inside_first = inside_scene.segments[inside_index]
        inside_second = inside_scene.segments[inside_index + 1]
        assert inside_first.shot_ids == (first_shot.id,)
        assert inside_second.shot_ids == (first_shot.id, second_shot.id)
        assert inside_second.boundary_from_previous is not None

        merged = _execute(
            store,
            inside.document,
            [
                {
                    "op": "merge_adjacent_segments",
                    "left_segment_id": inside_first.id,
                    "right_segment_id": inside_second.id,
                    "preserve_id": "left",
                    "merged": _script_segment_payload(
                        character_id,
                        "合并。",
                        boundary=True,
                        shot_ids=(first_shot.id, second_shot.id),
                    ),
                }
            ],
            "merge-inside",
        )
        merged_scene = merged.document.director_script.scenes[0]
        merged_segment = next(item for item in merged_scene.segments if item.id == inside_first.id)
        assert merged_segment.shot_ids == (first_shot.id, second_shot.id)

        # 拆在 Shot 边界：两段不再共享，第二段 boundary 必须为 null。
        at_boundary = _execute(
            store,
            merged.document,
            [
                {
                    "op": "split_segment",
                    "segment_id": merged_segment.id,
                    "preserve_id": "first",
                    "first": _script_segment_payload(
                        character_id, "只覆盖前一 Shot。", boundary=True, shot_ids=(first_shot.id,)
                    ),
                    "second": _script_segment_payload(
                        character_id,
                        "只覆盖后一 Shot。",
                        boundary=False,
                        shot_ids=(second_shot.id,),
                    ),
                }
            ],
            "split-at-boundary",
        )
        boundary_scene = at_boundary.document.director_script.scenes[0]
        boundary_index = [item.id for item in boundary_scene.segments].index(merged_segment.id)
        boundary_first = boundary_scene.segments[boundary_index]
        boundary_second = boundary_scene.segments[boundary_index + 1]
        assert boundary_first.shot_ids == (first_shot.id,)
        assert boundary_second.shot_ids == (second_shot.id,)
        assert boundary_second.boundary_from_previous is None

    asyncio.run(run())


def test_edit_script_rejects_invalid_coverage_and_empty_segments(tmp_path) -> None:
    async def run():
        store, _service, document, _route = await _visual_project(str(tmp_path))
        scene = document.director_script.scenes[0]
        first_shot, second_shot = scene.shots
        first_segment = shot_segments(scene, first_shot.id)[0]
        second_segment = shot_segments(scene, second_shot.id)[0]
        before = store.path.read_bytes()
        with pytest.raises(
            ValueError, match="Scene「连续动作」 的 Segment 没有覆盖到最后一个 Shot"
        ):
            _execute(
                store,
                document,
                [
                    {
                        "op": "update_segment_fields",
                        "segment_id": second_segment.id,
                        "fields": {
                            "shot_ids": [first_shot.id],
                            "boundary_from_previous": BOUNDARY,
                        },
                    }
                ],
                "coverage-skip",
            )
        with pytest.raises(ValueError, match="必须填写 boundary_from_previous"):
            _execute(
                store,
                document,
                [
                    {
                        "op": "update_segment_fields",
                        "segment_id": second_segment.id,
                        "fields": {"shot_ids": [first_shot.id]},
                    },
                    {
                        "op": "update_segment_fields",
                        "segment_id": first_segment.id,
                        "fields": {"shot_ids": [first_shot.id]},
                    },
                ],
                "coverage-boundary",
            )
        with pytest.raises(ValueError, match="失去全部 Shot"):
            _execute(
                store,
                document,
                [{"op": "delete_shot", "scene_id": scene.id, "shot_id": second_shot.id}],
                "delete-only-shot",
            )
        assert store.path.read_bytes() == before

        # 同一次修改里先移除只覆盖该 Shot 的 Segment，再删除 Shot，则整批成立。
        removed = _execute(
            store,
            document,
            [
                {"op": "delete_segment", "scene_id": scene.id, "segment_id": second_segment.id},
                {"op": "delete_shot", "scene_id": scene.id, "shot_id": second_shot.id},
            ],
            "delete-segment-and-shot",
        )
        removed_scene = removed.document.director_script.scenes[0]
        assert [shot.id for shot in removed_scene.shots] == [first_shot.id]
        assert removed_scene.segments[0].shot_ids == (first_shot.id,)

    asyncio.run(run())


def test_http_manual_edit_submits_v33_coverage_shape(tmp_path) -> None:
    async def run():
        store, service, document, _route = await _visual_project(str(tmp_path))
        scene = document.director_script.scenes[0]
        first_shot, second_shot = scene.shots
        first_segment = shot_segments(scene, first_shot.id)[0]
        second_segment = shot_segments(scene, second_shot.id)[0]
        api = StructuredDirectorHttpApi(service, resource_path="/structured-director")
        snapshot = await api.handle("GET", "/structured-director")
        payload = editable_scene_payload(snapshot.body["director_script"]["scenes"][0])
        position = {shot["id"]: index for index, shot in enumerate(payload["shots"])}
        payload["segments"] = [
            {
                **payload["segments"][0],
                "shot_indexes": [position[first_shot.id], position[second_shot.id]],
            },
            {
                **payload["segments"][1],
                "shot_indexes": [position[second_shot.id]],
                "boundary_from_previous": BOUNDARY,
            },
        ]
        saved = await api.handle(
            "PUT",
            "/structured-director/director-script",
            json.dumps(
                {"expected_revision": snapshot.body["revision"], "scenes": [payload]}
            ).encode(),
        )
        assert saved.status == 200, saved.body
        saved_scene = saved.body["director_script"]["scenes"][0]
        assert [segment["shot_ids"] for segment in saved_scene["segments"]] == [
            [first_shot.id, second_shot.id],
            [second_shot.id],
        ]
        assert saved_scene["segments"][1]["boundary_from_previous"] == BOUNDARY
        # 原两个 Segment 仍存在，只是改覆盖；Shot 本身仍没有 segments 字段。
        assert saved_scene["segments"][0]["id"] == first_segment.id
        assert saved_scene["segments"][1]["id"] == second_segment.id
        assert all("segments" not in shot for shot in saved_scene["shots"])

    asyncio.run(run())
