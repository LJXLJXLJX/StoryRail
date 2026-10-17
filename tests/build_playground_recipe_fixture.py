"""从真实插件目录生成 Web Playground 契约与标签预览 fixture。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.model_providers.breeze_tts2.plugin import plugin_instance as speech
from core.model_providers.codex_image.plugin import plugin_instance as images
from core.model_providers.demucs_audio.plugin import plugin_instance as separation
from core.model_providers.manifest import Capability
from core.model_providers.minimax_h3.plugin import plugin_instance as video
from core.model_providers.registry import ProviderRegistry
from core.model_providers.seedvr2_7b_sharp_fp8.plugin import plugin_instance as upscale
from core.model_providers.stable_audio_3.plugin import plugin_instance as audio
from core.model_providers.whisper_asr.plugin import plugin_instance as asr
from core.playground.parameters import recipe_input_labels
from core.playground.projection import capability_descriptors
from core.playground.service import PlaygroundService
from core.playground.store import PlaygroundStore
from tests.test_playground_recipe_catalog import MANIFEST as SAMPLE_MANIFEST


def build_fixture():
    with tempfile.TemporaryDirectory() as root:
        registry = ProviderRegistry()
        endpoint = "http://fixture.invalid"
        for factory in (images, video, upscale, separation, audio, asr):
            registry.install(factory(endpoint))
        registry.install(speech(endpoint, Path(root) / "speech"))
        service = PlaygroundService(PlaygroundStore(Path(root) / "playground"), registry)
        recipe = registry.recipe_definition(Capability.VIDEO_GENERATE, "minimax_h3.ref2va")[1]
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
