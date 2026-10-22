"""黄金 Provider 请求录制设施。

真实插件的 ``submit`` 把 Core 请求翻译成 HTTP 请求，这里用录制 transport 截获该请求，
观察与取产物则由确定性合成实现代替，因此不需要为每个外部服务协议写假服务。
录制结果是“发给外部服务的线上请求”：方法、路径与 JSON 体；媒体字节规范化成
可读标签加 SHA-256 与字节数，multipart 拆成有序字段，保证逐字节等价仍可比对且 diff 可读。

Provider 插件化重构前后都用同一份黄金文件比对；重构只允许调整本文件里构造插件的方式，
不允许修改黄金文件来迁就行为变化。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import struct
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.media_assets import mp4_duration
from core.model_providers.agy_image.plugin import plugin_instance as agy_image_plugin
from core.model_providers.boundary import (
    ArtifactDescriptor,
    GenerationObservation,
    GenerationPhase,
    ProviderHandle,
)
from core.model_providers.breeze_tts2.plugin import plugin_instance as breeze_tts2_plugin
from core.model_providers.codex_image.plugin import plugin_instance as codex_image_plugin
from core.model_providers.demucs_audio.plugin import plugin_instance as demucs_audio_plugin
from core.model_providers.ffmpeg_animatic import FFmpegAnimaticProvider
from core.model_providers.ffmpeg_audio_remix import FFmpegAudioRemixProvider
from core.model_providers.ffmpeg_final_assembly import FFmpegFinalAssemblyProvider
from core.model_providers.ffmpeg_pano_view import FFmpegPanoViewProvider
from core.model_providers.ffmpeg_video_frame import FFmpegVideoFrameProvider
from core.model_providers.http import HttpResponse
from core.model_providers.minimax_h3 import MANIFEST as H3_MANIFEST
from core.model_providers.minimax_h3 import render_settings as render_h3
from core.model_providers.minimax_h3.plugin import plugin_instance as minimax_h3_plugin
from core.model_providers.minimax_h3.render import H3RenderSettings
from core.model_providers.registry import PluginInstance, ProviderRegistry
from core.model_providers.seedvr2_7b_sharp_fp8.plugin import plugin_instance as seedvr2_plugin
from core.model_providers.settings import ProviderSettingsStore
from core.model_providers.stable_audio_3.plugin import plugin_instance as stable_audio_3_plugin
from core.model_providers.whisper_asr.plugin import plugin_instance as whisper_asr_plugin

GOLDEN_DIRECTORY = Path(__file__).parent / "golden" / "provider_requests"
UPDATE_ENV = "STORYRAIL_UPDATE_GOLDEN"
ENDPOINT = "http://golden.invalid"

# 插件请求体里承载 base64 媒体字节的键。
_BLOB_KEYS = frozenset({"base64", "data_base64", "content"})


# ---------------------------------------------------------------------------
# 确定性媒体字节
# ---------------------------------------------------------------------------


def png_bytes(label: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + label.encode()


def panorama_png_bytes(label: str, width: int = 2048) -> bytes:
    """带 IHDR 的 2:1 PNG 头，满足全景裁切的宽高契约。"""
    ihdr = struct.pack(">II", width, width // 2) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + label.encode()


def wav_bytes(label: str, duration_seconds: float, sample_rate: int = 8_000) -> bytes:
    """合法 PCM WAV；采样内容由标签重复填充，保证不同标签字节不同。"""
    frames = round(duration_seconds * sample_rate)
    pattern = hashlib.sha256(label.encode()).digest()
    pcm = (pattern * (frames * 2 // len(pattern) + 1))[: frames * 2]
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm)
    return output.getvalue()


def _box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def _full(kind: bytes, body: bytes) -> bytes:
    return _box(kind, b"\x00\x00\x00\x00" + body)


def mp4_bytes(label: str, duration_seconds: float, fps: int = 24) -> bytes:
    """只含 box 结构的 MP4：mvhd/mdhd 时长与 stsz 帧数可被 Core 读取，标签放在 free box。"""
    timescale = 1000
    duration = round(duration_seconds * timescale)
    frames = max(1, round(duration_seconds * fps))
    mvhd = _full(b"mvhd", b"\x00" * 8 + struct.pack(">II", timescale, duration) + b"\x00" * 80)
    tkhd = _full(b"tkhd", b"\x00" * 8 + struct.pack(">I", 1) + b"\x00" * 68)
    mdhd = _full(b"mdhd", b"\x00" * 8 + struct.pack(">II", timescale, duration) + b"\x00" * 4)
    hdlr = _full(b"hdlr", b"\x00" * 4 + b"vide" + b"\x00" * 13)
    stsz = _full(b"stsz", struct.pack(">II", 0, frames))
    trak = _box(b"trak", tkhd + _box(b"mdia", mdhd + hdlr + _box(b"minf", _box(b"stbl", stsz))))
    return (
        _box(b"ftyp", b"isom\x00\x00\x02\x00isom")
        + _box(b"moov", mvhd + trak)
        + _box(b"free", label.encode())
    )


# ---------------------------------------------------------------------------
# 线上请求日志与规范化
# ---------------------------------------------------------------------------


@dataclass
class WireLog:
    """按提交顺序记录发给外部服务的请求；字节按已登记标签规范化。"""

    entries: list[dict[str, Any]] = field(default_factory=list)
    # 当前场景步骤名；写进每条记录，让黄金文件 diff 能直接对应到用户操作。
    step: str = ""
    _labels: dict[str, str] = field(default_factory=dict)

    def label(self, content: bytes, name: str) -> bytes:
        self._labels.setdefault(hashlib.sha256(content).hexdigest(), name)
        return content

    def record(self, plugin: str, method: str, url: str, body: Any) -> None:
        self.entries.append(
            {
                "step": self.step,
                "plugin": plugin,
                "method": method,
                "path": urlsplit(url).path,
                "body": self._normalize(body),
            }
        )

    def blob(self, content: bytes) -> dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        return {
            "blob": self._labels.get(digest, "unlabelled"),
            "sha256": digest,
            "bytes": len(content),
        }

    def _normalize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    self.blob(base64.b64decode(item, validate=True))
                    if key in _BLOB_KEYS and isinstance(item, str)
                    else self._normalize(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._normalize(item) for item in value]
        return value

    def multipart(self, body: bytes, content_type: str) -> list[dict[str, Any]]:
        boundary = content_type.split("boundary=", 1)[1].encode()
        parts = body.split(b"--" + boundary)
        if parts[0] != b"" or parts[-1] != b"--\r\n":
            raise AssertionError("multipart 结构不合法。")
        fields = []
        for part in parts[1:-1]:
            head, _separator, content = part.removeprefix(b"\r\n").partition(b"\r\n\r\n")
            content = content.removesuffix(b"\r\n")
            headers = head.decode().split("\r\n")
            entry: dict[str, Any] = {"headers": headers}
            if any(line.startswith("Content-Type:") for line in headers):
                entry["value"] = self.blob(content)
            else:
                entry["value"] = content.decode()
            fields.append(entry)
        return fields


# ---------------------------------------------------------------------------
# 录制 transport 与合成观察包装
# ---------------------------------------------------------------------------

# 每个插件 submit 接受的最小合法 202 应答体。
_SUBMIT_REPLIES: dict[str, Callable[[str], dict[str, Any]]] = {
    "codex": lambda token: {"request_id": token, "accepted_at": "2026-01-01T00:00:00Z"},
    "agy": lambda token: {"request_id": token, "accepted_at": "2026-01-01T00:00:00Z"},
    "breeze": lambda token: {"speech_id": token},
    "h3_fl2va": lambda token: {"job_token": token, "queue_position": 0},
    "h3_ref2va": lambda token: {"render_id": token, "status_uri": f"/renders/{token}"},
    "seedvr2": lambda token: {"job_token": token, "queue_position": 0},
    "demucs": lambda token: {"separation_id": token},
    "stable_audio": lambda token: {"generation_id": token},
    "animatic": lambda token: {"animatic_id": token},
    "final_assembly": lambda token: {"assembly_id": token},
    "video_frame": lambda token: {"frame_id": token},
    "pano_view": lambda token: {"view_id": token},
    "audio_remix": lambda token: {"remix_id": token},
}


class RecordingTransport:
    """只服务 submit：记录请求并回 202；observe/取产物不经过这里。

    同一插件实例的多个实现共用一个 transport 时，``routes`` 按路径前缀给记录命名。
    """

    def __init__(self, log: WireLog, name: str, routes: dict[str, str] | None = None) -> None:
        self._log = log
        self._name = name
        self._routes = routes or {}
        self._counts: dict[str, int] = {}
        self.last_body: dict[str, Any] | None = None

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        del timeout
        if method != "POST":
            raise AssertionError(f"录制 transport 只应收到 submit：{method} {url}")
        path = urlsplit(url).path
        name = next(
            (item for prefix, item in self._routes.items() if path.startswith(prefix)), self._name
        )
        self._log.record(name, method, url, json_body)
        self.last_body = json_body
        self._counts[name] = self._counts.get(name, 0) + 1
        reply = _SUBMIT_REPLIES[name](f"{name}-{self._counts[name]}")
        return HttpResponse(202, {"content-type": "application/json"}, json.dumps(reply).encode())


OutputFactory = Callable[[str, dict[str, Any]], tuple[str, bytes, float | None]]


class GoldenPlugin:
    """真实插件负责 submit 翻译；observe 立即成功并返回由提交标签派生的确定性产物。"""

    def __init__(
        self,
        real: object,
        transport: RecordingTransport,
        log: WireLog,
        output: OutputFactory,
    ) -> None:
        self._real = real
        self._transport = transport
        self._log = log
        self._output = output
        self._artifacts: dict[str, tuple[str, bytes, float | None]] = {}
        self._fail_next = False
        self._failing: set[str] = set()
        for name in (
            "plugin_id",
            "plugin_ids",
            "generate_plugin_id",
            "edit_plugin_id",
            "plugin_version",
            "supports_voice_design",
            "supports_synthesis",
        ):
            if hasattr(real, name):
                setattr(self, name, getattr(real, name))

    def fail_next(self) -> None:
        """下一次提交观察为可重试失败，用于录制重试请求。"""
        self._fail_next = True

    def _remember(self, handle: ProviderHandle) -> ProviderHandle:
        if self._fail_next:
            self._fail_next = False
            self._failing.add(handle.external_id)
        label = f"output:{handle.external_id}"
        media_type, content, duration = self._output(label, self._transport.last_body or {})
        self._artifacts[handle.external_id] = (
            media_type,
            self._log.label(content, label),
            duration,
        )
        return handle

    def submit(self, request: object) -> ProviderHandle:
        return self._remember(self._real.submit(request))

    def submit_recipe(self, request: object) -> ProviderHandle:
        return self._remember(self._real.submit_recipe(request))

    def submit_generate(self, request: object) -> ProviderHandle:
        return self._remember(self._real.submit_generate(request))

    def submit_edit(self, request: object) -> ProviderHandle:
        return self._remember(self._real.submit_edit(request))

    def observe(self, handle: ProviderHandle) -> GenerationObservation:
        if handle.external_id in self._failing:
            return GenerationObservation(
                GenerationPhase.FAILED, 1.0, "失败", None, "golden_failure", True
            )
        media_type, content, duration = self._artifacts[handle.external_id]
        descriptor = ArtifactDescriptor(
            handle.external_id,
            media_type,
            len(content),
            hashlib.sha256(content).hexdigest(),
            duration,
        )
        return GenerationObservation(GenerationPhase.SUCCEEDED, 1.0, "完成", descriptor)

    def cancel(self, handle: ProviderHandle) -> GenerationObservation:
        return GenerationObservation(GenerationPhase.CANCELLED, 0.0, "已取消")

    def read_artifact(self, handle: ProviderHandle, artifact_id: str) -> bytes:
        del artifact_id
        return self._artifacts[handle.external_id][1]


def _image(label: str, body: dict[str, Any]) -> tuple[str, bytes, float | None]:
    # 地点全景图请求等距柱状投影：产物带 2:1 IHDR，才能进入 3D 查看器取景。
    if "等距柱状投影" in json.dumps(body, ensure_ascii=False):
        return "image/png", panorama_png_bytes(label), None
    return "image/png", png_bytes(label), None


def _speech(label: str, body: dict[str, Any]) -> tuple[str, bytes, float | None]:
    # 时长随文本长度变化，让中英旁白取较长一条作时间基准的规则在请求里可见。
    duration = round(1.0 + len(body.get("text", "")) * 0.05, 2)
    return "audio/wav", wav_bytes(label, duration), duration


def _video_with(key: str) -> OutputFactory:
    def build(label: str, body: dict[str, Any]) -> tuple[str, bytes, float | None]:
        duration = float(body.get(key) or 4.0)
        return "video/mp4", mp4_bytes(label, duration), duration

    return build


def _h3_video(label: str, body: dict[str, Any]) -> tuple[str, bytes, float | None]:
    duration = float(body.get("seconds") or body.get("duration_s") or 4.0)
    return "video/mp4", mp4_bytes(label, duration), duration


def _assembled(label: str, body: dict[str, Any]) -> tuple[str, bytes, float | None]:
    duration = sum(float(clip["duration_seconds"]) for clip in body.get("clips", [])) or 4.0
    return "video/mp4", mp4_bytes(label, duration), duration


def _stem(label: str, _body: dict[str, Any]) -> tuple[str, bytes, float | None]:
    return "audio/wav", wav_bytes(label, 4.0), 4.0


def _generated_audio(label: str, body: dict[str, Any]) -> tuple[str, bytes, float | None]:
    duration = float(body.get("duration_seconds") or 4.0)
    return "audio/wav", wav_bytes(label, duration), duration


def _same_length_video(key: str) -> OutputFactory:
    """超分与重新混音保持来源视频时长。"""

    def build(label: str, body: dict[str, Any]) -> tuple[str, bytes, float | None]:
        duration = mp4_duration(base64.b64decode(body[key]["base64"]))
        return "video/mp4", mp4_bytes(label, duration), duration

    return build


class GoldenWhisper:
    """whisper.cpp 插件直接用 urllib；这里替换其 urlopen 并录制 multipart。"""

    def __init__(self, log: WireLog, real: object) -> None:
        self._log = log
        self.real = real
        self.plugin_id = real.plugin_id
        self.plugin_version = real.plugin_version

    def execute_recipe(self, request):
        return self.transcribe(request)

    def transcribe(self, request: object):
        from core.model_providers.whisper_asr import provider as module

        log = self._log

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self) -> bytes:
                return json.dumps({"text": " 转写结果 "}).encode()

        def fake_urlopen(http_request, timeout):
            del timeout
            content_type = http_request.get_header("Content-type")
            log.entries.append(
                {
                    "step": log.step,
                    "plugin": "whisper",
                    "method": http_request.get_method(),
                    "path": urlsplit(http_request.full_url).path,
                    "body": log.multipart(http_request.data, content_type),
                }
            )
            return _Response()

        original = module.urlopen
        module.urlopen = fake_urlopen
        try:
            return self.real.transcribe(request)
        finally:
            module.urlopen = original


@dataclass
class GoldenProviders:
    log: WireLog
    registry: ProviderRegistry
    plugins: dict[str, GoldenPlugin]

    def h3_render(self) -> H3RenderSettings:
        """与 server/__main__.py 相同：H3 渲染组合来自插件实例设置。"""
        return render_h3(self.registry.plugin_settings(H3_MANIFEST.plugin_id))

    def set_h3(self, preset: str, resolution: str, sage_attention: bool, selflift: bool) -> None:
        self.registry.update_plugin_settings(
            H3_MANIFEST.plugin_id,
            {
                "preset": preset,
                "resolution": resolution,
                "sage_attention": sage_attention,
                "selflift": selflift,
            },
        )

    def bind_images(self, plugin_id: str) -> None:
        for capability in ("image.generate", "image.edit"):
            self.registry.bind(capability, plugin_id)


def golden_providers(spool_directory: Path) -> GoldenProviders:
    """按生产装配（server/__main__.py）安装真实插件实例，实现对象接到录制 transport。"""
    log = WireLog()
    plugins: dict[str, GoldenPlugin] = {}
    registry = ProviderRegistry(ProviderSettingsStore(spool_directory / "providers.json"))

    def install(
        name: str,
        factory: Callable[[RecordingTransport], PluginInstance],
        output: OutputFactory,
        routes: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        """``routes``：路径前缀 → (记录名, 实现端口)，给共用 transport 的多个实现分别命名。"""
        transport = RecordingTransport(
            log, name, {prefix: item for prefix, (item, _port) in (routes or {}).items()}
        )
        instance = factory(transport)
        wrapped: dict[int, GoldenPlugin] = {}

        def wrap(provider: object) -> GoldenPlugin:
            return wrapped.setdefault(id(provider), GoldenPlugin(provider, transport, log, output))

        recipes = {recipe_id: wrap(provider) for recipe_id, provider in instance.recipes.items()}
        for recipe_id, plugin in recipes.items():
            for item, route_port in (routes or {}).values():
                if recipe_id.endswith("." + route_port):
                    plugins[item] = plugin
        plugins.setdefault(name, next(iter(wrapped.values())))
        registry.install(
            PluginInstance(
                instance.manifest,
                endpoint=instance.endpoint,
                recipes=recipes,
                prompt_formatter=instance.prompt_formatter,
                prompt_skills=instance.prompt_skills,
            )
        )

    def tool(name: str, capability: str, provider: object, output: OutputFactory) -> None:
        transport = RecordingTransport(log, name)
        provider._http = transport  # noqa: SLF001 - 确定性工具没有工厂，直接接录制 transport
        plugins[name] = GoldenPlugin(provider, transport, log, output)
        registry.register(capability, plugins[name])

    install("codex", lambda t: codex_image_plugin(ENDPOINT, t), _image)
    install("agy", lambda t: agy_image_plugin(ENDPOINT, t), _image)
    install("demucs", lambda t: demucs_audio_plugin(ENDPOINT, t), _stem)
    install(
        "breeze",
        lambda t: breeze_tts2_plugin(ENDPOINT, spool_directory / "breeze-tts2", t),
        _speech,
    )
    install(
        "video_prompt",
        lambda t: minimax_h3_plugin(ENDPOINT, t),
        _h3_video,
        routes={
            "/minimax-h3/fl2va/": ("h3_fl2va", "fl2va"),
            "/minimax-h3/ref2va/": ("h3_ref2va", "ref2va"),
        },
    )
    install("seedvr2", lambda t: seedvr2_plugin(ENDPOINT, t), _same_length_video("source_video"))
    install("stable_audio", lambda t: stable_audio_3_plugin(ENDPOINT, t), _generated_audio)
    whisper = whisper_asr_plugin(ENDPOINT)
    ((recipe, real_whisper),) = whisper.recipes.items()
    registry.install(
        PluginInstance(
            whisper.manifest,
            endpoint=whisper.endpoint,
            recipes={recipe: GoldenWhisper(log, real_whisper)},
        )
    )
    tool("final_assembly", "final_assembly", FFmpegFinalAssemblyProvider(ENDPOINT), _assembled)
    tool("animatic", "animatic", FFmpegAnimaticProvider(ENDPOINT), _assembled)
    tool("video_frame", "video_frame", FFmpegVideoFrameProvider(ENDPOINT), _image)
    tool("pano_view", "pano_view", FFmpegPanoViewProvider(ENDPOINT), _image)
    tool(
        "audio_remix",
        "audio_remix",
        FFmpegAudioRemixProvider(ENDPOINT),
        _same_length_video("video"),
    )
    return GoldenProviders(log, registry, plugins)


# ---------------------------------------------------------------------------
# 黄金文件比对
# ---------------------------------------------------------------------------


def _substitute(value: Any, substitutions: dict[int, str]) -> Any:
    if isinstance(value, dict):
        return {key: _substitute(item, substitutions) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, substitutions) for item in value]
    if isinstance(value, int) and not isinstance(value, bool) and value in substitutions:
        return substitutions[value]
    return value


def assert_golden(
    name: str,
    entries: list[dict[str, Any]],
    *,
    substitutions: dict[int, str] | None = None,
) -> None:
    """比对黄金文件。``substitutions`` 把由 Core 分配 ID 派生的值换成规则描述，
    使黄金文件不依赖 ID 分配顺序，同时仍校验派生规则本身。"""
    path = GOLDEN_DIRECTORY / f"{name}.json"
    entries = _substitute(entries, substitutions or {})
    rendered = json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.environ.get(UPDATE_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return
    if not path.exists():
        raise AssertionError(f"缺少黄金文件 {path}；用 {UPDATE_ENV}=1 在基线代码上录制。")
    expected = path.read_text(encoding="utf-8")
    assert rendered == expected, f"线上请求与黄金文件 {path.name} 不一致。"
