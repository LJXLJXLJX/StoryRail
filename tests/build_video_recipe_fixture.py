"""Core 计算的视频 recipe 投影样本；Web 测试不复制标签或切换规则。"""

import asyncio
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from test_director_commands import _visual_project

from core.model_providers.recipe import RecipeInputs
from core.structured_director.models import Asset
from core.structured_director.reads.video_recipes import video_recipe_state


async def build(output):
    with tempfile.TemporaryDirectory() as directory:
        _, service, document, _ = await _visual_project(directory)
        video = document.video_plan.segments[0]
        boundary = document.keyframe_plan.segments[0]
        ids = {boundary.start_keyframe_id: "1" * 32, boundary.end_keyframe_id: "2" * 32}
        assets = tuple(
            Asset(
                id=asset_id,
                media_type="image/png",
                byte_count=32,
                sha256=asset_id * 2,
                relative_path=f"assets/images/keyframes/{asset_id}.png",
                duration_seconds=None,
            )
            for asset_id in ids.values()
        )
        document = replace(
            document,
            assets=(*document.assets, *assets),
            keyframe_plan=replace(
                document.keyframe_plan,
                keyframes=tuple(
                    replace(frame, selected_asset_id=ids[frame.id]) if frame.id in ids else frame
                    for frame in document.keyframe_plan.keyframes
                ),
                segments=tuple(
                    replace(item, start_enabled=True, end_enabled=True)
                    if item.segment_id == video.segment_id
                    else item
                    for item in document.keyframe_plan.segments
                ),
            ),
        )
        views = service.provider_recipe_views()
        states = {
            recipe_id: video_recipe_state(
                document, replace(video, active_recipe=recipe_id), service._registry, views
            )
            for recipe_id in ("minimax_h3.fl2va", "minimax_h3.ref2va")
        }
        inputs = RecipeInputs.from_json(
            {
                "bindings": {
                    "additional_images": [{"asset_id": "1" * 32, "description": "视觉参考"}]
                },
                "params": {},
            }
        )
        blocked = replace(
            video,
            active_recipe="minimax_h3.ref2va",
            recipes=video.recipes.with_entry("minimax_h3.ref2va", inputs),
        )
        states["blocked"] = video_recipe_state(document, blocked, service._registry, views)
        output.write_text(
            json.dumps({"views": views, "states": states}, ensure_ascii=False, indent=2) + "\n"
        )


if __name__ == "__main__":
    import sys

    asyncio.run(build(Path(sys.argv[1])))
