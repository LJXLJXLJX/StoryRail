"""大型地点库投影只按独立图片和语义引用建立一次索引。"""

from dataclasses import replace
from time import perf_counter

from test_location_generation import Rig

from core.structured_director.location_mutations import LocationActionIndex
from core.structured_director.models import (
    Location,
    LocationImage,
    LocationImageKind,
    LocationLibrary,
)
from core.structured_director.reads.snapshot_view import serialize_snapshot


def uid(number: int) -> str:
    return f"{number:032x}"


def large_document(document, *, locations=200, images=20):
    rows = []
    for location_index in range(locations):
        rows.append(
            Location(
                uid(10_000 + location_index),
                f"地点 {location_index}",
                "共享固定空间。",
                images=tuple(
                    LocationImage(
                        uid(100_000 + location_index * images + image_index),
                        f"图片 {image_index}",
                        (
                            LocationImageKind.PANORAMA
                            if image_index == 0
                            else LocationImageKind.IMAGE
                        ),
                        f"地点 {location_index} 的图片 {image_index} 实际内容。",
                        f"生成地点 {location_index} 的图片 {image_index}。",
                    )
                    for image_index in range(images)
                ),
            )
        )
    return replace(document, location_library=LocationLibrary(tuple(rows)))


def test_action_index_covers_every_image_once(tmp_path):
    rig = Rig(tmp_path)
    document = large_document(rig.document)
    index = LocationActionIndex(document)
    assert len(index.image_ids) == 4_000
    assert len(index.assets) == len(document.assets)
    assert set(index.scene_locations) <= {None}


def test_snapshot_projection_preserves_order_and_cardinality(tmp_path):
    rig = Rig(tmp_path)
    document = large_document(rig.document, locations=80, images=12)
    snapshot = serialize_snapshot(document, rig.service, "/assets")
    locations = snapshot["location_library"]["locations"]
    assert len(locations) == 80
    assert all(len(item["images"]) == 12 for item in locations)
    assert locations[0]["images"][0]["kind"] == "panorama"
    assert locations[-1]["images"][-1]["name"] == "图片 11"


def test_projection_scale_is_linear_enough_for_interactive_read(tmp_path):
    rig = Rig(tmp_path)
    small = large_document(rig.document, locations=25, images=10)
    large = large_document(rig.document, locations=100, images=10)

    start = perf_counter()
    serialize_snapshot(small, rig.service, "/assets")
    small_elapsed = max(perf_counter() - start, 0.001)

    start = perf_counter()
    serialize_snapshot(large, rig.service, "/assets")
    large_elapsed = perf_counter() - start

    assert large_elapsed < 2.0
    assert large_elapsed < small_elapsed * 12


def test_large_library_contains_no_master_view_tree(tmp_path):
    rig = Rig(tmp_path)
    document = large_document(rig.document, locations=10, images=10)
    projection = serialize_snapshot(document, rig.service, "/assets")["location_library"]
    for location in projection["locations"]:
        assert "master" not in location
        assert "views" not in location
        assert all("reference_view_ids" not in image for image in location["images"])
