from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.http import HttpTransport, UrllibTransport, require_keys, require_success


@dataclass(frozen=True, slots=True)
class MockGenerateRequest:
    text: str
    delay_ms: int = 20

    def __post_init__(self) -> None:
        if not self.text or len(self.text) > 1000:
            raise ValueError("text 必须是 1 到 1000 字符。")
        if not 0 <= self.delay_ms <= 10_000:
            raise ValueError("delay_ms 必须在 0 到 10000 之间。")


class MockModelProvider:
    plugin_id = "mock.generate"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport | None = None) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport or UrllibTransport()

    def submit(self, request: MockGenerateRequest) -> ProviderHandle:
        response = self._http.request(
            "POST",
            f"{self._endpoint}/mock/generate",
            json_body={"text": request.text, "delay_ms": request.delay_ms},
        )
        data = require_success(response, {202})
        require_keys(data, required={"ticket"})
        ticket = data["ticket"]
        if not isinstance(ticket, str) or not ticket:
            raise ModelProviderError("invalid_response", "Mock ticket 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, ticket)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        ticket = self._ticket(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/mock/tickets/{quote(ticket)}"), {200}
        )
        require_keys(
            data,
            required={"phase", "percent", "note"},
            optional={"output_key", "bytes", "sha256", "problem"},
        )
        phase_map = {
            "waiting": GenerationPhase.QUEUED,
            "drawing": GenerationPhase.RUNNING,
            "ready": GenerationPhase.SUCCEEDED,
            "broken": GenerationPhase.FAILED,
            "aborted": GenerationPhase.CANCELLED,
        }
        try:
            phase = phase_map[data["phase"]]
            progress = int(data["percent"]) / 100
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelProviderError("invalid_response", "Mock 状态字段不合法。") from exc
        artifact = None
        error_code = None
        if phase is GenerationPhase.SUCCEEDED:
            output_key = data.get("output_key")
            digest = data.get("sha256")
            size = data.get("bytes")
            if (
                not isinstance(output_key, str)
                or not isinstance(digest, str)
                or not isinstance(size, int)
            ):
                raise ModelProviderError("invalid_response", "Mock 完成响应缺少输出元数据。")
            artifact = ArtifactDescriptor(output_key, "text/plain", size, digest)
        elif phase is GenerationPhase.FAILED:
            error_code = "mock_failed"
        return GenerationObservation(
            phase=phase,
            progress=progress,
            message=str(data["note"]),
            artifact=artifact,
            error_code=error_code,
        )

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        ticket = self._ticket(handle)
        response = self._http.request("DELETE", f"{self._endpoint}/mock/tickets/{quote(ticket)}")
        require_success(response, {202, 409})
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        self._ticket(handle)
        response = self._http.request(
            "GET", f"{self._endpoint}/mock/outputs/{quote(artifact_id, safe='')}"
        )
        if response.status != 200:
            raise ModelProviderError("artifact_unavailable", "Mock 输出不可用。")
        return response.body

    def _ticket(self, handle: ProviderHandle) -> str:
        if handle.plugin_id != self.plugin_id or handle.plugin_version != self.plugin_version:
            raise ModelProviderError("invalid_handle", "调用句柄不属于该 Mock 插件。")
        return handle.external_id
