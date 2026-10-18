"""真实调用前验收T11固定样本的Core装配，绝不调用模型。"""

import asyncio
import base64
from pathlib import Path

import pytest

from core.director_proposals import CharacterCardProposal, ReferenceLibraryProposal
from core.project_settings import ProjectAspectRatio
from core.structured_director import StructuredDirectorStore
from core.structured_director.models import NarrationLanguage
from scripts.harness.real_agent.prompt_fixture import prepare


@pytest.mark.parametrize("kind", ["keyframe", "fl2va", "ref2va"])
def test_prompt_fixture_before_real_calls(tmp_path, kind):
    async def run():
        p = tmp_path / ("a" * 32)
        p.mkdir()
        store = StructuredDirectorStore(p, "a" * 32)
        store.create_project(
            title="fixture",
            aspect_ratio=ProjectAspectRatio.LANDSCAPE,
            director_plan_markdown="甲递杯，乙接稳。",
            narration_languages=tuple(NarrationLanguage),
        )
        store.begin_reference_proposal()
        store.apply_reference_proposal(
            ReferenceLibraryProposal(
                (
                    CharacterCardProposal("甲", "蓝色外套", "自然"),
                    CharacterCardProposal("乙", "红色外套", "自然"),
                )
            )
        )
        folder = Path(__file__).parent / "fixtures/prompt_contracts/media"
        result = await prepare(
            store,
            {
                "prompt_fixture": kind,
                "images": {
                    p.name: base64.b64encode(p.read_bytes()).decode() for p in folder.glob("*.png")
                },
                "audios": {
                    p.name: base64.b64encode(p.read_bytes()).decode() for p in folder.glob("*.wav")
                },
            },
        )
        # 只有 fixture 登记的视图候选，没有任何真实 Provider 调用。
        assert {item.plugin_id for item in store.read().generations} <= {
            "fixture.image",
            "fixture.audio",
        }
        if kind == "keyframe":
            assert result["workset"]["operation"] == "edit"
            assert len(result["reference_images"]) == 5
        else:
            assert result["context"]["mode"] == kind
            assert len(result["context"]["dialogue"]) == (2 if kind == "ref2va" else 0)

    asyncio.run(run())
