"""Core 本机确定性媒体工具：执行器生命周期、真实 FFmpeg 渲染与 Playground 闭环。"""

from __future__ import annotations

import array
import hashlib
import json
import math
import subprocess
import threading
import time
from pathlib import Path

import pytest

from core.media_tools import install_local_media_tools
from core.media_tools.executor import LocalMediaExecutor
from core.media_tools.ffmpeg import FFmpeg, MediaToolCancelled
from core.media_tools.providers import (
    LocalAnimaticProvider,
    LocalAudioRemixProvider,
    LocalFinalAssemblyProvider,
    LocalPanoViewProvider,
    LocalVideoFrameProvider,
)
from core.media_tools.tools import PANO_OUTPUT_SIZES, pano_vertical_fov, render_pano_view
from core.model_providers.boundary import GenerationPhase, ModelProviderError, ProviderHandle
from core.model_providers.contracts import (
    AnimaticClip,
    AnimaticNarration,
    AnimaticRequest,
    AssemblyClip,
    AssemblyNarration,
    AudioRemixRequest,
    FinalAssemblyRequest,
    PanoViewRequest,
    VideoFrameRequest,
    image_dimensions,
)
from core.model_providers.registry import ProviderRegistry

_TERMINAL = {GenerationPhase.SUCCEEDED, GenerationPhase.FAILED, GenerationPhase.CANCELLED}


def _wait(observe, timeout: float = 60.0):
    observation = observe()
    deadline = time.monotonic() + timeout
    while observation.phase not in _TERMINAL:
        assert time.monotonic() < deadline, observation.message
        time.sleep(0.02)
        observation = observe()
    return observation


@pytest.fixture
def executor(tmp_path: Path):
    value = LocalMediaExecutor(tmp_path / "media-tools")
    yield value
    value.close()


# ---------------------------------------------------------------- 执行器


def _write(directory: Path, content: bytes = b"output") -> Path:
    path = directory / "output.bin"
    path.write_bytes(content)
    return path


def test_success_describes_artifact_and_serves_bytes(executor: LocalMediaExecutor) -> None:
    def job(directory, cancel, progress):
        progress(0.5, "一半")
        return _write(directory, b"hello")

    task = executor.submit("light", job, media_type="image/png", failure_code="x_failed")
    observation = _wait(lambda: executor.observe(task))

    assert observation.phase is GenerationPhase.SUCCEEDED
    assert observation.progress == 1.0
    assert observation.artifact.artifact_id == task
    assert observation.artifact.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert observation.artifact.byte_count == 5
    assert observation.artifact.duration_seconds is None
    assert executor.read_artifact(task, task) == b"hello"
    with pytest.raises(ModelProviderError):
        executor.read_artifact(task, "other")


def test_failure_reports_tool_error_code(executor: LocalMediaExecutor) -> None:
    def job(directory, cancel, progress):
        raise ValueError("源视频不能完整解码。")

    task = executor.submit("light", job, media_type="image/png", failure_code="frame_failed")
    observation = _wait(lambda: executor.observe(task))

    assert observation.phase is GenerationPhase.FAILED
    assert observation.error_code == "frame_failed"
    assert "源视频不能完整解码" in observation.message
    assert observation.retryable is False


def test_cancel_running_and_queued_tasks(executor: LocalMediaExecutor) -> None:
    started = threading.Event()
    ran_second = threading.Event()

    def blocking(directory, cancel, progress):
        started.set()
        while not cancel.is_set():
            time.sleep(0.01)
        raise MediaToolCancelled

    def second(directory, cancel, progress):
        ran_second.set()
        return _write(directory)

    first = executor.submit("heavy", blocking, media_type="video/mp4", failure_code="x")
    queued = executor.submit("heavy", second, media_type="video/mp4", failure_code="x")
    assert started.wait(5)

    assert executor.cancel(queued).phase is GenerationPhase.CANCELLED
    executor.cancel(first)
    assert _wait(lambda: executor.observe(first)).phase is GenerationPhase.CANCELLED
    time.sleep(0.1)
    assert not ran_second.is_set()


def test_restart_loses_tasks_and_clears_work_directory(tmp_path: Path) -> None:
    root = tmp_path / "media-tools"
    first = LocalMediaExecutor(root)
    task = first.submit(
        "light", lambda d, c, p: _write(d), media_type="image/png", failure_code="x"
    )
    _wait(lambda: first.observe(task))
    first.close()

    second = LocalMediaExecutor(root)
    try:
        observation = second.observe(task)
        assert observation.phase is GenerationPhase.FAILED
        assert observation.error_code == "local_task_lost"
        assert observation.retryable is True
        assert list(root.iterdir()) == []
    finally:
        second.close()


def test_finished_tasks_expire_after_retention(tmp_path: Path) -> None:
    executor = LocalMediaExecutor(tmp_path / "media-tools", retention_seconds=0)
    try:
        old = executor.submit("light", lambda d, c, p: _write(d), media_type="x", failure_code="x")
        _wait(lambda: executor.observe(old))
        executor.submit("light", lambda d, c, p: _write(d), media_type="x", failure_code="x")
        assert executor.observe(old).error_code == "local_task_lost"
        assert not (tmp_path / "media-tools" / old).exists()
    finally:
        executor.close()


def test_handle_must_belong_to_the_tool(executor: LocalMediaExecutor) -> None:
    provider = LocalVideoFrameProvider(executor, FFmpeg("ffmpeg", "ffprobe"))
    with pytest.raises(ModelProviderError) as error:
        provider.observe(ProviderHandle("ffmpeg.pano_view", 1, "a" * 32))
    assert error.value.code == "invalid_handle"
    with pytest.raises(TypeError):
        provider.submit(object())


def test_install_registers_five_tools_only_when_ffmpeg_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(FFmpeg, "discover", classmethod(lambda cls: None))
    registry = ProviderRegistry()
    assert install_local_media_tools(registry, tmp_path / "missing") is None
    assert not any(registry.available(tool) for tool in ("final_assembly", "pano_view"))

    monkeypatch.setattr(FFmpeg, "discover", classmethod(lambda cls: cls("ffmpeg", "ffprobe")))
    executor = install_local_media_tools(registry, tmp_path / "present")
    try:
        assert executor is not None
        tools = ("final_assembly", "animatic", "video_frame", "pano_view", "audio_remix")
        assert all(registry.available(tool) for tool in tools)
        assert registry.resolve("final_assembly").plugin_id == "ffmpeg.final-assembly"
    finally:
        executor.close()


# ---------------------------------------------------------------- 真实 FFmpeg


@pytest.fixture
def ff() -> FFmpeg:
    value = FFmpeg.discover()
    if value is None:
        pytest.skip("需要 FFmpeg")
    return value


def _ffmpeg(*arguments: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=True,
        capture_output=True,
        timeout=60,
    )


def _color_clip(path: Path, color: str, duration: float, *, audio: bool = True) -> bytes:
    sources = ["-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d={duration}"]
    if audio:
        sources += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:a", "aac"]
    _ffmpeg(*sources, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    return path.read_bytes()


def _tone(path: Path, frequency: int, duration: float, rate: int = 48000) -> bytes:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate={rate}:duration={duration}",
        "-c:a",
        "pcm_s16le",
        str(path),
    )
    return path.read_bytes()


def _probe(content: bytes, directory: Path) -> dict:
    path = directory / f"probe-{hashlib.sha256(content).hexdigest()[:8]}"
    path.write_bytes(content)
    return json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


def _run(provider, request):
    handle = provider.submit(request)
    observation = _wait(lambda: provider.observe(handle))
    assert observation.phase is GenerationPhase.SUCCEEDED, observation.message
    content = provider.read_artifact(handle, observation.artifact.artifact_id)
    assert hashlib.sha256(content).hexdigest() == observation.artifact.sha256
    return observation, content


def test_ffmpeg_run_terminates_process_on_cancel(ff: FFmpeg, tmp_path: Path) -> None:
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(MediaToolCancelled):
        ff.run(
            ["-re", "-f", "lavfi", "-i", "anullsrc", "-t", "60", "-f", "null", "-"],
            cancel,
            log=tmp_path / "run.log",
        )
    assert time.monotonic() - started < 5


def test_final_assembly_renders_seam_blend_and_late_narration(
    ff: FFmpeg, executor: LocalMediaExecutor, tmp_path: Path
) -> None:
    clips = [
        _color_clip(tmp_path / f"{color}.mp4", color, 0.8) for color in ("red", "green", "blue")
    ]
    narration = _tone(tmp_path / "narration.wav", 700, 1.2)
    request = FinalAssemblyRequest(
        tuple(
            AssemblyClip(content, transition, duration)
            for content, transition, duration in zip(
                clips, (None, None, "seam_blend"), (0.8, 0.8, 1.2), strict=True
            )
        ),
        (AssemblyNarration(narration, 2),),
        "16:9",
        0.2,
    )

    observation, content = _run(LocalFinalAssemblyProvider(executor, ff), request)

    # 0.8 + 0.8 + 1.2 − 0.2 融合 = 2.6；旁白从第 3 段起点 1.4 秒开始，1.2 秒内结束。
    probe = _probe(content, tmp_path)
    assert {item["codec_type"] for item in probe["streams"]} == {"video", "audio"}
    assert float(probe["format"]["duration"]) == pytest.approx(2.6, abs=0.05)
    assert observation.artifact.duration_seconds == pytest.approx(
        float(probe["format"]["duration"]), abs=1e-5
    )
    video = next(item for item in probe["streams"] if item["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1920, 1080)


def test_final_assembly_crops_silent_clip_to_two_to_one(
    ff: FFmpeg, executor: LocalMediaExecutor, tmp_path: Path
) -> None:
    clip = _color_clip(tmp_path / "red.mp4", "red", 0.5, audio=False)
    request = FinalAssemblyRequest((AssemblyClip(clip, None, 0.5),), (), "2:1")

    _observation, content = _run(LocalFinalAssemblyProvider(executor, ff), request)

    video = next(
        item for item in _probe(content, tmp_path)["streams"] if item["codec_type"] == "video"
    )
    assert (video["width"], video["height"]) == (1920, 960)


def test_animatic_renders_stills_with_narration(
    ff: FFmpeg, executor: LocalMediaExecutor, tmp_path: Path
) -> None:
    stills = []
    for color in ("red", "green", "blue"):
        path = tmp_path / f"{color}.png"
        _ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=320x180", "-frames:v", "1", str(path))
        stills.append(path.read_bytes())
    narration = _tone(tmp_path / "narration.wav", 700, 1.2)
    request = AnimaticRequest(
        tuple(
            AnimaticClip(content, transition, duration)
            for content, transition, duration in zip(
                stills, (None, None, "seam_blend"), (0.8, 0.8, 1.2), strict=True
            )
        ),
        (AnimaticNarration(narration, 2),),
        "9:16",
        0.2,
    )

    observation, content = _run(LocalAnimaticProvider(executor, ff), request)

    probe = _probe(content, tmp_path)
    assert {item["codec_type"] for item in probe["streams"]} == {"video", "audio"}
    assert float(probe["format"]["duration"]) == pytest.approx(2.6, abs=0.05)
    video = next(item for item in probe["streams"] if item["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert observation.artifact.media_type == "video/mp4"


def _center_rgb(content: bytes, directory: Path) -> tuple[int, int, int]:
    width, height = image_dimensions(content)
    path = directory / f"center-{hashlib.sha256(content).hexdigest()[:8]}.png"
    path.write_bytes(content)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout
    offset = ((height // 2) * width + width // 2) * 3
    return tuple(raw[offset : offset + 3])


def test_video_frame_selects_index_and_reports_range(
    ff: FFmpeg, executor: LocalMediaExecutor, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=64x64:r=5:d=0.6",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=64x64:r=5:d=0.4",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(source),
    )
    provider = LocalVideoFrameProvider(executor, ff)

    _observation, first = _run(provider, VideoFrameRequest(source.read_bytes(), 0))
    _observation, last = _run(provider, VideoFrameRequest(source.read_bytes(), 4))
    red, _green, blue = _center_rgb(first, tmp_path)
    assert red > 200 and blue < 60
    red, _green, blue = _center_rgb(last, tmp_path)
    assert blue > 200 and red < 60

    handle = provider.submit(VideoFrameRequest(source.read_bytes(), 5))
    failed = _wait(lambda: provider.observe(handle))
    assert failed.phase is GenerationPhase.FAILED
    assert "0-4" in failed.message


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
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=black:s={size},format=rgb24",
        "-vf",
        f"geq=r='{store};{red}':g='{store};{green}':b='{store};{blue}'",
        "-frames:v",
        "1",
        str(path),
    )
    return path.read_bytes()


def _view(ff: FFmpeg, directory: Path, pano: bytes, **view) -> bytes:
    directory.mkdir()
    geometry = {"yaw_deg": 0.0, "pitch_deg": 0.0, "hfov_deg": 60.0, "aspect_ratio": "16:9"}
    request = PanoViewRequest(pano, **{**geometry, **view})
    return render_pano_view(ff, request, directory, threading.Event(), lambda *_: None).read_bytes()


def test_pano_vertical_fov_uses_perspective_formula() -> None:
    assert pano_vertical_fov(90, 2048, 1152) == pytest.approx(58.7155, abs=1e-3)
    assert pano_vertical_fov(90, 1152, 2048) == pytest.approx(121.2845, abs=1e-3)
    assert pano_vertical_fov(90, 2048, 1024) == pytest.approx(53.1301, abs=1e-3)
    assert PANO_OUTPUT_SIZES == {"16:9": (2048, 1152), "9:16": (1152, 2048), "2:1": (2048, 1024)}


@pytest.mark.parametrize(
    ("yaw", "expected"),
    [(0, (255, 0, 0)), (90, (0, 255, 0)), (180, (0, 0, 255)), (270, (255, 255, 0))],
)
def test_pano_yaw_is_clockwise_from_panorama_center(ff, tmp_path: Path, yaw, expected) -> None:
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS)
    assert _center_rgb(_view(ff, tmp_path / "view", pano, yaw_deg=float(yaw)), tmp_path) == expected


@pytest.mark.parametrize(("pitch", "expected"), [(45, (255, 0, 0)), (-45, (0, 0, 255))])
def test_pano_positive_pitch_looks_up(ff, tmp_path: Path, pitch, expected) -> None:
    pano = _make_pano(tmp_path / "pano.png", _LATITUDE_BANDS)
    output = _view(ff, tmp_path / "view", pano, pitch_deg=float(pitch), hfov_deg=40.0)
    assert _center_rgb(output, tmp_path) == expected


@pytest.mark.parametrize(
    "aspect_ratio",
    [
        "16:9",
        pytest.param("9:16", marks=pytest.mark.slow),
        pytest.param("2:1", marks=pytest.mark.slow),
    ],
)
def test_pano_output_long_edge_is_2048_and_deterministic(ff, tmp_path: Path, aspect_ratio) -> None:
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS)
    view = {"yaw_deg": 33.5, "pitch_deg": 12.25, "hfov_deg": 95.0, "aspect_ratio": aspect_ratio}
    first = _view(ff, tmp_path / "first", pano, **view)
    second = _view(ff, tmp_path / "second", pano, **view)

    assert image_dimensions(first) == PANO_OUTPUT_SIZES[aspect_ratio]
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    assert b"tIME" not in first and b"tEXt" not in first


def test_pano_jpeg_with_one_pixel_slack_is_accepted(ff, tmp_path: Path) -> None:
    pano = _make_pano(tmp_path / "pano.jpg", _LONGITUDE_BANDS, size="2049x1024")
    red, green, blue = _center_rgb(_view(ff, tmp_path / "view", pano, yaw_deg=90.0), tmp_path)
    assert green > 200 and red < 50 and blue < 50


@pytest.mark.parametrize("size", ["2048x1000", "1000x500"])
def test_pano_request_rejects_non_equirect_or_small_panorama(ff, tmp_path: Path, size) -> None:
    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS, size=size)
    with pytest.raises(ValueError, match="2:1 等距柱状图"):
        PanoViewRequest(pano, 0.0, 0.0, 60.0, "16:9")


def test_audio_remix_keeps_video_and_applies_gain_windows(
    ff: FFmpeg, executor: LocalMediaExecutor, tmp_path: Path
) -> None:
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x180:r=24:d=1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:sample_rate=44100:duration=1",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(tmp_path / "input.mp4"),
    )
    request = AudioRemixRequest(
        (tmp_path / "input.mp4").read_bytes(),
        _tone(tmp_path / "voice.wav", 440, 1, 44100),
        _tone(tmp_path / "background.wav", 880, 1, 44100),
        -18,
        -100,
        voice_gain_start_seconds=0.5,
        voice_gain_end_seconds=1.0,
        background_gain_start_seconds=0.0,
        background_gain_end_seconds=1.0,
    )

    _observation, content = _run(LocalAudioRemixProvider(executor, ff), request)

    probe = _probe(content, tmp_path)
    assert {item["codec_type"] for item in probe["streams"]} == {"video", "audio"}
    assert float(probe["format"]["duration"]) == pytest.approx(1.0, abs=0.08)
    output = tmp_path / "remixed.mp4"
    output.write_bytes(content)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a:0", "-ac", "1"]
        + ["-ar", "44100", "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    samples = array.array("f")
    samples.frombytes(raw)

    def rms(start: float, end: float) -> float:
        values = samples[round(start * 44100) : round(end * 44100)]
        return math.sqrt(sum(value * value for value in values) / len(values))

    assert rms(0.1, 0.4) > rms(0.65, 0.9) * 5


def test_playground_crops_four_directions_with_local_pano_tool(ff, tmp_path: Path) -> None:
    """Playground image.pano_view 经本机工具裁出四个方向，产物是新 Asset。"""
    import asyncio
    from dataclasses import replace

    from core.playground.lifecycle import utc_timestamp
    from core.playground.models import AssetOrigin, RunPhase
    from core.playground.projection import serialize_snapshot
    from core.playground.service import PlaygroundService
    from core.playground.store import PlaygroundStore
    from tests.provider_factory import provider_registry

    pano = _make_pano(tmp_path / "pano.png", _LONGITUDE_BANDS)
    (tmp_path / ".stories").mkdir()
    executor = LocalMediaExecutor(tmp_path / "media-tools")
    store = PlaygroundStore(tmp_path / ".stories" / ".playground")
    service = PlaygroundService(
        store, provider_registry(pano_view_provider=LocalPanoViewProvider(executor, ff))
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

    try:
        expected = {0: (255, 0, 0), 90: (0, 255, 0), 180: (0, 0, 255), 270: (255, 255, 0)}
        for yaw, color in expected.items():
            run = asyncio.run(crop(yaw))
            assert run.phase is RunPhase.SUCCEEDED, run.message
            output, content = service.read_asset(run.output_asset_id)
            assert output.id != source.id
            assert output.display_name == f"色带全景-全景裁切-yaw{yaw}"
            assert image_dimensions(content) == (2048, 1152)
            assert _center_rgb(content, tmp_path) == color
        assert service.read_asset(source.id)[1] == pano
    finally:
        executor.close()
