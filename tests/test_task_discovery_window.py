"""read_workflow 的任务发现默认只带全部进行中任务与最近几条已结束任务，更早历史按需分页。"""

from __future__ import annotations

from test_generation_mutations import _document
from test_models_validation import make_generation

from core.structured_director.models import (
    GenerationOperation,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)
from core.structured_director.reads.execution_reads import _task_discovery


def _generation(index, phase):
    return make_generation(
        ReferenceGenerationKind.KEYFRAME_IMAGE,
        GenerationOperation.GENERATE,
        id=f"{index:032x}",
        target_id=f"{index + 100:032x}",
        phase=phase,
        error_code="provider_failed" if phase is ReferenceGenerationPhase.FAILED else None,
    )


def _document_with_history(active, finished):
    generations = (
        *(_generation(index, ReferenceGenerationPhase.FAILED) for index in range(1, finished + 1)),
        *(
            _generation(index, ReferenceGenerationPhase.QUEUED)
            for index in range(finished + 1, finished + active + 1)
        ),
    )
    return _document(generations=generations)


def test_default_page_lists_all_active_and_five_latest_finished():
    data = _task_discovery(_document_with_history(active=3, finished=12), {})
    assert data["active_count"] == 3
    assert data["recent_count"] == 12
    assert len(data["active"]) == 3
    # 已结束任务按创建倒序，只带最近 5 条。
    assert [item["id"] for item in data["recent"]] == [
        f"{index:032x}" for index in range(12, 7, -1)
    ]
    older = _task_discovery(
        _document_with_history(active=3, finished=12), {"cursor": data["next_cursor"]}
    )
    assert [item["id"] for item in older["recent"]][0] == f"{7:032x}"


def test_explicit_limit_overrides_default_window():
    data = _task_discovery(_document_with_history(active=1, finished=12), {"limit": 13})
    assert len(data["active"]) == 1
    assert len(data["recent"]) == 12
    assert data["next_cursor"] is None
