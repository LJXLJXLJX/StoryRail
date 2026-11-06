"""v19 同一 Store 的原子回执、重放、授权与提交不确定恢复。"""

import asyncio
import json
from dataclasses import asdict, replace
from unittest.mock import patch

import pytest
from conftest import make_service
from test_director_commands import _script_shot_payload, _visual_project

from core.application.caller import (
    AccessDenied,
    Caller,
    MutationGrant,
    command_digest,
    current_caller,
)
from core.director_commands import DirectorCommand
from core.structured_director import StructuredDirectorService, StructuredDirectorStore
from core.structured_director.errors import RevisionConflictError


def human(project_id, caller_id="human"):
    return Caller(
        caller_id, "human", frozenset({project_id}), frozenset({"human.write"}), 4102444800
    )


async def execute(service, caller, command):
    token = current_caller.set(caller)
    try:
        return await service.execute_director_command(command)
    finally:
        current_caller.reset(token)


def edit(document, key="edit"):
    scene = document.director_script.scenes[0]
    return DirectorCommand(
        "script.apply_operations",
        document.revision,
        key,
        {
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "update_shot_fields",
                    "shot_id": scene.shots[0].id,
                    "fields": {"action": "应用边界的新动作"},
                }
            ],
        },
    )


def test_atomic_commit_and_response_loss_restart_replay(tmp_path):
    async def run():
        store, service, document, _ = await _visual_project(str(tmp_path))
        caller, command = human(document.project_id), edit(document)
        before = store.path.read_bytes()
        with (
            patch(
                "core.structured_director.store.os.replace", side_effect=OSError("commit failed")
            ),
            pytest.raises(OSError),
        ):
            await execute(service, caller, command)
        assert store.path.read_bytes() == before
        first, concurrent = await asyncio.gather(
            execute(service, caller, command), execute(service, caller, command)
        )
        assert first.replay is False and concurrent.replay is True
        assert first.receipt == concurrent.receipt
        assert len(store.read().application_requests) == len(document.application_requests) + 1
        assert store.read().revision == document.revision + 1
        saved = store.path.read_bytes()
        restarted = StructuredDirectorService(
            StructuredDirectorStore(store.path.parent, document.project_id)
        )
        replay = await execute(restarted, caller, command)  # 原 revision，模拟响应丢失/进程重建
        assert replay.receipt == first.receipt and replay.replay
        assert store.path.read_bytes() == saved
        for changed in [
            replace(command, arguments={}),
            replace(command, expected_revision=first.document.revision),
        ]:
            with pytest.raises(RevisionConflictError, match="幂等键"):
                await execute(restarted, caller, changed)
        with pytest.raises(RevisionConflictError):
            await execute(restarted, human(document.project_id, "second"), command)
        with pytest.raises(AccessDenied):
            await execute(restarted, replace(caller, project_ids=frozenset({"e" * 32})), command)
        with pytest.raises(AccessDenied):
            await execute(restarted, replace(caller, expires_at=0), command)

    asyncio.run(run())


def test_insert_delete_and_noop_receipts_are_original(tmp_path):
    async def run():
        store, service, document, _ = await _visual_project(str(tmp_path))
        caller = human(document.project_id)
        scene = document.director_script.scenes[0]
        first_segment = next(
            segment for segment in scene.segments if scene.shots[0].id in segment.shot_ids
        )
        insert = DirectorCommand(
            "script.apply_operations",
            document.revision,
            "insert",
            {
                "scope": {"scene_ids": [scene.id]},
                "operations": [
                    {
                        "op": "insert_shot",
                        "scene_id": scene.id,
                        "after_shot_id": scene.shots[0].id,
                        "shot": _script_shot_payload(
                            scene.shots[0].visible_character_ids[0], "新镜头"
                        ),
                        "attach_to_segment_id": first_segment.id,
                    }
                ],
            },
        )
        first = await execute(service, caller, insert)
        again = await execute(service, caller, insert)
        assert first.receipt == again.receipt and again.replay
        shot_id = first.document.director_script.scenes[0].shots[1].id
        delete = DirectorCommand(
            "script.apply_operations",
            first.document.revision,
            "delete",
            {
                "scope": {"scene_ids": [scene.id]},
                "operations": [
                    {
                        "op": "delete_shot",
                        "scene_id": scene.id,
                        "shot_id": shot_id,
                    }
                ],
            },
        )
        deleted = await execute(service, caller, delete)
        assert (await execute(service, caller, delete)).receipt == deleted.receipt
        assert not any(s.id == shot_id for s in store.read().director_script.scenes[0].shots)
        command = edit(store.read())
        result = await execute(service, caller, command)
        noop = await execute(
            service,
            caller,
            replace(
                command, expected_revision=result.document.revision, idempotency_key="new-noop"
            ),
        )
        assert noop.receipt.status == "noop"
        assert store.read().revision == noop.receipt.new_revision
        value = json.loads(store.path.read_text())
        value["application_requests"][0]["unexpected"] = True
        store.path.write_text(json.dumps(value))
        with pytest.raises(ValueError, match="application request"):
            store.read()

    asyncio.run(run())


def test_generation_grant_submit_replay_and_uncertain_restart():
    from keyframe_wave_fixtures import KeyframeWaveFixture

    async def run(interrupted):
        fixture = KeyframeWaveFixture()
        await fixture.asyncSetUp()
        try:
            service, store, provider = fixture.service, fixture.store, fixture.provider
            document = store.read()
            frame_id = document.keyframe_plan.segments[0].start_keyframe_id
            command = DirectorCommand(
                "keyframe.generate", document.revision, "generate-once", {"keyframe_id": frame_id}
            )
            grant = MutationGrant(
                "explicit-generate",
                document.project_id,
                command_digest(asdict(command)),
                4102444800,
            )
            caller = Caller(
                "agent",
                "agent",
                frozenset({document.project_id}),
                frozenset({"project.read", "project.mutate"}),
                4102444800,
                (grant,),
                True,
            )
            for forbidden in [
                replace(command, arguments={"keyframe_id": "e" * 32}),
                replace(command, expected_revision=document.revision + 1),
                replace(command, name="final.approve"),
            ]:
                with pytest.raises(AccessDenied):
                    await execute(service, caller, forbidden)
            assert len(provider.requests) == 0
            if interrupted:
                with (
                    patch.object(store, "update_generation", side_effect=asyncio.CancelledError),
                    pytest.raises(asyncio.CancelledError),
                ):
                    await execute(service, caller, command)
                pending = store.read().application_requests[-1]
                assert pending.phase == "pending" and len(pending.generation_ids) == 1
                assert len(provider.requests) == 1
                service = make_service(
                    StructuredDirectorStore(store.path.parent, document.project_id),
                    image_provider=provider,
                )
                replay = await execute(service, caller, command)
                assert replay.data["phase"] == "uncertain" and replay.replay
                assert service._store.read().application_requests[-1].phase == "uncertain"
            else:
                first = await execute(service, caller, command)
                replay = await execute(service, caller, command)
                assert first.receipt == replay.receipt and replay.replay
                assert first.data["phase"] == "committed"
                assert len(first.data["generation_ids"]) == 1
            assert len(provider.requests) == 1
            with pytest.raises(AccessDenied):
                await execute(service, replace(caller, grants=()), command)
        finally:
            fixture.directory.cleanup()

    asyncio.run(run(False))
    asyncio.run(run(True))
