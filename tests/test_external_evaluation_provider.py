"""R08 合成 Provider 的持久句柄/失败证据；不调用真实媒体或模型。"""

import hashlib
import io
import json
import wave
from types import SimpleNamespace

import pytest

from core.model_providers.boundary import GenerationPhase, ModelProviderError
from scripts.harness.real_agent.external_core import SyntheticProvider


def test_synthetic_audio_survives_provider_restart_and_cancel_failure(tmp_path):
    provider = SyntheticProvider(tmp_path, "audio")
    handle = provider.submit(SimpleNamespace())
    restored = SyntheticProvider(tmp_path, "audio")
    (restored.root / "next-fault.txt").write_text("cancel_fail")
    with pytest.raises(ModelProviderError, match="取消"):
        restored.cancel(handle)
    assert (
        json.loads((restored.root / (handle.external_id + ".json")).read_text())["phase"]
        == "queued"
    )
    observed = restored.observe(handle)
    data = restored.read_artifact(handle, observed.artifact.artifact_id)
    assert observed.artifact.sha256 == hashlib.sha256(data).hexdigest()
    with wave.open(io.BytesIO(data)) as audio:
        assert audio.getnframes() / audio.getframerate() == observed.artifact.duration_seconds == 8
    assert restored.cancel(handle).phase == GenerationPhase.CANCELLED
    assert SyntheticProvider(tmp_path, "audio").observe(handle).phase == GenerationPhase.CANCELLED


def test_unknown_submission_keeps_external_job_without_returning_handle(tmp_path):
    provider = SyntheticProvider(tmp_path, "image")
    (provider.root / "next-fault.txt").write_text("submit_unknown")
    with pytest.raises(ModelProviderError, match="响应丢失"):
        provider.submit(SimpleNamespace())
    jobs = list(provider.root.glob("*.json"))
    assert len(jobs) == 1
    assert json.loads(jobs[0].read_text())["phase"] == "queued"
    assert not (provider.root / "next-fault.txt").exists()
