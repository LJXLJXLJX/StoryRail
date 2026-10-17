"""IndexTTS2.5 私有部署的封闭输入、语言与 63 位 seed。"""

from __future__ import annotations

import base64
import json
import threading

import pytest

from default_model_providers_implement.indextts2_worker import _MODEL_FILES, IndexTTS2Runtime, load
from default_model_providers_implement.request_builders import prepare_indextts2
from default_model_providers_implement.resource_manager import RunResult
from default_model_providers_implement.task_store import TaskRecord


def payload(wav_bytes):
    return {
        "content": "部署验证",
        "voice_sample": {"type": "audio/wav", "encoded": base64.b64encode(wav_bytes).decode()},
        "randomness": 2**63 - 1,
        "pace": 1.2,
        "emotion": [0.1] * 8,
        "language": "en",
    }


def test_builder_and_worker_keep_closed_paths_and_semantics(tmp_path, wav_bytes):
    model = tmp_path / "model"
    model.mkdir()
    for name in _MODEL_FILES:
        (model / name).write_bytes(b"fixture")
    record = TaskRecord("a" * 32, "indextts2", "queued", 0, "", str(tmp_path))
    prepare_indextts2(payload(wav_bytes))(record)
    request_file = tmp_path / "request.json"
    request = load(request_file, model)
    assert request["seed"] == 2**63 - 1 and request["language"] == "en"
    assert request["voice"].read_bytes() == wav_bytes
    assert request["duration_factor"] == 1.2 and request["emotion_vector"] == [0.1] * 8
    prepare_indextts2({k: v for k, v in payload(wav_bytes).items() if k != "language"})(record)
    assert load(request_file, model)["language"] == "auto"
    bad = json.loads(request_file.read_bytes())
    bad["voice_file"] = "../outside.wav"
    request_file.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="voice_file"):
        load(request_file, model)
    for changes in ({"pace": True}, {"emotion": [0] * 7}, {"language": "ja"}, {"shell": "cmd"}):
        with pytest.raises(ValueError):
            prepare_indextts2({**payload(wav_bytes), **changes})


@pytest.mark.parametrize("language,model_language", [("en", "en"), ("zh", "zh"), ("auto", "zhen")])
def test_large_seed_and_language_reach_inference(tmp_path, wav_bytes, language, model_language):
    numpy_seeds, torch_seeds, calls = [], [], []

    class Random:
        def seed(self, value):
            assert 0 <= value < 2**32
            numpy_seeds.append(value)

    class Numpy:
        random = Random()

    class Cuda:
        def is_available(self):
            return False

    class Torch:
        cuda = Cuda()

        def manual_seed(self, value):
            torch_seeds.append(value)

    class Tts:
        gr_progress = None

        def normalize_emo_vec(self, values, *, apply_bias):
            assert apply_bias is True
            return values

        def infer(self, **kwargs):
            calls.append(kwargs)
            (tmp_path / "output.wav").write_bytes(wav_bytes)
            return str(tmp_path / "output.wav")

    runtime = IndexTTS2Runtime.__new__(IndexTTS2Runtime)
    runtime._numpy, runtime._torch, runtime._tts = Numpy(), Torch(), Tts()
    runtime.run(
        {
            "seed": 2**63 - 1,
            "text": "The train arrives.",
            "voice": tmp_path / "voice.wav",
            "task_dir": tmp_path,
            "emotion_vector": [0.2] * 8,
            "duration_factor": 0.9,
            "language": language,
        }
    )
    assert numpy_seeds == [2**32 - 1] and torch_seeds == [2**63 - 1]
    assert calls[0]["lang"] == model_language and calls[0]["duration_factor"] == 0.9
    assert calls[0]["emo_vector"] == [0.2] * 8
    assert runtime._tts.gr_progress is None


def test_real_http_routes_normalize_and_recover_artifact(tmp_path, wav_bytes):
    from core.model_providers.boundary import GenerationPhase
    from core.model_providers.http import UrllibTransport
    from core.model_providers.indextts2.provider import (
        IndexTTS2Provider,
        IndexTTS2Request,
        VoiceReference,
    )
    from default_model_providers_implement.server import ModelApiServer

    server = ModelApiServer(("127.0.0.1", 0), tmp_path, enabled_services={"indextts2"})

    def runner(record, cancel, progress):
        request = json.loads((tmp_path / "tasks" / record.task_id / "request.json").read_bytes())
        assert request["language"] == "en" and request["seed"] == 2**63 - 1
        output = tmp_path / "tasks" / record.task_id / "output.wav"
        output.write_bytes(wav_bytes)
        return RunResult(output, "audio/wav")

    # Replace only the private GPU runner; exercise the actual HTTP and artifact paths.
    server.manager.managers[0]._runners["indextts2"] = runner
    server.manager.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    provider = IndexTTS2Provider(f"http://{host}:{port}", UrllibTransport())
    try:
        handle = provider.submit(
            IndexTTS2Request(
                "English narration",
                VoiceReference("audio/wav", wav_bytes),
                seed=2**63 - 1,
                language="en",
            )
        )
        from time import monotonic, sleep

        deadline = monotonic() + 5
        observed = provider.observe(handle)
        while observed.phase in (GenerationPhase.QUEUED, GenerationPhase.RUNNING):
            assert monotonic() < deadline
            sleep(0.01)
            observed = provider.observe(handle)
        assert observed.phase is GenerationPhase.SUCCEEDED
        assert provider.read_artifact(handle, observed.artifact.artifact_id) == wav_bytes
        assert provider.cancel(handle).phase is GenerationPhase.SUCCEEDED
    finally:
        server.shutdown()
        server.manager.shutdown()
        server.server_close()
        thread.join(5)


def test_asset_audio_role_language_defaults_without_project_context(tmp_path, wav_bytes):
    from core.model_providers.indextts2.plugin import plugin_instance
    from core.model_providers.manifest import Capability, Role
    from core.model_providers.recipe import MediaInput
    from core.model_providers.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.install(plugin_instance("http://models"))
    prepared = registry.prepare_recipe(Capability.SPEECH_SYNTHESIZE)
    request, _ = prepared.request(
        roles={Role.SPEECH_TEXT: "English and 中文", Role.SEED: 42},
        media={Role.VOICE_REFERENCE: (MediaInput("audio/wav", wav_bytes),)},
    )
    assert request.param("language") == "auto"
    english, _ = prepared.request(
        roles={Role.SPEECH_TEXT: "English narration", Role.SEED: 42, Role.LANGUAGE: "en"},
        media={Role.VOICE_REFERENCE: (MediaInput("audio/wav", wav_bytes),)},
    )
    assert english.param("language") == "en"
