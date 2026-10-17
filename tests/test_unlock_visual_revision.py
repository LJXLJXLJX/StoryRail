"""确认 unlock_visual_production 不会自行消化过期 revision。"""

import asyncio

import pytest
from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import RecordingProposer, TwoSceneScriptProposer, create_project

from core.structured_director import StructuredDirectorStore
from core.structured_director.errors import RevisionConflictError


def test_stale_unlock_still_conflicts_after_visual_layers_are_open(tmp_path) -> None:
    asyncio.run(_stale_unlock_still_conflicts(tmp_path))


async def _stale_unlock_still_conflicts(tmp_path) -> None:
    store = StructuredDirectorStore(tmp_path, "b" * 32)
    service = StructuredDirectorService(
        store,
        RecordingProposer(),
        script_proposer=TwoSceneScriptProposer(),
    )
    create_project(store)
    document = await service.prepare_references()
    document = await service.prepare_script(expected_revision=document.revision)
    document = await service.confirm_script(expected_revision=document.revision)
    stale = document.revision
    updated = await service.unlock_visual_production(expected_revision=stale)
    assert updated.workspace_layers.keyframes_unlocked
    assert updated.workspace_layers.videos_unlocked
    with pytest.raises(RevisionConflictError):
        await service.unlock_visual_production(expected_revision=stale)
