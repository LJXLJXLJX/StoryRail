"""Agent 经 `dialogue.select_candidate` 采用对白 WAV：与人类选择同一字段与失效规则。"""

import asyncio

from structured_director_fixtures import wav_bytes
from test_external_script_proposals import agent, http

from core.application.caller import _AGENT_OPERATIONS
from core.director_commands import DirectorCommand
from core.structured_director.reads.workflow_state import _dialogue_workflow
from scripts.harness.fixtures.candidates import register_dialogue_audio_candidate


async def _command(store, service_, name, key, arguments):
    document = store.read()
    command = DirectorCommand(name, document.revision, key, arguments)
    return await http(service_, agent(document, command), command)


def test_agent_selects_dialogue_audio_like_human_selection(tmp_path):
    from test_prompt_worksets import fixture

    async def run():
        store, service_, document, _ = await fixture(tmp_path)
        segment = document.director_script.scenes[0].segments[0]
        first, *others = segment.dialogue_lines
        card = next(
            item for item in document.reference_library.characters if item.id == first.character_id
        )
        document = await service_.import_media_asset(
            media_type="audio/wav",
            content=wav_bytes(duration_seconds=1.5) + b"agent-pick",
            expected_revision=document.revision,
        )
        new_asset_id = document.assets[-1].id
        generation_id = register_dialogue_audio_candidate(
            store,
            dialogue_line_id=first.id,
            source_asset_id=new_asset_id,
            voice_reference_asset_id=card.voice_reference_asset_id,
            reference_transcript=card.voice_reference_transcript,
            text=first.text,
        )
        before = store.read()

        result = await _command(
            store,
            service_,
            "dialogue.select_candidate",
            "agent-pick",
            {"dialogue_line_id": first.id, "generation_id": generation_id},
        )
        assert result.status == 200, result.body
        selected = store.read()
        items = {item.dialogue_line_id: item for item in selected.dialogue_plan.items}
        assert items[first.id].selected_audio_asset_id == new_asset_id
        assert all(items[line.id].selected_audio_asset_id is not None for line in others)
        assert all(items[line.id].start_seconds is None for line in segment.dialogue_lines)
        video = next(item for item in selected.video_plan.segments if item.segment_id == segment.id)
        assert video.selected_asset_id is None
        assert len(selected.generations) == len(before.generations)

        again = await _command(
            store,
            service_,
            "dialogue.select_candidate",
            "agent-pick-again",
            {"dialogue_line_id": first.id, "generation_id": generation_id},
        )
        assert again.status == 200, again.body
        assert again.body["receipt"]["status"] == "noop"
        assert store.read().dialogue_plan == selected.dialogue_plan

        other_generation = next(
            item.id
            for item in selected.generations
            if item.kind.value == "dialogue_audio" and item.target_id == others[0].id
        )
        wrong = await _command(
            store,
            service_,
            "dialogue.select_candidate",
            "agent-wrong-line",
            {"dialogue_line_id": first.id, "generation_id": other_generation},
        )
        assert wrong.status != 200
        assert store.read().dialogue_plan == selected.dialogue_plan

        extra = await _command(
            store,
            service_,
            "dialogue.select_candidate",
            "agent-extra-field",
            {"dialogue_line_id": first.id, "generation_id": generation_id, "asset_id": "0" * 32},
        )
        assert extra.status != 200

    asyncio.run(run())


def test_dialogue_candidates_are_offered_to_agent_in_workflow(tmp_path):
    from test_prompt_worksets import fixture

    async def run():
        store, service_, document, _ = await fixture(tmp_path)
        first = document.director_script.scenes[0].segments[0].dialogue_lines[0]
        cleared = await service_.clear_dialogue_audio_selection(
            dialogue_line_id=first.id, expected_revision=document.revision
        )
        _stage, phase, actions = _dialogue_workflow(cleared)
        selection = next(item for item in actions if item["action"] == "dialogue.select_candidate")
        assert selection["tool"] == "select_dialogue_candidate"
        assert selection["target_ids"] == [first.id]
        assert selection.get("human_only") is not True
        assert all(item["action"] != "candidate_selection" for item in actions)
        assert phase == "awaiting_human_review"

    asyncio.run(run())
    assert "dialogue.select_candidate" in _AGENT_OPERATIONS
