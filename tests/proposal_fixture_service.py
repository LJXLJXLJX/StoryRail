"""测试数据构建器：确定性 proposal fixtures 经过 Core Store；不属于产品执行器。

保留媒体/领域回归的原始输入；真实外部授权、stdio/HTTP和恢复由test_external_*单独覆盖。
"""

from provider_factory import provider_registry

from core.director_proposals import KeyframeOperationsProposal
from core.structured_director import StructuredDirectorService as CoreService
from core.structured_director.planning_inputs import (
    keyframe_inputs,
    reference_characters,
)
from core.structured_director.script_proposals import begin, submit


class ProposalFixtureService(CoreService):
    def __init__(
        self,
        store,
        proposer=None,
        *,
        script_proposer=None,
        keyframe_planner=None,
        registry=None,
        **providers,
    ):
        self.reference_fixture = proposer
        self.script_fixture = script_proposer
        self.keyframe_fixture = keyframe_planner
        # Old test setup may specify unused doubles. They never execute or enter product Core.
        for name in (
            "director_router",
            "director_discussion_store",
            "h3_prompt_writer",
            "narration_reviewer",
            "director_session",
        ):
            providers.pop(name, None)
        if registry is None:
            registry = provider_registry(**providers)
        super().__init__(store, registry=registry)

    async def prepare_references(self):
        document, recovery = self._store.begin_reference_proposal()
        proposal = await self.reference_fixture.propose(
            director_plan_markdown=document.director_plan_markdown, restart_thread=recovery
        )
        return self._store.apply_reference_proposal(proposal)

    async def prepare_script(self, *, expected_revision):
        from test_external_script_proposals import confirm_references

        from core.structured_director.reads.workflow_state import references_reviewed

        if self._store.read().revision == expected_revision and not references_reviewed(
            self._store.read()
        ):
            await confirm_references(self._store, self)
            expected_revision = self._store.read().revision
        document, recovery = begin(self._store, expected_revision=expected_revision)
        proposal = await self.script_fixture.propose(
            director_plan_markdown=document.director_plan_markdown,
            characters=reference_characters(document),
            restart_thread=recovery,
        )
        return submit(
            self._store,
            proposal,
            request_id=document.active_director_run.id,
            expected_revision=document.revision,
        )

    async def prepare_keyframes(self, *, expected_revision, target_ids=(), user_message=""):
        document, recovery = self._store.begin_keyframe_plan(
            expected_revision=expected_revision, target_ids=target_ids, user_message=user_message
        )
        scenes, segments, boundaries = keyframe_inputs(document, target_ids, user_message)
        proposal = await self.keyframe_fixture.propose(
            scenes=scenes,
            aspect_ratio=document.aspect_ratio.value,
            user_message=user_message,
            required_shared_boundaries=boundaries,
            restart_thread=recovery,
        )
        method = (
            self._store.apply_keyframe_operation_plan
            if isinstance(proposal, KeyframeOperationsProposal)
            else self._store.apply_keyframe_plan
        )
        return method(proposal, target_segment_ids=segments, required_shared_boundaries=boundaries)
