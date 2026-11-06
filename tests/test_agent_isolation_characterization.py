"""只在临时目录刻画绕过风险，不宣称 OS 隔离已经部署。"""

import asyncio
import json
import os
import subprocess
import sys

import pytest
from test_director_commands import _visual_project

from core.director_commands import DirectorCommand, DirectorCommandRegistry
from core.structured_director import StructuredDirectorHttpApi, StructuredDirectorStore


def test_same_uid_readonly_file_can_be_replaced_through_writable_parent(tmp_path):
    protected = tmp_path / "service"
    protected.mkdir()
    state = protected / "project.json"
    state.write_text("original")
    state.chmod(0o400)
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "alias").symlink_to(protected, target_is_directory=True)
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import os; "
            "p=Path('alias/project.json'); "
            "assert p.read_text() == 'original'; "
            "q=p.parent/'replacement'; q.write_text('replaced'); os.replace(q,p)",
        ],
        cwd=agent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert state.read_text() == "replaced"


def test_store_alias_second_writer_and_http_have_no_caller_boundary(tmp_path):
    asyncio.run(_entry_points(tmp_path))


async def _entry_points(tmp_path):
    store, service, document, _ = await _visual_project(str(tmp_path))
    leaf_alias = tmp_path / "leaf"
    leaf_alias.symlink_to(store.path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="普通目录"):
        StructuredDirectorStore(leaf_alias, document.project_id)
    # leaf 拒绝 symlink 是路径卫生；父级别名仍能到同一项目。
    parent_alias = tmp_path / "parent"
    parent_alias.symlink_to(tmp_path, target_is_directory=True)
    second = StructuredDirectorStore(parent_alias / document.project_id, document.project_id)
    assert os.path.samefile(second.path, store.path)
    scene = document.director_script.scenes[0]
    command = DirectorCommand(
        "script.apply_operations",
        document.revision,
        "second-writer",
        {
            "scope": {"scene_ids": [scene.id]},
            "operations": [
                {
                    "op": "update_shot_fields",
                    "shot_id": scene.shots[0].id,
                    "fields": {"action": "第二个 Store 可写同一临时项目"},
                }
            ],
        },
    )
    result = DirectorCommandRegistry(second).execute(command)
    assert store.read() == result.document
    api = StructuredDirectorHttpApi(service, resource_path="/api/projects/" + document.project_id)
    response = await api.handle(
        "POST",
        f"{api.resource_path}/commands",
        json.dumps(
            {
                "name": command.name,
                "expected_revision": result.document.revision,
                "idempotency_key": "http-without-caller",
                "arguments": {
                    "scope": {"scene_ids": [scene.id]},
                    "operations": [
                        {
                            "op": "update_shot_fields",
                            "shot_id": scene.shots[0].id,
                            "fields": {"action": "旧 HTTP 入口没有 caller 身份参数"},
                        }
                    ],
                },
            }
        ).encode(),
    )
    assert response.status == 200
    assert (
        store.read().director_script.scenes[0].shots[0].action == "旧 HTTP 入口没有 caller 身份参数"
    )
