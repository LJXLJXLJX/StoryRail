"""PG3-T2：Playground 命令信封、摘要与持久幂等。"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from core.application.caller import Caller
from core.model_providers.boundary import GenerationPhase
from core.model_providers.manifest import Capability
from core.playground.commands import (
    ALL_COMMANDS,
    OBSERVE_COMMANDS,
    READ_COMMANDS,
    SIGNAL_COMMANDS,
    WRITE_COMMANDS,
    ReplayedRequest,
    execute_command,
    request_context,
    stage_request,
)
from core.playground.errors import IdempotencyConflictError
from core.playground.lifecycle import utc_timestamp
from core.playground.models import PlaygroundRequestRecord, RunPhase, canonical_json
from tests.playground_fixtures import real_mp4_bytes
from tests.playground_recipes import PlaygroundCapability
from tests.test_playground_service import PNG, build, ingest, parameters_for

HUMAN = Caller("human-1", "human", frozenset(), frozenset({"human.write"}), 2**62)
AGENT = Caller("agent-1", "agent", frozenset(), frozenset({"playground.use"}), 2**62)


def envelope(name: str, arguments: dict, key: str) -> dict:
    return {"name": name, "idempotency_key": key, "arguments": arguments}


def test_command_sets_are_disjoint_and_complete() -> None:
    assert ALL_COMMANDS == READ_COMMANDS | OBSERVE_COMMANDS | WRITE_COMMANDS | SIGNAL_COMMANDS
    assert not READ_COMMANDS & WRITE_COMMANDS
    assert not SIGNAL_COMMANDS & (READ_COMMANDS | OBSERVE_COMMANDS | WRITE_COMMANDS)
    assert len(ALL_COMMANDS) == 11


def test_envelope_rejects_unknown_fields_and_names() -> None:
    with pytest.raises(ValueError, match="命令信封"):
        request_context(
            {"name": "playground.list_runs", "idempotency_key": "k", "arguments": {}, "x": 1},
            HUMAN,
        )
    with pytest.raises(ValueError, match="不支持的命令"):
        request_context(envelope("playground.nope", {}, "k"), HUMAN)
    with pytest.raises(ValueError, match="idempotency_key"):
        request_context(envelope("playground.list_runs", {}, ""), HUMAN)
    with pytest.raises(ValueError, match="arguments 字段不合法"):
        request_context(envelope("playground.list_runs", {"limit": 1}, "k"), HUMAN)
    with pytest.raises(ValueError, match="arguments 字段不合法"):
        request_context(
            envelope("playground.list_runs", {"limit": 1, "cursor": None, "capability": None}, "k"),
            HUMAN,
        )


def test_anonymous_caller_in_dev_mode(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        result = await execute_command(
            service,
            envelope(
                "playground.list_capabilities",
                {},
                "read-1",
            ),
            None,
        )
        assert result["receipt"]["status"] == "noop"
        assert len(result["data"]["capabilities"]) == 5
        assert result["data"]["capabilities"][0]["parameters_schema"]

    asyncio.run(scenario())


def test_read_commands_do_not_change_revision(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        before = service.snapshot()
        for name, arguments in (
            ("playground.list_capabilities", {}),
            (
                "playground.list_runs",
                {"limit": 10, "cursor": None, "capability": None, "include_dismissed": False},
            ),
            ("playground.list_assets", {"limit": 10, "cursor": None, "media_kind": None}),
        ):
            result = await execute_command(service, envelope(name, arguments, f"k-{name}"), HUMAN)
            assert result["receipt"]["old_revision"] == before.revision
            assert result["receipt"]["new_revision"] == before.revision
        after = service.snapshot()
        assert after.revision == before.revision
        assert after.application_requests == ()

    asyncio.run(scenario())


def test_capabilities_command_includes_schema(playground_factory) -> None:
    async def scenario() -> None:
        service, _assets = build(playground_factory)
        result = await execute_command(
            service, envelope("playground.list_capabilities", {}, "caps"), HUMAN
        )
        guide = result["data"]["image_prompt"]
        assert guide["global_skills"][0]["name"] == "storyrail-image-prompt-writing"
        assert "没有任何实际图片输入时" in guide["global_skills"][0]["resources"][0]["text"]
        for descriptor in result["data"]["capabilities"]:
            assert set(descriptor) == {
                "id",
                "label",
                "execution",
                "group",
                "available",
                "notes",
                "parameters_schema",
                "recipe",
            }
            assert descriptor["parameters_schema"]["additionalProperties"] is False

    asyncio.run(scenario())


def test_submit_replay_returns_first_receipt_without_second_provider_call(
    playground_factory,
) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        arguments = {
            "capability": "minimax_h3.fl2va",
            "parameters": parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            "note": "第一次",
        }
        first = await execute_command(
            service, envelope("playground.submit_run", arguments, "fl2va-1"), HUMAN
        )
        assert first["receipt"]["status"] == "succeeded"
        assert first["data"]["run"]["phase"] == "submitting"
        provider = service.registry.prepare_recipe(
            Capability.VIDEO_GENERATE, recipe_id="minimax_h3.fl2va"
        ).plugin.recipes["minimax_h3.fl2va"]
        assert len(provider.requests) == 1

        second = await execute_command(
            service, envelope("playground.submit_run", arguments, "fl2va-1"), HUMAN
        )
        assert second == first
        assert len(provider.requests) == 1
        assert len(service.snapshot().runs) == 1
        assert len(service.snapshot().application_requests) == 1

    asyncio.run(scenario())


def test_same_key_different_arguments_conflict(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        parameters = parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets)
        await execute_command(
            service,
            envelope(
                "playground.submit_run",
                {"capability": "minimax_h3.fl2va", "parameters": parameters, "note": None},
                "same-key",
            ),
            HUMAN,
        )
        with pytest.raises(IdempotencyConflictError, match="同一 idempotency_key"):
            await execute_command(
                service,
                envelope(
                    "playground.submit_run",
                    {
                        "capability": "minimax_h3.fl2va",
                        "parameters": {**parameters, "seed": 99},
                        "note": None,
                    },
                    "same-key",
                ),
                HUMAN,
            )

    asyncio.run(scenario())


def test_concurrent_same_key_submits_once(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        arguments = {
            "capability": "minimax_h3.fl2va",
            "parameters": parameters_for(PlaygroundCapability.VIDEO_FL2VA, assets),
            "note": None,
        }
        first, second = await asyncio.gather(
            execute_command(service, envelope("playground.submit_run", arguments, "race"), HUMAN),
            execute_command(service, envelope("playground.submit_run", arguments, "race"), HUMAN),
        )
        assert first == second
        assert (
            len(
                service.registry.prepare_recipe(
                    Capability.VIDEO_GENERATE, recipe_id="minimax_h3.fl2va"
                )
                .plugin.recipes["minimax_h3.fl2va"]
                .requests
            )
            == 1
        )
        assert len(service.snapshot().runs) == 1

    asyncio.run(scenario())


def test_noop_write_leaves_no_record(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        service._mutate_run(  # noqa: SLF001
            run.id,
            lambda current, _document: replace(current, phase=RunPhase.CANCELLED, error_code=None),
        )
        first = await execute_command(
            service, envelope("playground.dismiss_run", {"run_id": run.id}, "dismiss-1"), HUMAN
        )
        assert first["receipt"]["status"] == "succeeded"
        records = len(service.snapshot().application_requests)

        second = await execute_command(
            service, envelope("playground.dismiss_run", {"run_id": run.id}, "dismiss-2"), HUMAN
        )
        assert second["receipt"]["status"] == "noop"
        assert len(service.snapshot().application_requests) == records

        same_note = await execute_command(
            service,
            envelope("playground.set_note", {"run_id": run.id, "note": None}, "note-1"),
            HUMAN,
        )
        assert same_note["receipt"]["status"] == "noop"
        assert len(service.snapshot().application_requests) == records

    asyncio.run(scenario())


def test_wait_runs_command_reports_terminal(playground_factory, monkeypatch) -> None:
    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_MAX_SECONDS", "2")
    monkeypatch.setenv("STORYRAIL_GENERATION_WAIT_POLL_SECONDS", "0.01")

    async def scenario() -> None:
        service, assets = build(playground_factory)
        from tests.playground_recipes import PlaygroundCapability

        service.registry.prepare_recipe(Capability.IMAGE_GENERATE).plugin.recipes[
            "codex_image.generate"
        ].provider.observations = [GenerationPhase.SUCCEEDED]
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        result = await execute_command(
            service, envelope("playground.wait_runs", {"run_ids": [run.id]}, "wait-1"), AGENT
        )
        assert result["receipt"]["status"] == "succeeded"
        assert result["data"]["all_terminal"] is True
        assert result["data"]["runs"][0]["phase"] == "succeeded"

    asyncio.run(scenario())


def test_get_runs_unknown_is_404(playground_factory) -> None:
    async def scenario() -> None:
        from core.playground.errors import RunNotFoundError

        service = playground_factory()
        with pytest.raises(RunNotFoundError):
            await execute_command(
                service, envelope("playground.get_runs", {"run_ids": ["f" * 32]}, "get-1"), HUMAN
            )

    asyncio.run(scenario())


def test_list_runs_pagination_and_filters(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        for index in range(3):
            await service.submit_run(
                PlaygroundCapability.IMAGE_GENERATE.value,
                {
                    "prompt": f"第{index}张",
                    "aspect_ratio": "16:9",
                    "reference_image_asset_ids": [],
                },
                note=None,
            )
        hidden = service.snapshot().runs[0]
        service._mutate_run(  # noqa: SLF001
            hidden.id,
            lambda current, _document: replace(
                current, phase=RunPhase.CANCELLED, dismissed=True, error_code=None
            ),
        )

        page = await execute_command(
            service,
            envelope(
                "playground.list_runs",
                {"limit": 2, "cursor": None, "capability": None, "include_dismissed": True},
                "list-1",
            ),
            HUMAN,
        )
        assert len(page["data"]["runs"]) == 2
        assert page["data"]["next_cursor"]

        rest = await execute_command(
            service,
            envelope(
                "playground.list_runs",
                {
                    "limit": 2,
                    "cursor": page["data"]["next_cursor"],
                    "capability": None,
                    "include_dismissed": True,
                },
                "list-2",
            ),
            HUMAN,
        )
        assert len(rest["data"]["runs"]) == 1
        assert rest["data"]["next_cursor"] is None

        visible = await execute_command(
            service,
            envelope(
                "playground.list_runs",
                {"limit": 10, "cursor": None, "capability": None, "include_dismissed": False},
                "list-3",
            ),
            HUMAN,
        )
        assert all(not run["dismissed"] for run in visible["data"]["runs"])
        assert len(visible["data"]["runs"]) == 2

        filtered = await execute_command(
            service,
            envelope(
                "playground.list_runs",
                {
                    "limit": 10,
                    "cursor": None,
                    "capability": "minimax_h3.fl2va",
                    "include_dismissed": True,
                },
                "list-4",
            ),
            HUMAN,
        )
        assert filtered["data"]["runs"] == []

        with pytest.raises(ValueError, match="cursor 不合法"):
            await execute_command(
                service,
                envelope(
                    "playground.list_runs",
                    {"limit": 10, "cursor": "!!!", "capability": None, "include_dismissed": True},
                    "list-5",
                ),
                HUMAN,
            )

    asyncio.run(scenario())


def test_list_assets_media_kind_filter(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        ingest(service, "image/png", PNG, label="图")
        ingest(service, "video/mp4", real_mp4_bytes(24, 2.0), label="视频", duration_seconds=2.0)
        result = await execute_command(
            service,
            envelope(
                "playground.list_assets",
                {"limit": 10, "cursor": None, "media_kind": "image"},
                "assets-1",
            ),
            HUMAN,
        )
        assert len(result["data"]["assets"]) == 1
        assert result["data"]["assets"][0]["media_type"] == "image/png"
        assert result["data"]["next_cursor"] is None

        videos = await execute_command(
            service,
            envelope(
                "playground.list_assets",
                {"limit": 10, "cursor": None, "media_kind": "video"},
                "assets-2",
            ),
            HUMAN,
        )
        assert len(videos["data"]["assets"]) == 1
        assert videos["data"]["assets"][0]["media_type"] == "video/mp4"

        everything = await execute_command(
            service,
            envelope(
                "playground.list_assets",
                {"limit": 10, "cursor": None, "media_kind": None},
                "assets-3",
            ),
            HUMAN,
        )
        assert len(everything["data"]["assets"]) == 2

    asyncio.run(scenario())


def test_set_note_write_records_receipt(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        before = service.snapshot().revision
        result = await execute_command(
            service,
            envelope("playground.set_note", {"run_id": run.id, "note": "对比组 A"}, "note-9"),
            HUMAN,
        )
        assert result["receipt"]["status"] == "succeeded"
        assert result["receipt"]["old_revision"] == before
        assert result["receipt"]["new_revision"] == before + 1
        assert result["data"]["run"]["note"] == "对比组 A"
        assert len(service.snapshot().application_requests) == 1

    asyncio.run(scenario())


def test_request_record_pruned_to_1000(playground_factory) -> None:
    async def scenario() -> None:
        service, assets = build(playground_factory)
        from tests.playground_recipes import PlaygroundCapability

        records = tuple(
            PlaygroundRequestRecord(
                request_id=f"{index:064x}",
                caller_id="agent-1",
                idempotency_key=f"key-{index}",
                request_digest=f"{index + 1:064x}",
                operation="playground.set_note",
                receipt_json=canonical_json({"receipt": {"status": "succeeded"}, "data": {}}),
                created_at=utc_timestamp(),
            )
            for index in range(1000)
        )
        service.store.commit(
            lambda previous: replace(
                previous, revision=previous.revision + 1, application_requests=records
            )
        )
        run = await service.submit_run(
            PlaygroundCapability.IMAGE_GENERATE.value,
            parameters_for(PlaygroundCapability.IMAGE_GENERATE, assets),
            note=None,
        )
        await execute_command(
            service,
            envelope("playground.set_note", {"run_id": run.id, "note": "新的备注"}, "note-new"),
            HUMAN,
        )
        stored = service.snapshot().application_requests
        assert len(stored) == 1000
        assert stored[-1].idempotency_key == "note-new"
        assert stored[0].idempotency_key == "key-1"

    asyncio.run(scenario())


def test_stage_request_checks_inside_commit(playground_factory) -> None:
    async def scenario() -> None:
        service = playground_factory()
        context = request_context(
            envelope("playground.set_note", {"run_id": "a" * 32, "note": None}, "k"), HUMAN
        )
        document = service.snapshot()
        updated = stage_request(
            document, context, build_receipt=lambda current: {"receipt": {}, "data": {}}
        )
        assert len(updated.application_requests) == 1
        with pytest.raises(ReplayedRequest):
            stage_request(
                updated, context, build_receipt=lambda current: {"receipt": {}, "data": {}}
            )

    asyncio.run(scenario())
