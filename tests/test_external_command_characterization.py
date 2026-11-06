"""当前内部命令边界的刻画；这些缺口不是外部 API 应承诺的行为。"""

import asyncio
import json
from dataclasses import replace

import pytest
from test_director_commands import _script_shot_payload, _visual_project

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.director_commands.registry import director_command_id
from core.structured_director import StructuredDirectorStore
from core.structured_director.errors import RevisionConflictError


def test_replay_key_and_structural_retry_characterization(tmp_path):
    asyncio.run(_characterize(tmp_path))


async def _characterize(tmp_path):
    store, _, document, _ = await _visual_project(str(tmp_path))
    scene = document.director_script.scenes[0]
    registry = DirectorCommandRegistry(store)
    command = DirectorCommand(
        "script.apply_operations",
        document.revision,
        "same-key",
        {
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "update_shot_fields",
                    "shot_id": scene.shots[0].id,
                    "fields": {"action": "改变动作"},
                }
            ],
        },
    )
    first = registry.execute(command)
    before = store.path.read_bytes()
    with pytest.raises(RevisionConflictError):
        registry.execute(command)
    assert store.path.read_bytes() == before
    replay = registry.execute(replace(command, expected_revision=first.document.revision))
    assert replay.receipt.status == "noop"
    assert replay.receipt != first.receipt  # 目标态 noop，并非持久原始 receipt 回放。
    changed = replace(
        command,
        expected_revision=first.document.revision,
        arguments={
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "update_shot_fields",
                    "shot_id": scene.shots[0].id,
                    "fields": {"action": "同 key 不同动作"},
                }
            ],
        },
    )
    assert director_command_id(changed) != director_command_id(command)
    result = registry.execute(changed)
    assert result.receipt.status == "succeeded"  # 当前不拒绝 key 参数冲突。

    # 两个 caller 没有可传入的身份；独立 Registry 共享相同 ID 空间。
    other_caller = DirectorCommandRegistry(store)
    assert (
        other_caller.execute(
            replace(
                changed,
                expected_revision=result.document.revision,
            )
        ).receipt.command_id
        == result.receipt.command_id
    )
    # 复制的是隔离 fixture，以相同 entity IDs 检查 project 不参与命令摘要。
    (tmp_path / "other").mkdir()
    other = StructuredDirectorStore(tmp_path / "other", "b" * 32)
    other_document = json.loads(before)
    other_document["project_id"] = "b" * 32
    other_document["application_requests"] = []
    other_document["revision"] = document.revision
    other.path.write_text(json.dumps(other_document), encoding="utf-8")
    other_result = DirectorCommandRegistry(other).execute(command)
    assert other_result.receipt.command_id == first.receipt.command_id
    assert store.read() == result.document

    insert = DirectorCommand(
        "script.apply_operations",
        result.document.revision,
        "insert",
        {
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "insert_shot",
                    "scene_id": scene.id,
                    "after_shot_id": scene.shots[0].id,
                    "shot": _script_shot_payload(scene.shots[0].visible_character_ids[0], "插入"),
                    "attach_to_segment_id": next(
                        segment.id
                        for segment in scene.segments
                        if scene.shots[0].id in segment.shot_ids
                    ),
                }
            ],
        },
    )
    inserted = registry.execute(insert)
    with pytest.raises(RevisionConflictError):
        registry.execute(insert)
    with pytest.raises(ValueError, match="派生 ID"):
        registry.execute(replace(insert, expected_revision=inserted.document.revision))
    shot_id = inserted.document.director_script.scenes[0].shots[1].id
    delete = DirectorCommand(
        "script.apply_operations",
        inserted.document.revision,
        "delete",
        {
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "delete_shot",
                    "shot_id": shot_id,
                    "scene_id": scene.id,
                }
            ],
        },
    )
    deleted = registry.execute(delete)
    with pytest.raises(RevisionConflictError):
        registry.execute(delete)
    with pytest.raises(ValueError, match="Shot 不存在"):
        registry.execute(replace(delete, expected_revision=deleted.document.revision))
    assert store.read() == deleted.document
    assert len(deleted.document.director_script.scenes[0].shots) == 2
