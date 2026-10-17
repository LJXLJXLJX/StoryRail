"""生成浏览器 smoke 的合成投影，不访问真实作品或 Provider。"""

import asyncio
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from provider_factory import provider_registry
from structured_director_fixtures import RecordingProvider
from test_scene_driver_invariants import (
    MixedProposer,
    insert_shot,
    narration_project,
    select_audio,
)

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.structured_director.reads.semantic_projection import build_semantic_projection
from core.structured_director.reads.snapshot_view import serialize_snapshot


class SmokeProposer(MixedProposer):
    async def propose(self, **kwargs):
        proposal = await super().propose(**kwargs)
        narration, drama = proposal.scenes
        return replace(
            proposal,
            scenes=(
                replace(narration, title="潮声之前", summary="天亮前，海边车站尚无人声。"),
                replace(drama, title="沿岸行走", summary="小满握住行李箱，在海风里等候。"),
                replace(drama, title="远处的灯", summary="她沿着同一片海岸望去。" * 50),
            ),
        )


async def build(path):
    with tempfile.TemporaryDirectory() as directory:
        store, service, _, document = await narration_project(Path(directory), SmokeProposer())
        document = await select_audio(service, document)
        scene = document.director_script.scenes[1]
        document = insert_shot(
            DirectorCommandRegistry(store),
            document,
            scene_id=scene.id,
            after_shot_id=scene.shots[-1].id,
            idempotency_key="smoke-long-shot",
        ).document
        projections = {}
        queries = [("outline", {"project_id": document.project_id})]
        queries += [
            (level, {"scene_ids": [scene.id]})
            for scene in document.director_script.scenes
            for level in ("scene", "shot", "segment")
        ]
        for level, scope in queries:
            request = {"level": level, "scope": scope, "extensions": ["text"], "limit": 100}
            projections[level + ":" + scope.get("scene_ids", ["all"])[0]] = (
                build_semantic_projection(document, request)
            )
        # 测试 Provider 中英返回相同字节，两条选择共用同一 Asset。
        selected = document.director_script.scenes[0].narration_cues[0].zh.selected_audio_asset_id
        # 浏览器只需要可试听的 fake WAV；生产 Asset URL 仍由原 snapshot 提供。
        import base64

        from test_scene_driver_invariants import wav_bytes

        audio_url = (
            "data:audio/wav;base64," + base64.b64encode(wav_bytes(duration_seconds=16)).decode()
        )
        value = {
            "project": {"id": document.project_id, "title": "海岸来信", "aspect_ratio": "16:9"},
            "snapshot": {
                "revision": document.revision,
                "assets": [{"id": selected, "content_url": audio_url}],
                "reference_library": {
                    "characters": [
                        {"id": item.id, "name": item.name}
                        for item in document.reference_library.characters
                    ]
                },
                "provider_availability": {"speech_synthesis": True},
            },
            "projections": projections,
        }
        narration = document.director_script.scenes[0]
        document = insert_shot(
            DirectorCommandRegistry(store),
            document,
            scene_id=narration.id,
            after_shot_id=None,
            idempotency_key="smoke-narration-plan",
        ).document
        for plugin in provider_registry(
            fl2va_provider=RecordingProvider(media_type="video/mp4", content=b"fixture"),
            ref2va_provider=RecordingProvider(media_type="video/mp4", content=b"ref-fixture"),
        )._plugins.values():
            service._registry.install(plugin)
        document = await service.unlock_visual_production(expected_revision=document.revision)
        left_segment = document.director_script.scenes[1].segments[-1].id
        right_segment = document.director_script.scenes[2].segments[0].id
        bindings = {item.segment_id: item for item in document.keyframe_plan.segments}
        document = (
            DirectorCommandRegistry(store)
            .execute(
                DirectorCommand(
                    "keyframe.apply_operations",
                    document.revision,
                    "smoke-cross-scene",
                    {
                        "operations": [
                            {
                                "op": "share_boundary",
                                "left_segment_id": left_segment,
                                "right_segment_id": right_segment,
                                "source_keyframe_id": bindings[left_segment].end_keyframe_id,
                            }
                        ],
                    },
                )
            )
            .document
        )
        bindings = {item.segment_id: item for item in document.keyframe_plan.segments}
        assert bindings[left_segment].end_keyframe_id == bindings[right_segment].start_keyframe_id
        continuity_projections = {}
        for level, scope in queries:
            continuity_projections[level + ":" + scope.get("scene_ids", ["all"])[0]] = (
                build_semantic_projection(
                    document,
                    {
                        "level": level,
                        "scope": scope,
                        "extensions": ["text"],
                        "limit": 100,
                    },
                )
            )
        value["continuity"] = {
            "project": value["project"],
            "snapshot": {**value["snapshot"], "revision": document.revision},
            "projections": continuity_projections,
            "shared_boundary_keyframe_id": bindings[left_segment].end_keyframe_id,
            "left_segment_id": left_segment,
            "right_segment_id": right_segment,
        }
        production = serialize_snapshot(document, service, "/synthetic/structured-director")
        for asset in production["assets"]:
            if asset["media_type"] == "audio/wav":
                asset["content_url"] = audio_url
        value["continuity"]["production_snapshot"] = production
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys

    # 无参数保持原行为（写回 web/src/test）；传路径时供 freshness 门禁写到临时目录比较。
    output = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("web/src/test/story_reader_fixture.json")
    )
    asyncio.run(build(output))
