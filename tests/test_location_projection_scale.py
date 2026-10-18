"""大地点库的只读投影规模与权限等价验证；不读取真实作品。"""

from dataclasses import replace
from statistics import median
from time import perf_counter

from test_location_generation import KIND, Rig

from core.structured_director.models import (
    KeyframeEnvironmentMode,
    LocationFixture,
    LocationLibrary,
    ReferenceGenerationPhase,
)
from core.structured_director.reads.location_view import location_library_projection


def scaled_project(tmp_path):
    rig = Rig(tmp_path)
    ids = rig.build()
    first = rig.master_ready(ids["room"])
    rig.generate_master(ids["room"])
    rig.finish(rig.last(KIND.LOCATION_MASTER_IMAGE, ids["room"]).id)
    document = rig.document
    candidate = document.generations[-1]
    second = candidate.output_asset_id
    base = document.location_library.locations[0]

    def uid(n):
        return f"{n:032x}"

    locations = []
    for n in range(10):
        fixtures = tuple(
            LocationFixture(uid(10000 + n * 100 + i), f"陈设 {i}", "固定陈设", i * 40)
            for i in range(8)
        )
        states = (replace(base.states[0], id=uid(20000 + n)),)
        views = tuple(
            replace(
                base.views[0],
                id=uid(30000 + n * 10 + i),
                name=f"视图 {n}-{i}",
                azimuth_deg=i * 60,
                state_id=states[0].id if i == 4 else None,
                reference_view_ids=(uid(30000 + n * 10),) if i == 1 else (),
                selected_asset_id=first if i < 4 else None,
            )
            for i in range(6)
        )
        locations.append(
            replace(
                base,
                id=uid(40000 + n),
                fixtures=fixtures,
                states=states,
                views=views,
                master=replace(base.master, selected_asset_id=first),
            )
        )
    scene = document.director_script.scenes[0]
    frame = document.keyframe_plan.keyframes[0]
    binding = document.keyframe_plan.segments[0]
    video = document.video_plan.segments[0]
    scenes, frames, bindings, videos = [], [], [], []
    for n in range(10):
        shots, segments = [], []
        for i in range(10):
            segment_id = uid(50000 + n * 10 + i)
            start, end = uid(60000 + n * 20 + i * 2), uid(60001 + n * 20 + i * 2)
            view_id = locations[n].views[i % 3].id
            shots.append(replace(scene.shots[0], id=uid(70000 + n * 10 + i), view_id=view_id))
            segments.append(
                replace(
                    scene.segments[0],
                    id=segment_id,
                    shot_ids=(uid(70000 + n * 10 + i),),
                    dialogue_lines=(),
                )
            )
            frames.extend(
                (
                    replace(
                        frame,
                        id=start,
                        owner_segment_id=segment_id,
                        environment_mode=KeyframeEnvironmentMode.EDIT,
                        environment_view_id=view_id,
                        environment_none_reason=None,
                        predecessor_keyframe_id=None,
                    ),
                    replace(
                        frame, id=end, owner_segment_id=segment_id, predecessor_keyframe_id=start
                    ),
                )
            )
            bindings.append(
                replace(
                    binding,
                    segment_id=segment_id,
                    start_keyframe_id=start,
                    end_keyframe_id=end,
                    start_enabled=True,
                    end_enabled=True,
                )
            )
            videos.append(replace(video, segment_id=segment_id))
        scenes.append(
            replace(
                scene,
                id=uid(80000 + n),
                shots=tuple(shots),
                segments=tuple(segments),
                location_id=locations[n].id,
                state_id=None,
            )
        )
    generations = []
    for location in locations:
        for asset_id in (first, second, first):
            generations.append(
                replace(
                    candidate,
                    id=uid(90000 + len(generations)),
                    target_id=location.id,
                    output_asset_id=asset_id,
                )
            )
        for view in location.views:
            generations.append(
                replace(
                    candidate,
                    id=uid(90000 + len(generations)),
                    kind=KIND.LOCATION_VIEW_IMAGE,
                    target_id=view.id,
                    aspect_ratio=None,
                    output_asset_id=first,
                )
            )
    for i in range(510):
        active = i < 10
        generations.append(
            replace(
                candidate,
                id=uid(90000 + len(generations)),
                kind=KIND.KEYFRAME_IMAGE,
                target_id=frames[i % 200].id,
                aspect_ratio=None,
                phase=ReferenceGenerationPhase.RUNNING if active else candidate.phase,
                output_asset_id=None if active else first,
            )
        )
    document = replace(
        document,
        location_library=LocationLibrary(tuple(locations)),
        director_script=replace(
            document.director_script, scenes=tuple(scenes), production_baseline_scenes=tuple(scenes)
        ),
        dialogue_plan=replace(document.dialogue_plan, items=()),
        keyframe_plan=replace(
            document.keyframe_plan, keyframes=tuple(frames), segments=tuple(bindings)
        ),
        video_plan=replace(document.video_plan, segments=tuple(videos)),
        generations=tuple(generations),
    )
    return rig, document


def measure_projection(document, service, repeats=5):
    samples = []
    for _ in range(repeats):
        start = perf_counter()
        location_library_projection(document, service)
        samples.append((perf_counter() - start) * 1000)
    return median(samples), samples


def test_scaled_projection_avoids_image_reads_and_mutations(tmp_path, monkeypatch):
    from pathlib import Path
    from unittest.mock import patch

    import core.structured_director.store as store_module
    from core.structured_director import location_mutations
    from core.structured_director.store import StructuredDirectorStore

    rig, document = scaled_project(tmp_path)
    assert len(document.location_library.locations) == 10
    assert sum(len(location.views) for location in document.location_library.locations) == 60
    assert sum(len(location.fixtures) for location in document.location_library.locations) == 80
    assert len(document.keyframe_plan.keyframes) == 200
    assert len(document.generations) == 600
    monkeypatch.setattr(store_module, "_LOCATION_PANO_SOURCES", {})
    with patch.object(rig.store, "read_asset", wraps=rig.store.read_asset) as reader:
        expected = location_library_projection(document, rig.service)
        assert reader.call_count == 2  # 30 主图候选共享两份不可变内容。
    with (
        patch.object(Path, "read_bytes", side_effect=AssertionError("snapshot read file bytes")),
        patch.object(
            StructuredDirectorStore,
            "read_asset",
            side_effect=AssertionError("warm snapshot read image bytes"),
        ),
        patch.object(
            location_mutations,
            "apply_location_operations",
            side_effect=AssertionError("snapshot ran a mutation"),
        ),
        patch.object(
            location_mutations,
            "select_location_master",
            side_effect=AssertionError("snapshot ran a selection"),
        ),
        patch.object(
            location_mutations,
            "select_location_view",
            side_effect=AssertionError("snapshot ran a selection"),
        ),
    ):
        assert location_library_projection(document, rig.service) == expected
        elapsed, samples = measure_projection(document, rig.service)
    print(f"location projection median={elapsed:.3f} ms, samples={samples}")
    assert elapsed < 100  # 宽松 CPU 门槛；原实现本机约 300 ms。


def test_indexed_permissions_match_formal_mutations(tmp_path):
    """所有删除/清除/选择动作与正式 mutation 比对，包括 no-op 和下游非终态。"""
    from core.director_commands import (
        LocationMasterSelection,
        LocationViewSelection,
        parse_location_operations_patch,
    )
    from core.structured_director.location_mutations import (
        apply_location_operations,
        select_location_master,
        select_location_view,
    )

    rig, document = scaled_project(tmp_path)
    result = location_library_projection(document, rig.service)

    def accepted(call):
        try:
            call()
        except ValueError:
            return False
        return True

    for location, row in zip(document.location_library.locations, result["locations"], strict=True):

        def operation(op, location_id=location.id):
            return accepted(
                lambda: apply_location_operations(
                    document,
                    parse_location_operations_patch(
                        {
                            "scope": {
                                "location_ids": [location_id],
                                "scene_ids": [],
                                "shot_ids": [],
                            },
                            "operations": [op],
                        }
                    ),
                )
            )

        assert ("delete" in row["allowed_actions"]) == operation(
            {"op": "delete_location", "location_id": location.id}
        )
        assert ("clear_selection" in row["master"]["production"]["allowed_actions"]) == operation(
            {"op": "clear_master_selection", "location_id": location.id}
        )
        for key, kind in (("fixtures", "fixture"), ("states", "state")):
            for item in row[key]:
                assert ("delete" in item["allowed_actions"]) == operation(
                    {
                        "op": f"delete_{kind}",
                        "location_id": location.id,
                        f"{kind}_id": item["id"],
                    }
                )
        for view, vrow in zip(location.views, row["views"], strict=True):
            assert ("delete" in vrow["production"]["allowed_actions"]) == operation(
                {"op": "delete_view", "view_id": view.id}
            )
            assert ("clear_selection" in vrow["production"]["allowed_actions"]) == (
                view.selected_asset_id is not None
                and operation({"op": "clear_view_selection", "view_id": view.id})
            )
        for production, target, selection in [
            (row["master"]["production"], location.id, select_location_master),
            *(
                (vrow["production"], view.id, select_location_view)
                for view, vrow in zip(location.views, row["views"], strict=True)
            ),
        ]:
            candidates = [
                g for g in document.generations if g.id in production["candidate_generation_ids"]
            ]
            for generation in candidates:
                value = (
                    LocationMasterSelection
                    if selection is select_location_master
                    else LocationViewSelection
                )(target, generation.output_asset_id)
                assert (generation.id in production["selectable_generation_ids"]) == accepted(
                    lambda selection=selection, value=value: selection(document, value)
                )
