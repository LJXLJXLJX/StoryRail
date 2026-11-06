"""从示例插件目录生成 Web Playground 契约与标签预览 fixture。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from provider_factory import sample_plugin  # noqa: E402
from sample_plugins import MANIFESTS  # noqa: E402

from core.model_providers.manifest import Capability
from core.model_providers.registry import ProviderRegistry
from core.playground.parameters import recipe_input_labels
from core.playground.projection import capability_descriptors
from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from tests.test_playground_recipe_catalog import MANIFEST as SAMPLE_MANIFEST


class _Unused:
    """只用于生成目录；fixture 不提交任务。"""

    def submit(self, request):
        raise AssertionError

    def transcribe(self, request):
        raise AssertionError

    def observe(self, handle):
        raise AssertionError

    def cancel(self, handle):
        raise AssertionError

    def read_artifact(self, handle, artifact_id):
        raise AssertionError


def build_fixture():
    with tempfile.TemporaryDirectory() as root:
        registry = ProviderRegistry()
        for manifest in (MANIFESTS[2], MANIFESTS[1], *MANIFESTS[3:], MANIFESTS[0]):
            registry.install(
                sample_plugin(manifest, {recipe.id: _Unused() for recipe in manifest.recipes})
            )
        service = PlaygroundService(PlaygroundStore(Path(root) / "playground"), registry)
        recipe = registry.recipe_definition(Capability.VIDEO_GENERATE, "sample_video.ref2va")[1]
        parameters = {
            "first_frame_asset_id": "1" * 32,
            "last_frame_asset_id": None,
            "additional_images": [{"asset_id": "2" * 32, "description": ""}],
            "reference_audios": [{"asset_id": "3" * 32, "description": ""}],
            "reference_videos": [],
        }
        return {
            "capabilities": capability_descriptors(service, include_schema=False),
            "sample_recipe": SAMPLE_MANIFEST.recipes[0].to_json(),
            "reference_preview": {
                "ready": False,
                "reason": "参考输入必须填写说明。",
                "input_labels": recipe_input_labels(recipe, parameters, draft=True),
            },
        }


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(json.dumps(build_fixture(), ensure_ascii=False, indent=2) + "\n")
