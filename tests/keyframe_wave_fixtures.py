import tempfile
from dataclasses import replace
from pathlib import Path

from proposal_fixture_service import ProposalFixtureService as StructuredDirectorService
from structured_director_fixtures import (
    RecordingProposer,
    RecordingProvider,
    RecordingScriptProposer,
    create_project,
)

from core.director_proposals import (
    KeyframePlanProposal,
    KeyframeSegmentProposal,
    KeyframeShotProposal,
)
from core.structured_director import StructuredDirectorStore


class FiveShotScript(RecordingScriptProposer):
    async def propose(self, **kwargs):
        base = await super().propose(**kwargs)
        scene = base.scenes[0]
        shot = scene.shots[0]
        shot = replace(
            shot,
            segments=(
                replace(
                    shot.segments[0],
                    duration_estimate_seconds=2,
                    dialogue_lines=(),
                ),
            ),
        )
        scene = replace(scene, shots=(shot,) * 5)
        return replace(base, scenes=(scene, replace(scene, title="不能扩大的另一场")))


class FiveShotPlan:
    async def propose(self, **kwargs):
        return KeyframePlanProposal(
            tuple(
                KeyframeShotProposal(
                    shot_id=shot.id,
                    continues_from_previous_shot=index in (2, 4),
                    start_prompt_text=f"时刻 {index}"
                    if index not in (2, 4)
                    else f"结束 {index - 1}",
                    start_visible_character_ids=(),
                    segments=(
                        KeyframeSegmentProposal(
                            shot.segments[0].id,
                            "start" if index == 0 else "both",
                            f"结束 {index}",
                            (),
                        ),
                    ),
                )
                for scene in kwargs["scenes"]
                for index, shot in enumerate(scene.shots)
            )
        )


class KeyframeWaveFixture:
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / ("a" * 32)
        self.path.mkdir()
        self.store = StructuredDirectorStore(self.path, self.path.name)
        self.provider = RecordingProvider(media_type="image/png", content=b"\x89PNG\r\n\x1a\nframe")
        self.service = StructuredDirectorService(
            self.store,
            RecordingProposer(),
            script_proposer=FiveShotScript(),
            keyframe_planner=FiveShotPlan(),
            image_provider=self.provider,
        )
        create_project(self.store)
        document = await self.service.prepare_references()
        document = await self.service.prepare_script(expected_revision=document.revision)
        document = await self.service.confirm_script(expected_revision=document.revision)
        document = document
        document = await self.service.unlock_visual_production(expected_revision=document.revision)
        document = await self.service.prepare_keyframes(expected_revision=document.revision)
        self.scene, self.other = document.director_script.scenes
        bindings = {item.segment_id: item for item in document.keyframe_plan.segments}
        self.bindings = [bindings[shot.segments[0].id] for shot in self.scene.shots]
