"""全景裁切：Core 插件 HTTP 协议、媒体服务请求构造、真实 FFmpeg v360 worker 与服务闭环。"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.contracts import PanoViewRequest as PanoViewContract
from core.model_providers.contracts import image_dimensions
from core.model_providers.ffmpeg_pano_view import FFmpegPanoViewProvider, PanoViewRequest
from core.model_providers.http import HttpResponse, UrllibTransport
from default_model_providers_implement.ffmpeg_pano_view_worker import (
    OUTPUT_SIZES,
    render,
    vertical_fov,
)
from default_model_providers_implement.request_builders import prepare_ffmpeg_pano_view
from default_model_providers_implement.server import ModelApiServer
from default_model_providers_implement.strict_json import RequestError
from default_model_providers_implement.task_store import TaskRecord


def _png_header(width: int = 2048, height: int = 1024) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )


class RecordingTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, *, json_body=None, timeout: float = 30.0):
        self.calls.append((method, url, json_body))
        return self.responses.pop(0)


def _response(status: int, value: dict) -> HttpResponse:
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(value).encode())


def _payload(**overrides) -> dict:
    return {
        "mime": "image/png",
        "base64": base64.b64encode(_png_header()).decode(),
        "yaw_deg": 90.0,
        "pitch_deg": -10.0,
        "hfov_deg": 75.0,
        "aspect_ratio": "16:9",
        **overrides,
    }


# ---------------------------------------------------------------- Core 插件


def test_submit_sends_typed_geometry_without_paths() -> None:
    transport = RecordingTransport([_response(202, {"view_id": "view-1"})])
    provider = FFmpegPanoViewProvider("http://models/", transport)

    handle = provider.submit(PanoViewContract(_png_header(), 270, 15, 90, "9:16"))

    assert handle == ProviderHandle("ffmpeg.pano_view", 1, "view-1")
    method, url, body = transport.calls[0]
    assert (method, url) == ("POST", "http://models/ffmpeg/pano-views")
    assert body == {
        "mime": "image/png",
        "base64": base64.b64encode(_png_header()).decode(),
        "yaw_deg": 270.0,
        "pitch_deg": 15.0,
        "hfov_deg": 90.0,
        "aspect_ratio": "9:16",
    }


def test_observe_normalizes_png_artifact_and_rejects_other_media() -> None:
    done = {
        "stage": "done",
        "progress": 1.0,
        "message": "完成",
        "image": {"id": "a" * 32, "mime": "image/png", "bytes": 10, "sha256": "b" * 64},
    }
    transport = RecordingTransport(
        [
            _response(200, done),
            _response(200, {**done, "image": {**done["image"], "mime": "video/mp4"}}),
            _response(200, {"stage": "rendering", "progress": 0.5, "message": "裁切中"}),
        ]
    )
    provider = FFmpegPanoViewProvider("http://models", transport)
    handle = ProviderHandle(provider.plugin_id, 1, "a" * 32)

    observed = provider.observe(handle)
    assert observed.phase is GenerationPhase.SUCCEEDED
    assert observed.artifact.media_type == "image/png"
    assert observed.artifact.duration_seconds is None
    with pytest.raises(ModelProviderError):
        provider.observe(handle)
    assert provider.observe(handle).phase is GenerationPhase.RUNNING
    with pytest.raises(ModelProviderError):
        provider.observe(ProviderHandle("ffmpeg.video_frame", 1, "a" * 32))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PanoViewRequest(b"GIF89a", 0, 0, 90, "16:9"),
        lambda: PanoViewRequest(_png_header(), 360, 0, 90, "16:9"),
        lambda: PanoViewRequest(_png_header(), 0, 61, 90, "16:9"),
        lambda: PanoViewRequest(_png_header(), 0, 0, 19, "16:9"),
        lambda: PanoViewRequest(_png_header(), True, 0, 90, "16:9"),
        lambda: PanoViewRequest(_png_header(), math.nan, 0, 90, "16:9"),
        lambda: PanoViewRequest(_png_header(), 0, 0, 90, "1:1"),
    ],
)
def test_plugin_request_rejects_invalid_input(factory) -> None:
    with pytest.raises(ValueError):
        factory()


# ---------------------------------------------------------------- 媒体服务请求构造


def test_builder_writes_source_and_request(tmp_path: Path) -> None:
    record = TaskRecord("c" * 32, "ffmpeg_pano_view", "queued", 0.0, "等待", str(tmp_path))
    prepare_ffmpeg_pano_view(_payload(yaw_deg=0, mime="image/jpeg", base64=_jpeg_b64()))(record)

    request = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert request == {
        "schema": "pano_view_v1",
        "source": "source.jpg",
        "yaw_deg": 0.0,
        "pitch_deg": -10.0,
        "hfov_deg": 75.0,
        "aspect_ratio": "16:9",
    }
    assert (tmp_path / "source.jpg").read_bytes().startswith(b"\xff\xd8\xff")


def _jpeg_b64() -> str:
    return base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 16).decode()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"path": "/etc/passwd"}, None),
        ({"mime": "image/webp"}, "全景裁切只接受 PNG 或 JPEG。"),
        ({"mime": "image/jpeg"}, "图片字节与声明的 media type 不一致。"),
        ({"yaw_deg": 360}, "全景裁切 yaw 必须在 [0, 360) 度内。"),
        ({"yaw_deg": -0.5}, "全景裁切 yaw 必须在 [0, 360) 度内。"),
        ({"pitch_deg": -60.5}, "全景裁切 pitch 必须在 [-60, 60] 度内。"),
        ({"hfov_deg": 120.1}, "全景裁切水平视场角必须在 [20, 120] 度内。"),
        ({"hfov_deg": "90"}, "全景裁切水平视场角必须在 [20, 120] 度内。"),
        ({"aspect_ratio": "4:3"}, "全景裁切画幅只允许 16:9、9:16 或 2:1。"),
    ],
)
def test_builder_rejects_invalid_payload(overrides: dict, message: str | None) -> None:
    with pytest.raises(RequestError, match=None if message is None else re.escape(message)):
        prepare_ffmpeg_pano_view(_payload(**overrides))


def test_vertical_fov_uses_perspective_formula() -> None:
    assert vertical_fov(90, 2048, 1152) == pytest.approx(58.7155, abs=1e-3)
    assert vertical_fov(90, 1152, 2048) == pytest.approx(121.2845, abs=1e-3)
    assert vertical_fov(90, 2048, 1024) == pytest.approx(53.1301, abs=1e-3)
    assert {ratio: size for ratio, size in OUTPUT_SIZES.items()} == {
        "16:9": (2048, 1152),
        "9:16": (1152, 2048),
        "2:1": (2048, 1024),
    }


# ---------------------------------------------------------------- 真实 FFmpeg worker


def _needs_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("需要 FFmpeg")


# 经度色带：以全景正中为 0°，0° 红、90° 绿、180° 蓝、270° 黄，每条宽 90°。
_LONGITUDE_BANDS = (
    "st(0,floor(mod(X*360/W+225,360)/90))",
    "255*(eq(ld(0),0)+eq(ld(0),3))",
    "255*(eq(ld(0),1)+eq(ld(0),3))",
    "255*eq(ld(0),2)",
)
# 纬度色带：上半球红、下半球蓝。
_LATITUDE_BANDS = ("st(0,lt(Y,H/2))", "255*ld(0)", "0", "255*(1-ld(0))")


def _make_pano(path: Path, bands: tuple[str, ...], size: str = "2048x1024") -> bytes:
    store, red, green, blue = bands
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s={size},format=rgb24",
            "-vf",
            f"geq=r='{store};{red}':g='{store};{green}':b='{store};{blue}'",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return path.read_bytes()


def _render(directory: Path, content: bytes, suffix: str = ".png", **view) -> Path:
    directory.mkdir()
    (directory / f"source{suffix}").write_bytes(content)
    (directory / "request.json").write_text(
        json.dumps(
            {
                "schema": "pano_view_v1",
                "source": f"source{suffix}",
                "yaw_deg": 0.0,
                "pitch_deg": 0.0,
                "hfov_deg": 60.0,
                "aspect_ratio": "16:9",
                **view,
            }
        )
    )
    render(directory / "request.json")
    return directory / "output.png"


def _center_rgb(path: Path) -> tuple[int, int, int]:
    width, height = image_dimensions(path.read_bytes())
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout
    offset = ((height // 2) * width + width // 2) * 3
    return tuple(raw[offset : offset + 3])


@pytest.mark.parametrize(
    ("yaw", "expected"),
    [(0, (255, 0, 0)), (90, (0, 255, 0)), (180, (0, 0, 255)), (270, (255, 255, 0))],
)
def test_yaw_is_clockwise_from_panorama_center(tmp_path: Path, yaw: float, expected) -> None:
    _needs_ffmpeg()
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS)
    output = _render(tmp_path / "view", pano, yaw_deg=float(yaw))
    assert _center_rgb(output) == expected


@pytest.mark.parametrize(("pitch", "expected"), [(45, (255, 0, 0)), (-45, (0, 0, 255))])
def test_positive_pitch_looks_up(tmp_path: Path, pitch: float, expected) -> None:
    _needs_ffmpeg()
    pano = _make_pano(tmp_path / "pano.png", _LATITUDE_BANDS)
    output = _render(tmp_path / "view", pano, pitch_deg=float(pitch), hfov_deg=40.0)
    assert _center_rgb(output) == expected


@pytest.mark.parametrize(
    "aspect_ratio",
    [
        "16:9",
        pytest.param("9:16", marks=pytest.mark.slow),
        pytest.param("2:1", marks=pytest.mark.slow),
    ],
)
def test_output_long_edge_is_2048_and_deterministic(tmp_path: Path, aspect_ratio: str) -> None:
    _needs_ffmpeg()
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS)
    view = {"yaw_deg": 33.5, "pitch_deg": 12.25, "hfov_deg": 95.0, "aspect_ratio": aspect_ratio}
    first = _render(tmp_path / "first", pano, **view).read_bytes()
    second = _render(tmp_path / "second", pano, **view).read_bytes()

    assert image_dimensions(first) == OUTPUT_SIZES[aspect_ratio]
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert b"tIME" not in first and b"tEXt" not in first


def test_jpeg_panorama_with_one_pixel_slack_is_accepted(tmp_path: Path) -> None:
    _needs_ffmpeg()
    pano = _make_pano(tmp_path / "pano.jpg", _LONGITUDE_BANDS, size="2049x1024")
    red, green, blue = _center_rgb(_render(tmp_path / "view", pano, ".jpg", yaw_deg=90.0))
    assert green > 200 and red < 50 and blue < 50


@pytest.mark.parametrize("size", ["2048x1000", "1000x500"])
def test_worker_rejects_non_equirect_or_small_panorama(tmp_path: Path, size: str) -> None:
    _needs_ffmpeg()
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS, size=size)
    with pytest.raises(ValueError, match="2:1 等距柱状图"):
        _render(tmp_path / "view", pano)


@pytest.mark.parametrize(
    "view",
    [
        {"yaw_deg": 360.0},
        {"pitch_deg": 61.0},
        {"hfov_deg": 19.0},
        {"aspect_ratio": "1:1"},
        {"source": "../pano.png"},
        {"extra": 1},
    ],
)
def test_worker_revalidates_request(tmp_path: Path, view: dict) -> None:
    with pytest.raises(ValueError):
        _render(tmp_path / "view", _png_header(), **view)


# ---------------------------------------------------------------- 媒体服务闭环


@pytest.fixture
def pano_server(tmp_path: Path):
    server = ModelApiServer(
        ("127.0.0.1", 0), tmp_path / "state", enabled_services={"ffmpeg_pano_view"}
    )
    server.manager.start()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.manager.shutdown()
        server.server_close()
        thread.join(5)


def test_media_service_renders_view_end_to_end(tmp_path: Path, pano_server) -> None:
    _needs_ffmpeg()
    server, endpoint = pano_server
    provider = FFmpegPanoViewProvider(endpoint, UrllibTransport())
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS)

    handle = provider.submit(PanoViewContract(pano, 180, 0, 60, "16:9"))
    assert server.store.get(handle.external_id).kind == "ffmpeg_pano_view"
    observation = provider.observe(handle)
    deadline = time.monotonic() + 60
    while observation.phase in {GenerationPhase.QUEUED, GenerationPhase.RUNNING}:
        assert time.monotonic() < deadline
        time.sleep(0.05)
        observation = provider.observe(handle)
    assert observation.phase is GenerationPhase.SUCCEEDED, observation.message

    content = provider.read_artifact(handle, observation.artifact.artifact_id)
    assert hashlib.sha256(content).hexdigest() == observation.artifact.sha256
    assert image_dimensions(content) == (2048, 1152)
    output = tmp_path / "served.png"
    output.write_bytes(content)
    assert _center_rgb(output) == (0, 0, 255)


def test_media_service_rejects_invalid_geometry_and_unknown_task(pano_server) -> None:
    _, endpoint = pano_server
    transport = UrllibTransport()
    rejected = transport.request(
        "POST", endpoint + "/ffmpeg/pano-views", json_body=_payload(pitch_deg=75)
    )
    assert rejected.status == 422
    assert transport.request("PUT", endpoint + f"/ffmpeg/pano-views/{'d' * 32}/abort").status == 404
    disabled = transport.request(
        "POST", endpoint + "/ffmpeg/video-frames", json_body={"mime": "video/mp4"}
    )
    assert disabled.status == 404


def test_playground_crops_four_directions_through_media_service(
    tmp_path: Path, pano_server
) -> None:
    """Playground image.pano_view 经真实媒体服务裁出四个方向，产物是新 Asset。"""
    import asyncio
    from dataclasses import replace

    from core.playground.lifecycle import utc_timestamp
    from core.playground.models import AssetOrigin, RunPhase
    from core.playground.projection import serialize_snapshot
    from core.playground.service import PlaygroundService
    from core.playground.store import PlaygroundStore
    from tests.provider_factory import provider_registry

    _needs_ffmpeg()
    _, endpoint = pano_server
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS)
    (tmp_path / ".stories").mkdir()
    store = PlaygroundStore(tmp_path / ".stories" / ".playground")
    service = PlaygroundService(
        store,
        provider_registry(pano_view_provider=FFmpegPanoViewProvider(endpoint, UrllibTransport())),
    )
    holder = {}

    def ingest(previous):
        updated, asset = store.ingest_asset(
            previous,
            media_type="image/png",
            content=pano,
            origin_dir="imported",
            label="色带全景",
            origin=AssetOrigin("imported"),
            created_at=utc_timestamp(),
        )
        holder["asset"] = asset
        return replace(updated, revision=previous.revision + 1)

    store.commit(ingest)
    source = holder["asset"]
    actions = {
        item["id"]: item["allowed_actions"] for item in serialize_snapshot(service)["assets"]
    }
    assert "pano_view" in actions[source.id]

    async def crop(yaw: int):
        run = await service.submit_run(
            "image.pano_view",
            {
                "image_asset_id": source.id,
                "yaw_deg": yaw,
                "pitch_deg": 0,
                "hfov_deg": 60,
                "aspect_ratio": "16:9",
            },
            note=None,
        )
        deadline = time.monotonic() + 60
        while run.phase not in {RunPhase.SUCCEEDED, RunPhase.FAILED}:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.05)
            run = await service.refresh_run(run.id)
        return run

    expected = {0: (255, 0, 0), 90: (0, 255, 0), 180: (0, 0, 255), 270: (255, 255, 0)}
    for yaw, color in expected.items():
        run = asyncio.run(crop(yaw))
        assert run.phase is RunPhase.SUCCEEDED, run.message
        output, content = service.read_asset(run.output_asset_id)
        assert output.id != source.id
        assert output.display_name == f"色带全景-全景裁切-yaw{yaw}"
        assert image_dimensions(content) == (2048, 1152)
        path = tmp_path / f"yaw{yaw}.png"
        path.write_bytes(content)
        assert _center_rgb(path) == color
    assert service.read_asset(source.id)[1] == pano
