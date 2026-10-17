"""T11原创合成项目；全部业务写入（含地点库与绑定）均走现有Core。"""

import base64
from dataclasses import asdict, replace
from uuid import uuid4

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_proposals import (
    DialogueLineProposal,
    SceneProposal,
    ShotProposal,
    ShotSegmentProposal,
    StructuredDirectorScriptProposal,
)
from core.model_providers.minimax_h3.plugin import plugin_instance
from core.model_providers.minimax_h3.prompt_context import context_from_workset
from core.model_providers.registry import ProviderRegistry
from core.structured_director import (
    ImageAssetCategory,
    StructuredDirectorService,
)
from core.structured_director.models import CharacterLook, ReferenceGenerationKind
from core.structured_director.prompt_worksets import keyframe_workset, video_prompt_workset
from scripts.harness.fixtures.candidates import register_image_candidate


async def prepare(store, value):
    doc = store.read()
    a, b = doc.reference_library.characters
    kind = value["prompt_fixture"]
    dialogue = (
        (
            DialogueLineProposal(a.id, "给你。", "平静。"),
            DialogueLineProposal(b.id, "谢谢。", "自然。"),
        )
        if kind == "ref2va"
        else ()
    )
    proposal = StructuredDirectorScriptProposal(
        (
            SceneProposal(
                title="桌边递杯",
                summary="甲将白色杯子交给乙。",
                setting="白墙房间，右侧方窗，中央木桌。",
                shots=(
                    ShotProposal(
                        visible_character_ids=(a.id, b.id),
                        composition="固定中景，甲左乙右。",
                        camera_movement="固定。",
                        action="甲递出白色杯子，乙接稳。",
                        audio_direction="安静室内环境声。",
                        transition_in=None,
                    ),
                ),
                segments=(
                    ShotSegmentProposal(
                        shot_indexes=(0,),
                        duration_estimate_seconds=3,
                        action="甲递杯，乙接稳，保持左右站位。",
                        dialogue_lines=dialogue,
                        boundary_from_previous=None,
                    ),
                ),
                narration_cues=(),
                driver="drama",
            ),
        )
    )
    providers = ProviderRegistry()
    providers.install(plugin_instance("http://127.0.0.1:9"))
    service = StructuredDirectorService(store, providers)
    from scripts.benchmark_project_storage import confirm_fixture_references

    doc = confirm_fixture_references(store)
    doc, _ = store.begin_script_proposal(expected_revision=doc.revision)
    doc = store.apply_script_proposal(proposal)
    doc = await service.confirm_script(expected_revision=doc.revision)
    doc = service.snapshot_required()
    scene = doc.director_script.scenes[0]
    segment = scene.segments[0]
    assets = {}
    for name, encoded in value["images"].items():
        doc = await service.import_image_asset(
            media_type="image/png",
            content=base64.b64decode(encoded),
            category=ImageAssetCategory.KEYFRAME,
            filename=name,
            expected_revision=doc.revision,
        )
        assets[name] = doc.assets[-1].id
    for character, name in [(a, "character-a.png"), (b, "character-b.png")]:
        look = CharacterLook(uuid4().hex, "日常", "固定服装", "全片")
        doc = await service.update_character(
            replace(character, looks=(look,)),
            expected_revision=doc.revision,
            created_look_ids=frozenset({look.id}),
        )
        doc = await service.select_look_asset(
            card_id=character.id,
            look_id=look.id,
            asset_id=assets[name],
            expected_revision=doc.revision,
        )
    registry = DirectorCommandRegistry(store)
    doc = _bind_location(store, registry, doc, scene, assets["scene.png"])
    view_id = doc.location_library.locations[0].views[0].id
    doc = await service.unlock_visual_production(expected_revision=doc.revision)
    binding = doc.keyframe_plan.segments[0]
    ops = [
        {
            "op": "set_activation",
            "segment_id": segment.id,
            "start_enabled": True,
            "end_enabled": True,
        },
        {
            "op": "set_aux_references",
            "segment_id": segment.id,
            "asset_ids": [assets["aux-cup.png"]],
        },
    ]
    for f in doc.keyframe_plan.keyframes:
        ops.append(
            {
                "op": "update_frame_fields",
                "keyframe_id": f.id,
                "fields": {
                    "prompt_text": "甲持杯准备递出。"
                    if f.id == binding.start_keyframe_id
                    else "乙接稳白杯，甲已松手。",
                    "visible_character_ids": [a.id, b.id],
                    "environment_mode": "edit",
                    "environment_view_id": view_id,
                    "environment_none_reason": None,
                },
            }
        )
    doc = registry.execute(
        DirectorCommand("keyframe.apply_operations", doc.revision, "frames", {"operations": ops})
    ).document
    for frame_id, name in [
        (binding.start_keyframe_id, "start.png"),
        (binding.end_keyframe_id, "end.png"),
    ]:
        doc = await service.select_keyframe(
            keyframe_id=frame_id, asset_id=assets[name], expected_revision=doc.revision
        )
    for index, character in enumerate((a, b), 1):
        doc = await service.upload_reference_voice(
            card_id=character.id,
            media_type="audio/wav",
            content=base64.b64decode(value["audios"][f"audio-{index}.wav"]),
            expected_revision=doc.revision,
        )
    if kind == "ref2va":
        doc = registry.execute(
            DirectorCommand(
                "video.set_recipe",
                doc.revision,
                "mode",
                {
                    "scope": {"scene_ids": [scene.id]},
                    "segment_id": segment.id,
                    "recipe_id": "minimax_h3.ref2va",
                },
            )
        ).document
        voice_ids = tuple(
            character.voice_reference_asset_id for character in doc.reference_library.characters
        )
        if any(asset_id is None for asset_id in voice_ids):
            raise ValueError("Ref2VA fixture 参考音频未就绪。")
        doc = await service.save_segment_video_inputs(
            segment_id=segment.id,
            prompt_text="",
            bindings={
                "reference_audios": [
                    {
                        "asset_id": asset_id,
                        "description": "甲的音色参考。" if index == 1 else "原样使用乙的这段对白。",
                    }
                    for index, asset_id in enumerate(voice_ids, 1)
                    if asset_id is not None
                ]
            },
            params={},
            expected_revision=doc.revision,
        )
    public = {
        "project_id": doc.project_id,
        "expected_revision": doc.revision,
        "scene_id": scene.id,
        "segment_id": segment.id,
        "keyframe_id": binding.end_keyframe_id,
        "prompt_fixture": kind,
        "director_plan_markdown": doc.director_plan_markdown,
        "user_message": "请用中文；保留原对白（若有），无字幕、无水印、不增加角色。",
    }
    if kind == "keyframe":
        workset = next(x for x in keyframe_workset(doc, segment.id) if x["slot"] == "end")
        public["workset"] = workset
        public["reference_images"] = [
            base64.b64encode(store.read_asset(x["asset_id"])[1]).decode()
            for x in workset["image_inputs"]
        ]
    else:
        public["context"] = asdict(
            context_from_workset(
                video_prompt_workset(doc, segment.id, provider_recipes=providers.recipe_views())
            )
        )
    return public


def _bind_location(store, registry, doc, scene, asset_id):
    """白墙房间：经正式地点操作建库并绑定 Scene 与其 Shot；视图由人类选择入口选用合成图片。"""
    shot_ids = [shot.id for shot in scene.shots]
    created = registry.execute(
        DirectorCommand(
            "location.apply_operations",
            doc.revision,
            "location",
            {
                "scope": {"location_ids": [], "scene_ids": [scene.id], "shot_ids": shot_ids},
                "operations": [
                    {
                        "op": "create_location",
                        "key": "room",
                        "name": "白墙房间",
                        "kind": "interior",
                        "description": "白墙房间，右侧方窗，中央木桌。",
                    },
                    {
                        "op": "update_location",
                        "location_id": "room",
                        "fields": {"master_prompt_text": "白墙房间全景。"},
                    },
                    {
                        "op": "create_view",
                        "location_id": "room",
                        "key": "table",
                        "fields": {
                            "name": "桌边中景",
                            "purpose": "固定中景，甲左乙右",
                            "azimuth_deg": 0.0,
                        },
                    },
                    {
                        "op": "bind_scene",
                        "scene_id": scene.id,
                        "location_id": "room",
                        "state_id": None,
                    },
                    *(
                        {"op": "bind_shot", "shot_id": item, "view_id": "table"}
                        for item in shot_ids
                    ),
                ],
            },
        )
    )
    view_id = created.data["created_ids"]["table"]
    register_image_candidate(
        store,
        kind=ReferenceGenerationKind.LOCATION_VIEW_IMAGE,
        target_id=view_id,
        asset_id=asset_id,
    )
    return registry.execute(
        DirectorCommand(
            "location.select_view",
            store.read().revision,
            "location-view",
            {"view_id": view_id, "asset_id": asset_id},
        )
    ).document
