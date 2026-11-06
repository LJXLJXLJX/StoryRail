from __future__ import annotations

import asyncio
from dataclasses import replace

from test_director_commands import _visual_project


def test_director_plan_edit_preserves_existing_structured_content(tmp_path) -> None:
    async def scenario() -> None:
        _store, service, before, _route = await _visual_project(str(tmp_path))
        updated = await service.update_director_plan(
            "# 补全方案\n\n增加结尾，但不自动改写现有结构化内容。",
            expected_revision=before.revision,
        )

        assert updated.revision == before.revision + 1
        assert updated.director_plan_markdown.endswith("不自动改写现有结构化内容。")
        assert (
            replace(
                updated,
                revision=before.revision,
                director_plan_markdown=before.director_plan_markdown,
            )
            == before
        )

        noop = await service.update_director_plan(
            updated.director_plan_markdown,
            expected_revision=updated.revision,
        )
        assert noop == updated

    asyncio.run(scenario())
