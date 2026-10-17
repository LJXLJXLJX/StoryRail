"""创建语言契约、单语言完整生产链和跨语言写入拒绝。"""

import asyncio
import json
from dataclasses import replace

import pytest
from proposal_fixture_service import ProposalFixtureService
from structured_director_fixtures import (
    NarrationReferenceProposer,
    RecordingProvider,
    upload_narrator_voice,
    wav_bytes,
)
from test_architecture_acceptance import mixed_acceptance

from core.project_settings import ProjectAspectRatio
from core.project_workspaces import ProjectWorkspaceStore
from core.structured_director import (
    NarrationLanguage,
    StructuredDirectorHttpApi,
    StructuredDirectorStore,
)
from core.structured_director.models._shared import parse_narration_languages
from core.structured_director.reads.professional_worksets import workset_read
from core.structured_director.reads.snapshot_view import serialize_snapshot
from core.structured_director.v32_projection import v32_cue_anchors
from core.web_contracts.snapshot_schema import snapshot_schemas
from server.api import StoryRailApi


@pytest.mark.parametrize("languages", [["zh"], ["en"], ["en", "zh"]])
def test_creation_persists_required_languages_and_they_are_immutable(tmp_path, languages):
    workspaces = ProjectWorkspaceStore(tmp_path)
    api = StoryRailApi(
        workspaces,
        lambda project_id: ProposalFixtureService(workspaces.structured_director_store(project_id)),
    )
    response = asyncio.run(
        api.handle(
            "POST",
            "/api/projects",
            json.dumps(
                {
                    "title": "语言项目",
                    "aspect_ratio": "16:9",
                    "director_plan_markdown": "# 完整方案",
                    "narration_languages": languages,
                }
            ).encode(),
        )
    )
    assert response.status == 201, response.body
    expected = parse_narration_languages(languages)
    assert response.body["structured_director"]["narration_languages"] == list(expected)
    store = api._workspaces.structured_director_store(response.body["project"]["id"])
    document = store.read()
    assert document.narration_languages == expected
    assert json.loads(store.path.read_text())["narration_languages"] == list(expected)
    before = store.path.read_bytes()
    changed = (
        (NarrationLanguage.EN,) if expected == (NarrationLanguage.ZH,) else (NarrationLanguage.ZH,)
    )
    with pytest.raises(ValueError, match="不可修改"):
        store._atomic_write(
            replace(document, revision=document.revision + 1, narration_languages=changed)
        )
    assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    "languages", [None, [], ["fr"], ["zh", "zh"], ["zh", "en", "zh"], "zh", [True]]
)
def test_creation_rejects_invalid_language_selection_without_creating_project(tmp_path, languages):
    workspaces = ProjectWorkspaceStore(tmp_path)
    api = StoryRailApi(
        workspaces,
        lambda project_id: ProposalFixtureService(workspaces.structured_director_store(project_id)),
    )
    body = {"title": "语言项目", "aspect_ratio": "16:9", "director_plan_markdown": "# 完整方案"}
    if languages is not None:
        body["narration_languages"] = languages
    response = asyncio.run(api.handle("POST", "/api/projects", json.dumps(body).encode()))
    assert response.status == 400
    assert api._workspaces.list() == ()
    assert not list(tmp_path.glob("*/project.json"))


@pytest.mark.parametrize("language", [NarrationLanguage.ZH, NarrationLanguage.EN])
def test_single_language_tts_to_scene_final_to_approval_survives_restart(tmp_path, language):
    languages = (language,)
    disabled = NarrationLanguage.EN if language is NarrationLanguage.ZH else NarrationLanguage.ZH

    class ReferenceProposer(NarrationReferenceProposer):
        async def propose(self, **kwargs):
            proposal = await super().propose(**kwargs)
            return replace(
                proposal,
                narrator=replace(
                    proposal.narrator, **{f"{disabled.value}_voice_description": None}
                ),
            )

    async def factory(path, script_proposer):
        class ScriptProposer:
            async def propose(self, **kwargs):
                proposal = await script_proposer.propose(**kwargs)
                return replace(
                    proposal,
                    scenes=tuple(
                        replace(
                            scene,
                            narration_cues=tuple(
                                replace(cue, **{disabled.value: None})
                                for cue in scene.narration_cues
                            ),
                        )
                        for scene in proposal.scenes
                    ),
                )

        store = StructuredDirectorStore(path, "a" * 32)
        store.create_project(
            title="单语言项目",
            aspect_ratio=ProjectAspectRatio.LANDSCAPE,
            director_plan_markdown="# 完整方案",
            narration_languages=languages,
        )
        speech = RecordingProvider(media_type="audio/wav", content=wav_bytes(duration_seconds=16))
        service = ProposalFixtureService(
            store, ReferenceProposer(), script_proposer=ScriptProposer(), speech_provider=speech
        )
        document = await service.prepare_references()
        workset = workset_read(
            document, {"capability": "script", "scope": {"project_id": document.project_id}}
        )
        assert workset["core_facts"]["narration_languages"] == list(languages)
        track_schema = workset["output_schema"]["properties"]["scenes"]["items"]["properties"][
            "narration_cues"
        ]["items"]["properties"]
        assert track_schema[disabled.value] == {"type": "null"}
        assert track_schema[language.value]["type"] == "object"
        document = await upload_narrator_voice(service, document)
        before = store.path.read_bytes()
        before_files = set(path.rglob("*"))
        with pytest.raises(ValueError, match="未启用"):
            await service.upload_narrator_voice(
                narrator_id=document.reference_library.narrator.id,
                language=disabled,
                media_type="audio/wav",
                content=wav_bytes(duration_seconds=4),
                expected_revision=document.revision,
            )
        assert store.path.read_bytes() == before
        assert set(path.rglob("*")) == before_files
        document = await service.prepare_script(expected_revision=document.revision)
        document = await service.confirm_script(expected_revision=document.revision)
        cue = document.director_script.scenes[0].narration_cues[0]
        assert getattr(cue, disabled.value) is None
        before = store.path.read_bytes()
        with pytest.raises(ValueError, match="未启用"):
            await service.generate_narration(
                cue_id=cue.id, language=disabled, expected_revision=document.revision
            )
        assert store.path.read_bytes() == before
        narrator = document.reference_library.narrator
        response = await StructuredDirectorHttpApi(
            service, resource_path="/structured-director"
        ).handle(
            "PUT",
            "/structured-director/narrator",
            json.dumps(
                {
                    "expected_revision": document.revision,
                    "id": narrator.id,
                    "name": "旁白新名称",
                    "zh": None
                    if narrator.zh is None
                    else {
                        "voice_description": narrator.zh.voice_description,
                        "voice_reference_asset_id": narrator.zh.voice_reference_asset_id,
                        "voice_reference_transcript": narrator.zh.voice_reference_transcript,
                    },
                    "en": None
                    if narrator.en is None
                    else {
                        "voice_description": narrator.en.voice_description,
                        "voice_reference_asset_id": narrator.en.voice_reference_asset_id,
                        "voice_reference_transcript": narrator.en.voice_reference_transcript,
                    },
                }
            ).encode(),
        )
        assert response.status == 200, response.body
        wire_narrator = serialize_snapshot(store.read(), service, "/r")["reference_library"][
            "narrator"
        ]
        assert set(snapshot_schemas()["NarratorProfile"]["required"]) <= wire_narrator.keys()
        assert wire_narrator[disabled.value] is None
        assert wire_narrator[language.value]["voice_description"]
        # Web 保存旁白参数时未启用语言整条传 null，必须正常保存而不是 500。
        document = store.read()
        scene = document.director_script.scenes[0]
        cue = scene.narration_cues[0]
        track = getattr(cue, language.value)
        response = await StructuredDirectorHttpApi(
            service, resource_path="/structured-director"
        ).handle(
            "PUT",
            f"/structured-director/scenes/{scene.id}/narration-cues/{cue.id}",
            json.dumps(
                {
                    "expected_revision": document.revision,
                    "start_shot_id": v32_cue_anchors(scene)[0],
                    "end_shot_id": v32_cue_anchors(scene)[1],
                    language.value: {
                        "text": track.text + "。",
                        "seed": track.seed,
                        "recipe_params": track.recipe_params.to_json(),
                    },
                    disabled.value: None,
                }
            ).encode(),
        )
        assert response.status == 200, response.body
        saved = store.read().director_script.scenes[0].narration_cues[0]
        assert getattr(saved, language.value).text == track.text + "。"
        assert getattr(saved, disabled.value) is None
        return store, service, speech, store.read()

    document = asyncio.run(mixed_acceptance(tmp_path, project_factory=factory))
    assert all(
        item.language in languages for item in document.generations if item.language is not None
    )
    assert document.final_approval.asset_id(language) is not None
    assert document.final_approval.asset_id(disabled) is None
    assert document.final_approval.generation_id(disabled) is None
    assert all(clip.asset_id(disabled) is None for clip in document.final_assembly.clips)
    from core.structured_director.production_context import _script_json

    cue_json = json.loads(_script_json(document.director_script.scenes, document))["scenes"][0][
        "narration_cues"
    ][0]
    assert cue_json[disabled.value] is None
    assert cue_json[language.value]["text"]
