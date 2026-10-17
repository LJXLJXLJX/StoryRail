"""媒体提交的共用提交收尾。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from core.model_providers.boundary import ProviderHandle

from ..generation_lifecycle import _link_generation_retry, _submission_failure
from ..models import ReferenceGeneration, ReferenceGenerationPhase, transition_generation

_ASSEMBLY_TRANSITION_SECONDS = 0.1


async def _commit_submission(
    owner,
    document,
    generation: ReferenceGeneration,
    *,
    expected_revision: int,
    submit: Callable[[], ProviderHandle],
    capability: str,
    queued_message: str,
    retry_of: ReferenceGeneration | None,
) -> object:
    generation = _link_generation_retry(document, generation, retry_of)
    owner._store.create_generation(generation, expected_revision=expected_revision)
    try:
        handle = await asyncio.to_thread(submit)
    except Exception as exc:
        return owner._store.update_generation(
            _submission_failure(generation, exc, capability=capability)
        )
    queued = transition_generation(
        generation,
        ReferenceGenerationPhase.QUEUED,
        message=queued_message,
        plugin_id=handle.plugin_id,
        plugin_version=handle.plugin_version,
        external_id=handle.external_id,
    )
    return owner._store.update_generation(queued)
