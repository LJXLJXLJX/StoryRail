# 代码骨架

下面是一个完整、可运行的示例插件 `my_video`：接入一个假想的云端图生视频 API（首帧 + 提示词 → MP4）。
把 `my_video`、`MyVideo`、URL 路径和字段换成目标 API 的真实定义即可。本地模型服务按 local-service.md
的约定时，结构完全相同，只是路径与响应字段不同，并且通常由服务端直接给出 `sha256`。

假想 API：

```text
POST /tasks                {"prompt", "image": "data:image/png;base64,...", "duration": 5, "seed": 1,
                            "aspect_ratio": "16:9", "motion": "medium", "resolution": "720p"}
                           → 200 {"task_id": "..."}
GET  /tasks/<id>           → 200 {"status": "pending|running|succeeded|failed|cancelled",
                                  "progress": 0.4, "video_url"?: "https://cdn.example.com/...",
                                  "error"?: "..."}
POST /tasks/<id>/cancel    → 200
```

## `core/model_providers/my_video/manifest.py`

```python
"""My Video 插件 manifest：首帧图生视频。"""

from __future__ import annotations

from core.model_providers.manifest import (
    Capability,
    Field,
    Option,
    PluginManifest,
    Recipe,
    Role,
    Slot,
    Widget,
    aspect_ratio_field,
    prompt_field,
    seed_field,
)

MANIFEST = PluginManifest(
    plugin_id="my_video",
    plugin_version=1,
    label="My Video",
    recipes=(
        Recipe(
            "my_video.i2v",
            Capability.VIDEO_GENERATE,
            "首帧生成视频",
            slots=(
                Slot(
                    "first_frame",
                    Role.FIRST_FRAME,
                    "首帧",
                    minimum=1,
                    media_types=("image/png", "image/jpeg"),
                ),
            ),
            params=(
                prompt_field(2_000),
                Field(
                    "duration_seconds",
                    Widget.NUMBER,
                    "时长（秒）",
                    minimum=1,
                    maximum=10,
                    role=Role.DURATION,
                ),
                aspect_ratio_field(),
                seed_field(),
                # 没有 role 的机制参数：每个 Segment 各自保存，人或 Agent 填写。
                Field(
                    "motion",
                    Widget.ENUM,
                    "运动幅度",
                    default="medium",
                    options=(Option("low", "小"), Option("medium", "中"), Option("high", "大")),
                ),
            ),
        ),
    ),
    # 模型级设置：全局一份，在「Provider 设置」里修改。
    settings=(
        Field(
            "resolution",
            Widget.ENUM,
            "分辨率",
            default="720p",
            options=(Option("720p", "720p"), Option("1080p", "1080p")),
            summary=True,
        ),
    ),
    hints=(("soft_duration_limit_seconds", 10),),
)
```

## `core/model_providers/my_video/provider.py`

```python
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from math import isfinite
from urllib.parse import quote, urlsplit

from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ModelProviderError,
    ProviderHandle,
)
from core.model_providers.http import HttpTransport, require_keys, require_success
from core.model_providers.recipe import RecipeRequest

# 结果下载链接只接受这些主机，按厂商文档填写。
_DOWNLOAD_HOSTS = frozenset({"cdn.example.com"})


@dataclass(frozen=True, slots=True)
class MyVideoRequest:
    prompt: str
    first_frame: bytes
    first_frame_type: str
    duration_seconds: float
    aspect_ratio: str
    seed: int
    motion: str
    resolution: str

    def __post_init__(self) -> None:
        if not self.prompt.strip() or len(self.prompt) > 2_000:
            raise ValueError("提示词必须是 1 到 2000 个字符。")
        if self.first_frame_type not in {"image/png", "image/jpeg"} or not self.first_frame:
            raise ValueError("首帧必须是 PNG 或 JPEG。")
        if not isfinite(self.duration_seconds) or not 1 <= self.duration_seconds <= 10:
            raise ValueError("时长必须在 1 到 10 秒之间。")
        if self.aspect_ratio not in {"16:9", "9:16", "2:1"}:
            raise ValueError("画幅不受支持。")
        if self.motion not in {"low", "medium", "high"}:
            raise ValueError("运动幅度不受支持。")
        if self.resolution not in {"720p", "1080p"}:
            raise ValueError("分辨率不受支持。")


def to_request(contract: RecipeRequest) -> MyVideoRequest:
    frame = contract.single("first_frame")
    if frame is None:
        raise ValueError("缺少首帧。")
    return MyVideoRequest(
        prompt=str(contract.param("prompt")),
        first_frame=frame.content,
        first_frame_type=frame.media_type,
        duration_seconds=float(contract.param("duration_seconds")),
        aspect_ratio=str(contract.param("aspect_ratio")),
        seed=int(contract.param("seed")),
        motion=str(contract.param("motion")),
        resolution=str(contract.setting("resolution")),
    )


_PHASES = {
    "pending": GenerationPhase.QUEUED,
    "running": GenerationPhase.RUNNING,
    "succeeded": GenerationPhase.SUCCEEDED,
    "failed": GenerationPhase.FAILED,
    "cancelled": GenerationPhase.CANCELLED,
}
_MESSAGES = {
    GenerationPhase.QUEUED: "排队中。",
    GenerationPhase.RUNNING: "正在生成视频。",
    GenerationPhase.SUCCEEDED: "视频已生成。",
    GenerationPhase.FAILED: "视频生成失败。",
    GenerationPhase.CANCELLED: "已取消。",
}


class MyVideoProvider:
    plugin_id = "my_video"
    plugin_version = 1

    def __init__(self, endpoint: str, transport: HttpTransport) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._http = transport
        self._downloads: dict[str, bytes] = {}

    def submit_recipe(self, request: RecipeRequest) -> ProviderHandle:
        return self.submit(to_request(request))

    def submit(self, request: MyVideoRequest) -> ProviderHandle:
        image = base64.b64encode(request.first_frame).decode("ascii")
        data = require_success(
            self._http.request(
                "POST",
                f"{self._endpoint}/tasks",
                json_body={
                    "prompt": request.prompt,
                    "image": f"data:{request.first_frame_type};base64,{image}",
                    "duration": request.duration_seconds,
                    "seed": request.seed,
                    "aspect_ratio": request.aspect_ratio,
                    "motion": request.motion,
                    "resolution": request.resolution,
                },
            ),
            {200},
        )
        require_keys(data, required={"task_id"})
        task_id = data["task_id"]
        if not isinstance(task_id, str) or not task_id or len(task_id) > 200:
            raise ModelProviderError("invalid_response", "My Video task_id 不合法。")
        return ProviderHandle(self.plugin_id, self.plugin_version, task_id)

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        data = self._task(handle)
        phase = _PHASES[data["status"]]
        if phase is GenerationPhase.SUCCEEDED:
            content = self._download(data.get("video_url"))
            self._downloads[handle.external_id] = content
            artifact = ArtifactDescriptor(
                handle.external_id, "video/mp4", len(content), hashlib.sha256(content).hexdigest()
            )
            return GenerationObservation(phase, 1.0, _MESSAGES[phase], artifact)
        if phase is GenerationPhase.FAILED:
            return GenerationObservation(phase, 0.0, _MESSAGES[phase], None, "video_failed")
        return GenerationObservation(phase, float(data.get("progress") or 0.0), _MESSAGES[phase])

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        task_id = self._id(handle)
        require_success(
            self._http.request("POST", f"{self._endpoint}/tasks/{quote(task_id)}/cancel"),
            {200, 409},
        )
        return self.observe(handle)

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        if artifact_id != self._id(handle):
            raise ModelProviderError("artifact_unavailable", "产物不属于该任务。")
        content = self._downloads.pop(handle.external_id, None)
        if content is None:
            # Core 重启后缓存为空：重新查询拿到（可能已刷新的）下载链接。
            data = self._task(handle)
            if data["status"] != "succeeded":
                raise ModelProviderError("artifact_unavailable", "视频产物不可用。")
            content = self._download(data.get("video_url"))
        return content

    def _task(self, handle: ProviderHandle) -> dict:
        task_id = self._id(handle)
        data = require_success(
            self._http.request("GET", f"{self._endpoint}/tasks/{quote(task_id)}"), {200}
        )
        require_keys(data, required={"status"}, optional={"progress", "video_url", "error"})
        if data["status"] not in _PHASES:
            raise ModelProviderError("invalid_response", "My Video 任务状态不合法。")
        progress = data.get("progress")
        if progress is not None and (
            isinstance(progress, bool)
            or not isinstance(progress, int | float)
            or not 0 <= progress <= 1
        ):
            raise ModelProviderError("invalid_response", "My Video 进度不合法。")
        return data

    def _download(self, url: object) -> bytes:
        if not isinstance(url, str):
            raise ModelProviderError("invalid_response", "My Video 完成响应缺少 video_url。")
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in _DOWNLOAD_HOSTS:
            raise ModelProviderError("invalid_response", "My Video 下载地址不在允许的主机内。")
        response = self._http.request("GET", url, timeout=300.0)
        if response.status != 200 or response.body[4:8] != b"ftyp":
            raise ModelProviderError(
                "artifact_unavailable", "My Video 视频下载失败。", retryable=True
            )
        return response.body

    def _id(self, handle: ProviderHandle) -> str:
        if (handle.plugin_id, handle.plugin_version) != (self.plugin_id, self.plugin_version):
            raise ModelProviderError("invalid_handle", "调用句柄不属于 My Video 插件。")
        return handle.external_id
```

> 下载请求复用了带 API Key 的同一个 transport。厂商的 CDN 链接本身已签名、不需要 Key 时，为下载单独构造一个
> 不带认证头的 `UrllibTransport()`，避免把 Key 发给 CDN。

## `core/model_providers/my_video/plugin.py`

```python
"""把 MyVideoProvider 安装为全局可绑定的插件实例。"""

from __future__ import annotations

import os

from core.model_providers.http import HttpTransport, UrllibTransport
from core.model_providers.registry import PluginInstance

from .manifest import MANIFEST
from .provider import MyVideoProvider

API_KEY_ENV = "STORYRAIL_MY_VIDEO_API_KEY"


def plugin_instance(endpoint: str, transport: HttpTransport | None = None) -> PluginInstance:
    if transport is None:
        key = os.environ.get(API_KEY_ENV, "").strip()
        if not key:
            raise ValueError(f"my_video 插件缺少环境变量 {API_KEY_ENV}。")
        transport = UrllibTransport({"Authorization": f"Bearer {key}"})
    provider = MyVideoProvider(endpoint, transport)
    return PluginInstance(
        MANIFEST, endpoint=endpoint, recipes={recipe.id: provider for recipe in MANIFEST.recipes}
    )
```

## `core/model_providers/my_video/__init__.py`

```python
"""My Video 图生视频插件。"""

from .provider import MyVideoProvider, MyVideoRequest

__all__ = ["MyVideoProvider", "MyVideoRequest"]
```

## `tests/test_my_video_provider.py`

```python
"""My Video 插件：请求翻译、状态映射、下载校验与句柄归属。不访问网络。"""

from __future__ import annotations

import hashlib
import json

import pytest

from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.http import HttpResponse
from core.model_providers.manifest import Role
from core.model_providers.my_video.manifest import MANIFEST
from core.model_providers.my_video.plugin import API_KEY_ENV, plugin_instance
from core.model_providers.recipe import MediaInput, build_recipe_request

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 32


class FakeTransport:
    def __init__(self, status: dict) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.status = status

    def request(self, method, url, *, json_body=None, timeout=30.0):
        self.calls.append((method, url, json_body))
        if method == "POST" and url.endswith("/tasks"):
            return HttpResponse(200, {}, json.dumps({"task_id": "t1"}).encode())
        if url.startswith("https://cdn.example.com/"):
            return HttpResponse(200, {}, MP4)
        if method == "POST":
            return HttpResponse(200, {}, b"{}")
        return HttpResponse(200, {}, json.dumps(self.status).encode())


def _request(**params):
    return build_recipe_request(
        MANIFEST,
        "my_video.i2v",
        inputs={"first_frame": (MediaInput("image/png", PNG),)},
        params={
            "prompt": "海浪拍岸",
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "seed": 7,
            "motion": "medium",
            **params,
        },
    )


def _provider(status: dict):
    transport = FakeTransport(status)
    plugin = plugin_instance("https://api.example.com/v1", transport)
    return plugin.recipes["my_video.i2v"], transport


def test_plugin_identity_and_core_filled_roles():
    instance = plugin_instance("https://api.example.com/v1", FakeTransport({}))
    assert instance.plugin_id == "my_video"
    roles = {item.role for item in MANIFEST.recipe("my_video.i2v").params if item.role}
    assert roles == {Role.PROMPT, Role.DURATION, Role.ASPECT_RATIO, Role.SEED}


def test_missing_api_key_is_explicit(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with pytest.raises(ValueError, match=API_KEY_ENV):
        plugin_instance("https://api.example.com/v1")


def test_submit_translates_request_exactly():
    provider, transport = _provider({"status": "pending"})
    handle = provider.submit_recipe(_request())
    assert handle == ProviderHandle("my_video", 1, "t1")
    method, url, body = transport.calls[0]
    assert (method, url) == ("POST", "https://api.example.com/v1/tasks")
    assert body["image"].startswith("data:image/png;base64,")
    assert {key: body[key] for key in body if key != "image"} == {
        "prompt": "海浪拍岸",
        "duration": 5.0,
        "seed": 7,
        "aspect_ratio": "16:9",
        "motion": "medium",
        "resolution": "720p",
    }


def test_out_of_range_params_are_rejected():
    with pytest.raises(ValueError):
        _request(duration_seconds=30)
    with pytest.raises(ValueError):
        _request(motion="extreme")


@pytest.mark.parametrize(
    ("status", "phase"),
    [
        ("pending", GenerationPhase.QUEUED),
        ("running", GenerationPhase.RUNNING),
        ("cancelled", GenerationPhase.CANCELLED),
    ],
)
def test_status_mapping(status, phase):
    provider, _ = _provider({"status": status, "progress": 0.5})
    assert provider.observe(ProviderHandle("my_video", 1, "t1")).phase is phase


def test_success_downloads_and_describes_artifact():
    url = "https://cdn.example.com/t1.mp4"
    provider, _ = _provider({"status": "succeeded", "video_url": url})
    handle = ProviderHandle("my_video", 1, "t1")
    observation = provider.observe(handle)
    assert observation.artifact.sha256 == hashlib.sha256(MP4).hexdigest()
    assert observation.artifact.byte_count == len(MP4)
    assert provider.read_artifact(handle, "t1") == MP4


def test_failure_unknown_status_foreign_host_and_foreign_handle():
    provider, _ = _provider({"status": "failed", "error": "审核未通过"})
    observation = provider.observe(ProviderHandle("my_video", 1, "t1"))
    assert observation.phase is GenerationPhase.FAILED and observation.error_code
    provider, _ = _provider({"status": "weird"})
    with pytest.raises(ModelProviderError):
        provider.observe(ProviderHandle("my_video", 1, "t1"))
    provider, _ = _provider({"status": "succeeded", "video_url": "https://evil.example.net/x"})
    with pytest.raises(ModelProviderError):
        provider.observe(ProviderHandle("my_video", 1, "t1"))
    with pytest.raises(ModelProviderError):
        provider.observe(ProviderHandle("other", 1, "t1"))
```

## 插件 README 要写的内容

- 一句话：哪个模型、哪项能力、云端还是本地；
- 外部接口：调用了哪些路径，输入如何上传，结果如何取回；
- 凭据：环境变量名，写在哪里（`start.local.env`）；
- 限制：时长、分辨率、格式、取消是否真正中止计费、内容审核；
- 启动示例：`./start.sh --provider-plugin my_video=https://api.example.com/v1`。
