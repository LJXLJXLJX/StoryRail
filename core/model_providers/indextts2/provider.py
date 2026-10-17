from __future__ import annotations

import base64
from dataclasses import dataclass
from math import isfinite
from urllib.parse import quote

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success
from core.model_providers.recipe import RecipeRequest


@dataclass(frozen=True, slots=True)
class VoiceReference:
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type not in {
            "audio/wav",
            "audio/mpeg",
            "audio/flac",
            "audio/mp4",
            "audio/ogg",
        }:
            raise ValueError("参考音频类型不受支持。")
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("参考音频大小不合法。")


@dataclass(frozen=True, slots=True)
class IndexTTS2Request:
    text: str
    voice: VoiceReference
    seed: int = 42
    duration_factor: float = 1.0
    emotion_vector: tuple[float, ...] = (0.0,) * 8
    language: str = "auto"

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip() or len(self.text) > 20_000:
            raise ValueError("text 必须是 1 到 20000 字符。")
        if (
            type(self.seed) is not int
            or not 0 <= self.seed <= 2**63 - 1
            or isinstance(self.duration_factor, bool)
            or not isinstance(self.duration_factor, (int, float))
            or not isfinite(self.duration_factor)
            or not 0.5 <= self.duration_factor <= 2.0
        ):
            raise ValueError("TTS 参数不合法。")
        if (
            not isinstance(self.emotion_vector, (tuple, list))
            or len(self.emotion_vector) != 8
            or any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not isfinite(item)
                or not -1 <= item <= 1
                for item in self.emotion_vector
            )
        ):
            raise ValueError("emotion_vector 必须包含 8 个 -1 到 1 的数字。")
        if not isinstance(self.language, str) or self.language not in {"auto", "zh", "en"}:
            raise ValueError("language 必须是 auto、zh 或 en。")
        object.__setattr__(self, "emotion_vector", tuple(self.emotion_vector))


def to_request(contract: RecipeRequest) -> IndexTTS2Request:
    voice = contract.slot("voice")[0]
    return IndexTTS2Request(
        str(contract.param("text")),
        VoiceReference(voice.media_type, voice.content),
        int(contract.param("seed")),
        float(contract.param("duration_factor")),
        tuple(contract.param("emotion_vector")),
        str(contract.param("language")),
    )


class IndexTTS2Provider:
    plugin_id = "indextts2.synthesize"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        if request.recipe_id != "indextts2.synthesize":
            raise ValueError("未知 IndexTTS2.5 recipe。")
        return self.submit(to_request(request))

    def submit(self, request: RecipeRequest | IndexTTS2Request) -> ProviderHandle:
        if not isinstance(request, IndexTTS2Request):
            request = to_request(request)
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/indextts2/speech",
                json_body={
                    "content": request.text,
                    "voice_sample": {
                        "type": request.voice.media_type,
                        "encoded": base64.b64encode(request.voice.content).decode("ascii"),
                    },
                    "randomness": request.seed,
                    "pace": request.duration_factor,
                    "emotion": list(request.emotion_vector),
                    "language": request.language,
                },
            ),
            {202},
        )
        require_keys(data, required={"speech_id"})
        speech_id = data["speech_id"]
        if not isinstance(speech_id, str) or not 1 <= len(speech_id) <= 2000:
            raise ModelProviderError("invalid_response", "IndexTTS2 speech_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, speech_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        speech_id = self._id(handle)
        data = require_success(
            self._http.request(
                "GET", f"{self._endpoint}/indextts2/speech/{quote(speech_id, safe='')}"
            ),
            {200},
        )
        require_keys(
            data,
            required={"condition", "progress_fraction", "status_text"},
            optional={"audio_file", "reason"},
        )
        condition = data["condition"]
        progress = data["progress_fraction"]
        message = data["status_text"]
        reason = data.get("reason")
        if (
            not isinstance(condition, str)
            or isinstance(progress, bool)
            or not isinstance(progress, (int, float))
            or not isfinite(progress)
            or not 0 <= progress <= 1
            or not isinstance(message, str)
            or (reason is not None and not isinstance(reason, str))
        ):
            raise ModelProviderError("invalid_response", "IndexTTS2 任务状态不合法。")
        phase = {
            "waiting_for_gpu": GenerationPhase.QUEUED,
            "speaking": GenerationPhase.RUNNING,
            "available": GenerationPhase.SUCCEEDED,
            "fault": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(condition)
        if phase is None:
            raise ModelProviderError("invalid_response", "IndexTTS2 condition 不合法。")
        artifact = _audio(data.get("audio_file")) if phase is GenerationPhase.SUCCEEDED else None
        error_code = (reason or "indextts2_failed") if phase is GenerationPhase.FAILED else None
        return GenerationObservation(
            phase,
            float(progress),
            message,
            artifact,
            error_code,
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        speech_id = self._id(handle)
        require_success(
            self._http.request(
                "PATCH",
                f"{self._endpoint}/indextts2/speech/{quote(speech_id, safe='')}",
                json_body={"cancel": True},
            ),
            {202, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        speech_id = self._id(handle)
        escaped_artifact = quote(artifact_id, safe="")
        response = self._http.request(
            "GET",
            f"{self._endpoint}/indextts2/speech/{quote(speech_id, safe='')}"
            f"/audio/{escaped_artifact}",
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "IndexTTS2 音频不可用。")
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 IndexTTS2 插件。")
        if not isinstance(handle.external_id, str) or not 1 <= len(handle.external_id) <= 2000:
            raise ModelProviderError("invalid_handle", "IndexTTS2 任务 ID 不合法。")
        return handle.external_id


def _audio(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "IndexTTS2 完成响应缺少 audio_file。")
    require_keys(value, required={"name", "format", "bytes", "hash"})
    if (
        not isinstance(value["name"], str)
        or not value["name"]
        or value["format"] != "audio/wav"
        or type(value["bytes"]) is not int
        or value["bytes"] <= 0
        or not isinstance(value["hash"], str)
        or len(value["hash"]) != 64
        or any(char not in "0123456789abcdef" for char in value["hash"])
    ):
        raise ModelProviderError("invalid_response", "IndexTTS2 音频描述不合法。")
    return ArtifactDescriptor(value["name"], value["format"], value["bytes"], value["hash"])
