"""Core 计算的视频 recipe 投影样本；Web 测试不复制标签或切换规则。"""

import asyncio
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_director_commands import _ScriptCompiler, _visual_project
from test_prompt_worksets import fixture as dialogue_fixture

from core.model_providers.recipe import RecipeInputs
from core.structured_director.models import Asset
from core.structured_director.reads.video_recipes import video_recipe_state


class QuietScript(_ScriptCompiler):
    async def propose(self, **kwargs):
        proposal = await super().propose(**kwargs)
        return replace(
            proposal,
            scenes=tuple(
                replace(
                    scene,
                    segments=tuple(
                        replace(segment, dialogue_lines=()) for segment in scene.segments
                    ),
                )
                for scene in proposal.scenes
            ),
        )


async def build(output):
    with tempfile.TemporaryDirectory() as directory:
        _, service, document, _ = await _visual_project(directory, script_proposer=QuietScript())
        video = document.video_plan.segments[1]
        boundary = next(
            item for item in document.keyframe_plan.segments if item.segment_id == video.segment_id
        )
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
        with tempfile.TemporaryDirectory() as dialogue_directory:
            _, dialogue_service, dialogue_document, _ = await dialogue_fixture(
                Path(dialogue_directory)
            )
            dialogue_video = dialogue_document.video_plan.segments[0]
            states["dialogue"] = video_recipe_state(
                dialogue_document,
                dialogue_video,
                dialogue_service._registry,
                dialogue_service.provider_recipe_views(),
            )
            line_id = dialogue_document.director_script.scenes[0].segments[0].dialogue_lines[1].id
            missing = replace(
                dialogue_document,
                dialogue_plan=replace(
                    dialogue_document.dialogue_plan,
                    items=tuple(
                        replace(item, selected_audio_asset_id=None, start_seconds=None)
                        if item.dialogue_line_id == line_id
                        else replace(item, start_seconds=None)
                        for item in dialogue_document.dialogue_plan.items
                    ),
                ),
            )
            states["dialogue_missing"] = video_recipe_state(
                missing,
                dialogue_video,
                dialogue_service._registry,
                dialogue_service.provider_recipe_views(),
            )
        output.write_text(
            json.dumps({"views": views, "states": states}, ensure_ascii=False, indent=2) + "\n"
        )


if __name__ == "__main__":
    asyncio.run(build(Path(sys.argv[1])))
