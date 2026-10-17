from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.model_providers.boundary import ModelProviderError
from core.model_providers.recipe import RecipeRequest


@dataclass(frozen=True, slots=True)
class WhisperASRRequest:
    audio: bytes
    media_type: str
    language: str = "auto"

    def __post_init__(self) -> None:
        if self.media_type != "audio/wav":
            raise ValueError("Whisper ASR 当前只接受 WAV Reference Voice。")
        if (
            not 44 <= len(self.audio) <= 64 * 1024 * 1024
            or self.audio[:4] != b"RIFF"
            or self.audio[8:12] != b"WAVE"
        ):
            raise ValueError("Whisper ASR 输入必须是真实 WAV 音频。")
        if self.language not in {"auto", "zh", "en"}:
            raise ValueError("Whisper ASR language 只允许 auto、zh 或 en。")


@dataclass(frozen=True, slots=True)
class WhisperASRResult:
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > 20_000:
            raise ValueError("Whisper ASR 没有返回有效文字。")


def to_request(contract: RecipeRequest) -> WhisperASRRequest:
    audio = contract.slot("audio")[0]
    return WhisperASRRequest(audio.content, audio.media_type, str(contract.param("language")))


class WhisperASRProvider:
    """Synchronous adapter for the local whisper.cpp HTTP server."""

    plugin_id = "whisper.cpp.asr"
    plugin_version = 1

    def execute_recipe(self, request: RecipeRequest) -> WhisperASRResult:
        return self.transcribe(to_request(request))

    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint.rstrip("/")

    def transcribe(self, request: RecipeRequest | WhisperASRRequest) -> WhisperASRResult:
        if not isinstance(request, WhisperASRRequest):
            request = to_request(request)
        body, content_type = _multipart_body(request)
        http_request = Request(
            f"{self._endpoint}/inference",
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=600.0) as response:
                status = response.status
                content = response.read()
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            finally:
                exc.close()
            raise ModelProviderError(
                "external_error",
                f"Whisper ASR 返回 HTTP {exc.code}：{detail}",
                retryable=exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ModelProviderError(
                "transport_error", f"Whisper ASR 服务不可用：{exc}", retryable=True
            ) from exc
        if status != 200:
            raise ModelProviderError(
                "external_error", f"Whisper ASR 返回 HTTP {status}。", retryable=status >= 500
            )
        try:
            value = json.loads(content)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ModelProviderError(
                "invalid_response", "Whisper ASR 返回的 JSON 不合法。"
            ) from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"text"}
            or not isinstance(value["text"], str)
        ):
            raise ModelProviderError("invalid_response", "Whisper ASR 返回字段不合法。")
        try:
            return WhisperASRResult(value["text"].strip())
        except ValueError as exc:
            raise ModelProviderError("invalid_response", str(exc)) from exc


def _multipart_body(request: WhisperASRRequest) -> tuple[bytes, str]:
    boundary = "----StoryRailWhisper" + uuid.uuid4().hex
    chunks: list[bytes] = []

    def field(name: str, value: str) -> None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="reference.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            request.audio,
            b"\r\n",
        ]
    )
    field("response_format", "json")
    field("language", request.language)
    field("translate", "false")
    field("no_timestamps", "true")
    field("temperature", "0.0")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
