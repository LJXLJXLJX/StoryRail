from __future__ import annotations

import base64
import hashlib
import json
import uuid
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
class BreezeVoiceReference:
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
            raise ValueError("Breeze 参考音频类型不受支持。")
        if not self.content or len(self.content) > 64 * 1024 * 1024:
            raise ValueError("Breeze 参考音频大小不合法。")


@dataclass(frozen=True, slots=True)
class BreezeTTS2Request:
    text: str
    instruction: str | None = None
    voice: BreezeVoiceReference | None = None
    reference_transcript: str | None = None
    cfg_scale: float = 4.0
    seed: int = 42

    @property
    def is_voice_design(self) -> bool:
        return self.voice is None

    def __post_init__(self) -> None:
        if not self.text.strip() or len(self.text) > 20_000:
            raise ValueError("Breeze text 必须是 1 到 20000 字符。")
        if self.instruction is not None and not 0 < len(self.instruction.strip()) <= 4_000:
            raise ValueError("Breeze instruction 必须是 1 到 4000 字符。")
        if self.voice is None:
            if self.reference_transcript is not None:
                raise ValueError("Voice Design 不能包含 reference transcript。")
        elif not self.reference_transcript or not self.reference_transcript.strip():
            raise ValueError("Breeze Voice Clone 必须提供参考音频的完整文字稿。")
        if not 0 < self.cfg_scale <= 20:
            raise ValueError("Breeze cfg_scale 必须大于 0 且不超过 20。")
        if isinstance(self.seed, bool) or not 0 <= self.seed <= 2**63 - 1:
            raise ValueError("Breeze seed 不合法。")


_CFG_SCALE = 4.0


def to_request(request: RecipeRequest) -> BreezeTTS2Request:
    """manifest recipe → Breeze 请求；cfg_scale 是插件内部固定值。"""
    if request.recipe_id == "breeze_tts2.voice_design":
        return BreezeTTS2Request(
            text=request.param("text"),
            instruction=request.param("voice_description"),
            cfg_scale=_CFG_SCALE,
            seed=request.param("seed"),
        )
    if request.recipe_id == "breeze_tts2.clone":
        voice = request.single("voice")
        assert voice is not None
        return BreezeTTS2Request(
            text=request.param("text"),
            instruction=request.param("performance_instruction"),
            voice=BreezeVoiceReference(voice.media_type, voice.content),
            reference_transcript=request.param("reference_transcript"),
            cfg_scale=_CFG_SCALE,
            seed=request.param("seed"),
        )
    raise ModelProviderError("unsupported_recipe", f"Breeze 不支持 recipe {request.recipe_id}。")


class BreezeTTS2Provider:
    """Adapter for the already deployed Breeze-TTS-2 streaming API.

    The official API is a single-request streaming endpoint rather than a
    durable job API.  We therefore spool the returned PCM as a WAV in the
    Provider runtime directory before returning a Core handle.  The Core still
    owns the Generation and imports the immutable bytes through this adapter.
    """

    plugin_id = "breeze_tts_2.speech"
    plugin_version = 1
    supports_voice_design = True
    supports_synthesis = True

    def __init__(
        self,
        endpoint: str,
        spool_dir: Path,
        transport: HttpTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._spool_dir = spool_dir.resolve(strict=False)
        self._http = transport or UrllibTransport()

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        return self.submit(to_request(request))

    def submit(self, request: BreezeTTS2Request) -> ProviderHandle:
        response = self._http.request(
            "POST",
            f"{self._endpoint}/breeze-tts2/speech",
            json_body={
                "text": request.text,
                "instruction": request.instruction,
                "reference_transcript": request.reference_transcript,
                "cfg_scale": request.cfg_scale,
                "seed": request.seed,
                "voice": (
                    {
                        "media_type": request.voice.media_type,
                        "base64": base64.b64encode(request.voice.content).decode("ascii"),
                    }
                    if request.voice is not None
                    else None
                ),
            },
        )
        if response.status == 200 and response.headers.get("content-type", "").startswith("audio/"):
            # Keep compatibility with a manually started official Breeze API.
            return self._spool_legacy_pcm(response.body, response.headers)
        if response.status in {400, 404, 405, 415}:
            # Older installations expose only the official synchronous endpoint.
            # The default deployment never takes this branch, but retaining it
            # makes a staged service restart safe.
            body, content_type = _multipart_body(request)
            try:
                status, pcm, headers = _request_raw(
                    "POST",
                    f"{self._endpoint}/v1/audio/speech",
                    body=body,
                    headers={"Content-Type": content_type, "Accept": "audio/pcm"},
                    timeout=1_800.0,
                )
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                raise ModelProviderError(
                    "transport_error", f"Breeze 服务不可用：{exc}", retryable=True
                ) from exc
            if status == 200:
                return self._spool_legacy_pcm(pcm, headers)
        data = require_success(response, {202})
        require_keys(data, required={"speech_id"})
        speech_id = data["speech_id"]
        if not isinstance(speech_id, str) or not speech_id:
            raise ModelProviderError("invalid_response", "Breeze speech_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, speech_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        self._validate_handle(handle)
        manifest = self._spool_dir / f"{handle.external_id}.json"
        if manifest.is_file():
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
                descriptor = ArtifactDescriptor(**value["artifact"])
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ModelProviderError("invalid_response", "Breeze 产物清单损坏。") from exc
            return GenerationObservation(
                GenerationPhase.SUCCEEDED, 1.0, "Breeze TTS-2 已完成。", descriptor
            )
        from urllib.parse import quote

        response = self._http.request(
            "GET", f"{self._endpoint}/breeze-tts2/speech/{quote(handle.external_id, safe='')}"
        )
        data = require_success(response, {200})
        require_keys(
            data,
            required={"condition", "progress_fraction", "status_text"},
            optional={"audio_file", "reason"},
        )
        phase = {
            "waiting_for_gpu": GenerationPhase.QUEUED,
            "speaking": GenerationPhase.RUNNING,
            "available": GenerationPhase.SUCCEEDED,
            "fault": GenerationPhase.FAILED,
            "cancelled": GenerationPhase.CANCELLED,
        }.get(data["condition"])
        if phase is None:
            raise ModelProviderError("invalid_response", "Breeze condition 不合法。")
        artifact = _audio(data.get("audio_file")) if phase is GenerationPhase.SUCCEEDED else None
        error = (
            str(data.get("reason") or "breeze_tts2_failed")
            if phase is GenerationPhase.FAILED
            else None
        )
        return GenerationObservation(
            phase, float(data["progress_fraction"]), str(data["status_text"]), artifact, error
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        if (self._spool_dir / f"{handle.external_id}.json").is_file():
            return self.observe(handle)
        from urllib.parse import quote

        response = self._http.request(
            "PATCH",
            f"{self._endpoint}/breeze-tts2/speech/{quote(handle.external_id, safe='')}",
            json_body={"cancel": True},
        )
        if response.status not in {202, 409}:
            require_success(response, {202, 409})
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        self._validate_handle(handle)
        if artifact_id != handle.external_id:
            raise ModelProviderError("artifact_unavailable", "Breeze Artifact 不属于该调用。")
        path = self._spool_dir / f"{handle.external_id}.wav"
        if path.is_file():
            return path.read_bytes()
        from urllib.parse import quote

        speech_path = f"{self._endpoint}/breeze-tts2/speech/{quote(handle.external_id, safe='')}"
        response = self._http.request("GET", f"{speech_path}/audio/{quote(artifact_id, safe='')}")
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "Breeze 音频不可用。")
        return response.body

    def _spool_legacy_pcm(self, pcm: bytes, headers: dict[str, str]) -> ProviderHandle:
        if not pcm or len(pcm) % 2:
            raise ModelProviderError("invalid_response", "Breeze 没有返回合法的 PCM 音频。")
        try:
            sample_rate = int(headers.get("x-sample-rate", "24000"))
        except ValueError as exc:
            raise ModelProviderError("invalid_response", "Breeze sample rate 不合法。") from exc
        external_id = uuid.uuid4().hex
        wav_content = _pcm_to_wav(pcm, sample_rate)
        self._spool_dir.mkdir(parents=True, exist_ok=True)
        (self._spool_dir / f"{external_id}.wav").write_bytes(wav_content)
        descriptor = _descriptor(external_id, wav_content, sample_rate)
        (self._spool_dir / f"{external_id}.json").write_text(
            json.dumps({"artifact": asdict(descriptor)}, ensure_ascii=False), encoding="utf-8"
        )
        return ProviderHandle(self.plugin_id, self.plugin_version, external_id)

    def _validate_handle(self, handle: ProviderHandle) -> None:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 Breeze TTS-2 插件。")


def _multipart_body(request: BreezeTTS2Request) -> tuple[bytes, str]:
    boundary = "----StoryRailBreeze" + uuid.uuid4().hex
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

    field("text", request.text)
    field("cfg_scale", str(request.cfg_scale))
    field("seed", str(request.seed))
    if request.instruction:
        field("instruction", request.instruction)
    if request.reference_transcript is not None:
        field("ref_text", request.reference_transcript)
    if request.voice is not None:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="ref_audio"; filename="reference.wav"\r\n',
                f"Content-Type: {request.voice.media_type}\r\n\r\n".encode(),
                request.voice.content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _request_raw(
    method: str, url: str, *, body: bytes, headers: dict[str, str], timeout: float
) -> tuple[int, bytes, dict[str, str]]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.read(),
                {k.lower(): v for k, v in response.headers.items()},
            )
    except HTTPError as exc:
        try:
            return exc.code, exc.read(), {k.lower(): v for k, v in exc.headers.items()}
        finally:
            exc.close()


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    from io import BytesIO

    output = BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return output.getvalue()


def _descriptor(external_id: str, content: bytes, sample_rate: int) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        external_id,
        "audio/wav",
        len(content),
        hashlib.sha256(content).hexdigest(),
        duration_seconds=(len(content) - 44) / 2 / sample_rate,
    )


def _audio(value: object) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ModelProviderError("invalid_response", "Breeze 完成响应缺少 audio_file。")
    require_keys(value, required={"name", "format", "bytes", "hash"})
    return ArtifactDescriptor(
        str(value["name"]), str(value["format"]), int(value["bytes"]), str(value["hash"])
    )
