"""写入 revision 落后时按实体判定冲突：不相交就按当前文档执行，相交才 409 并列出冲突对象。"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from test_external_production import service, setup
from test_external_script_proposals import agent, http

from core.application.caller import Caller
from core.director_commands import DirectorCommand
from core.structured_director import change_journal
from core.structured_director.change_journal import PROJECT_KEY, RebaseScope, argument_ids


def delegated(document):
    return Caller(
        "local-agent",
        "agent",
        frozenset({document.project_id}),
        frozenset({"project.read", "project.mutate", "project.propose", "project.execute"}),
        4102444800,
        (),
        True,
    )


def touch_keyframe(store, keyframe_id, text):
    """模拟期间的人类写入：改另一个 Keyframe 的提示词。"""
    document = store.read()
    plan = document.keyframe_plan
    store._atomic_write(
        replace(
            document,
            revision=document.revision + 1,
            keyframe_plan=replace(
                plan,
                keyframes=tuple(
                    replace(item, prompt_text=text) if item.id == keyframe_id else item
                    for item in plan.keyframes
                ),
            ),
        )
    )


def edit_prompt(revision, keyframe_id, text, key="agent-edit"):
    return DirectorCommand(
        "keyframe.apply_operations",
        revision,
        key,
        {
            "operations": [
                {
                    "op": "update_frame_fields",
                    "keyframe_id": keyframe_id,
                    "fields": {"prompt_text": text},
                }
            ]
        },
    )


def keyframes(document):
    first, second = document.keyframe_plan.keyframes[:2]
    return first, second


def test_stale_write_on_disjoint_entities_runs_on_current_document(tmp_path):
    async def run():
        store, provider, document = await setup(tmp_path)
        mine, other = keyframes(document)
        stale = document.revision
        touch_keyframe(store, other.id, "人类刚改的另一帧")
        touch_keyframe(store, other.id, "人类又改了一次")
        command = edit_prompt(stale, mine.id, "Agent 写的这一帧")
        core = service(store, provider)
        result = await http(core, delegated(document), command)
        assert result.status == 200, result.body
        receipt = result.body["receipt"]
        assert receipt["rebased_from_revision"] == stale
        assert receipt["new_revision"] == stale + 3
        current = {item.id: item for item in store.read().keyframe_plan.keyframes}
        assert current[mine.id].prompt_text == "Agent 写的这一帧"
        assert current[other.id].prompt_text == "人类又改了一次"

        replay = await http(core, delegated(document), command)
        assert replay.status == 200 and replay.body["replay"] is True
        assert replay.body["receipt"] == receipt
        assert store.read().revision == stale + 3

    asyncio.run(run())


def test_stale_write_touching_a_changed_entity_is_rejected_with_locators(tmp_path):
    async def run():
        store, provider, document = await setup(tmp_path)
        mine, _ = keyframes(document)
        stale = document.revision
        touch_keyframe(store, mine.id, "人类先改了这一帧")
        before = store.path.read_bytes()
        result = await http(
            service(store, provider), delegated(document), edit_prompt(stale, mine.id, "Agent")
        )
        assert result.status == 409
        error = result.body["error"]
        assert error["code"] == "revision_conflict"
        assert error["conflict_reason"] == "entities_changed"
        assert error["expected_revision"] == stale
        assert error["current_revision"] == stale + 1
        (conflict,) = error["conflicts"]
        assert conflict["id"] == mine.id and conflict["kind"] == "keyframe"
        assert conflict["locator"].startswith("场景 1－片段 1")
        assert store.path.read_bytes() == before

    asyncio.run(run())


def test_project_level_changes_conflict_with_every_stale_write(tmp_path):
    async def run():
        store, provider, document = await setup(tmp_path)
        mine, _ = keyframes(document)
        stale = document.revision
        current = store.read()
        store._atomic_write(replace(current, revision=current.revision + 1, title="改了标题"))
        result = await http(
            service(store, provider), delegated(document), edit_prompt(stale, mine.id, "Agent")
        )
        assert result.status == 409
        assert [item["id"] for item in result.body["error"]["conflicts"]] == [PROJECT_KEY]

    asyncio.run(run())


def test_stale_write_without_journal_coverage_or_with_exact_grant_stays_strict(tmp_path):
    async def run():
        store, provider, document = await setup(tmp_path)
        mine, other = keyframe = keyframes(document)
        del keyframe
        stale = document.revision
        touch_keyframe(store, other.id, "另一帧")

        command = edit_prompt(stale, mine.id, "Agent", key="exact-grant")
        exact = await http(service(store, provider), agent(document, command), command)
        assert exact.status == 409
        assert exact.body["error"]["conflict_reason"] == "exact_grant"

        # Core 重启后日志从当前 revision 重新开始，无法覆盖更早的 revision。
        change_journal._JOURNALS.clear()
        touch_keyframe(store, other.id, "重启后的另一帧")
        command = edit_prompt(stale, mine.id, "Agent", key="after-restart")
        unavailable = await http(service(store, provider), delegated(document), command)
        assert unavailable.status == 409
        assert unavailable.body["error"]["conflict_reason"] == "journal_unavailable"
        assert unavailable.body["error"]["conflicts"] == []

    asyncio.run(run())


def test_actual_write_set_overlap_is_rejected(tmp_path):
    """参数没提到、但本次写入实际会改到的对象被他人改过时也冲突（例如级联失效）。"""

    async def run():
        store, _provider, document = await setup(tmp_path)
        mine, other = keyframes(document)
        stale = document.revision
        touch_keyframe(store, other.id, "他人改动")
        current = store.read()
        scope = RebaseScope(stale, stale, frozenset({mine.id}))
        assert store.accept_rebase(scope, current)
        cascaded = replace(
            current,
            keyframe_plan=replace(
                current.keyframe_plan,
                keyframes=tuple(
                    replace(item, prompt_text="级联改写") if item.id == other.id else item
                    for item in current.keyframe_plan.keyframes
                ),
            ),
        )
        assert store.concurrent_write_conflicts(scope, current, cascaded) == {other.id}
        assert scope.reason == "entities_changed"
        untouched = replace(
            current,
            keyframe_plan=replace(
                current.keyframe_plan,
                keyframes=tuple(
                    replace(item, prompt_text="只改自己") if item.id == mine.id else item
                    for item in current.keyframe_plan.keyframes
                ),
            ),
        )
        fresh = RebaseScope(stale, stale, frozenset({mine.id}))
        assert not store.concurrent_write_conflicts(fresh, current, untouched)

    asyncio.run(run())


def test_generation_rebases_on_unrelated_changes_and_rejects_changed_target(tmp_path):
    async def run():
        store, provider, document = await setup(tmp_path)
        segment = document.keyframe_plan.segments[0]
        target = segment.start_keyframe_id if segment.start_enabled else segment.end_keyframe_id
        other = next(item.id for item in document.keyframe_plan.keyframes if item.id != target)
        stale = document.revision
        touch_keyframe(store, other, "无关改动")
        command = DirectorCommand("keyframe.generate", stale, "gen", {"keyframe_id": target})
        result = await http(service(store, provider), delegated(document), command)
        assert result.status == 200, result.body
        assert result.body["receipt"]["rebased_from_revision"] == stale
        assert len(provider.requests) == 1

        stale = store.read().revision
        touch_keyframe(store, target, "人类改了目标帧")
        command = DirectorCommand("keyframe.generate", stale, "gen-2", {"keyframe_id": target})
        rejected = await http(service(store, provider), delegated(document), command)
        assert rejected.status == 409
        assert rejected.body["error"]["conflict_reason"] == "entities_changed"
        assert {item["id"] for item in rejected.body["error"]["conflicts"]} == {target}
        assert len(provider.requests) == 1

    asyncio.run(run())


def test_argument_ids_collects_nested_ids_only():
    first, second = "a" * 32, "b" * 32
    assert argument_ids(
        {
            "operations": [{"keyframe_id": first, "fields": {"reference_keyframe_ids": [second]}}],
            "prompt_text": "不是 ID",
            "count": 3,
        }
    ) == {first, second}
