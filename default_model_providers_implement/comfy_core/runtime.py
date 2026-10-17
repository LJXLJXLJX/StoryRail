"""固定节点图所需的最小 Comfy Core 运行时：通用初始化与 H3 FL2VA/Ref2VA 执行。"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import math
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from default_model_providers_implement.h3_request import Request
from default_model_providers_implement.sampling_progress import SamplingProgress

from .graph import (
    DIFFUSION_LABELS,
    GRAPH_NODE_TYPES,
    SAVE_NODE_ID,
    H3GraphInputs,
    build_h3_workflow,
    sampler_name,
)

BUILTIN_NODE_FILES = (
    "nodes_audio.py",
    "nodes_custom_sampler.py",
    "nodes_minimax_h3.py",
    "nodes_model_advanced.py",
    "nodes_video.py",
)
# 唯一允许加载的外部 custom node；不扫描 custom_nodes 目录。
CUSTOM_NODE_PACKAGES = ("comfyui-SelfLift",)
REQUIRED_NODE_TYPES = GRAPH_NODE_TYPES


def resolve_saved_video(history: Any, output_root: Path) -> Path:
    """从 PromptExecutor 输出中解析并约束唯一的 MP4。"""
    if not isinstance(history, dict):
        raise RuntimeError("Comfy Core 没有返回合法执行记录。")
    outputs = history.get("outputs")
    node = outputs.get(SAVE_NODE_ID) if isinstance(outputs, dict) else None
    values = node.get("images") if isinstance(node, dict) else None
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise RuntimeError("Comfy Core SaveVideo 必须且只能产生一个视频。")
    value = values[0]
    if set(value) != {"filename", "subfolder", "type"}:
        raise RuntimeError("Comfy Core 视频输出描述包含未知字段。")
    filename = value.get("filename")
    subfolder = value.get("subfolder")
    if (
        not isinstance(filename, str)
        or not filename.lower().endswith(".mp4")
        or not isinstance(subfolder, str)
        or value.get("type") != "output"
    ):
        raise RuntimeError("Comfy Core 视频输出描述不合法。")
    relative = PurePosixPath(subfolder) / filename
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("Comfy Core 视频输出越过了受控输出区。")
    root = output_root.resolve(strict=True)
    result = (root / Path(*relative.parts)).resolve(strict=True)
    result.relative_to(root)
    if not result.is_file() or result.stat().st_size < 12:
        raise RuntimeError("Comfy Core 视频产物不存在或不完整。")
    with result.open("rb") as handle:
        header = handle.read(12)
    if header[4:8] != b"ftyp":
        raise RuntimeError("Comfy Core 产物不是真实 MP4。")
    return result


REFERENCE_VIDEO_FPS = 24


def reference_frame_indices(timestamps: list[float], fps: int = REFERENCE_VIDEO_FPS) -> list[int]:
    """按 1/fps 等间隔时间点为每个输出帧选取不晚于该时刻的最近源帧（恒定帧率重采样）。"""
    if not timestamps:
        raise RuntimeError("H3 参考视频没有可解码画面。")
    count = max(1, math.floor(timestamps[-1] * fps + 1e-6) + 1)
    indices: list[int] = []
    source = 0
    for output in range(count):
        target = output / fps
        while source + 1 < len(timestamps) and timestamps[source + 1] <= target + 1e-6:
            source += 1
        indices.append(source)
    return indices


def stage_reference_video(source: Path, target: Path) -> None:
    """把参考视频转为 24fps、无音轨的 H.264 MP4；官方节点按 24fps 解释 ref_video 帧。"""
    import av  # noqa: PLC0415

    with av.open(str(source)) as container:
        frames = []
        timestamps: list[float] = []
        for frame in container.decode(container.streams.video[0]):
            if frame.time is None:
                raise RuntimeError("H3 参考视频缺少可用时间戳。")
            frames.append(frame.to_ndarray(format="rgb24"))
            timestamps.append(float(frame.time))
    if not frames:
        raise RuntimeError("H3 参考视频没有可解码画面。")
    indices = reference_frame_indices([value - timestamps[0] for value in timestamps])
    height, width = frames[0].shape[:2]
    temporary = target.with_name(f".{target.name}.tmp")
    with av.open(str(temporary), mode="w", format="mp4") as output:
        stream = output.add_stream("libx264", rate=REFERENCE_VIDEO_FPS)
        stream.width = width - width % 2
        stream.height = height - height % 2
        stream.pix_fmt = "yuv420p"
        for index in indices:
            picture = av.VideoFrame.from_ndarray(
                frames[index][: stream.height, : stream.width], format="rgb24"
            )
            for packet in stream.encode(picture):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    os.replace(temporary, target)


class _ProgressServer:
    def __init__(self, report: Callable[[float, str], None]) -> None:
        self._report = report
        self.reset()

    def reset(self, request_id: str | None = None, *, mode: str = "fl2va") -> None:
        """清除任务状态，并隔离常驻进程中迟到的旧任务事件。"""
        if mode not in {"fl2va", "ref2va"}:
            raise ValueError("Comfy Core H3 mode 不受支持。")
        self.client_id = request_id
        self.mode = mode
        self.last_node_id: str | None = None
        self._sampling = SamplingProgress(f"H3 {mode.upper()}")
        self._progress = 0.0

    def send_sync(self, event: str, data: Any, client_id: str | None = None) -> None:
        if not isinstance(data, dict):
            return
        event_id = data.get("prompt_id") or client_id
        if self.client_id is not None and event_id is not None and event_id != self.client_id:
            return
        if event == "executing":
            node = data.get("node")
            if node is None:
                return
            node_id = str(node)
            self.last_node_id = node_id
            mode_name = self.mode.upper()
            stages = {
                "5": (0.14, "Comfy Core 正在加载并编码文本条件。"),
                "7": (
                    0.16,
                    "Comfy Core 正在建立 Ref2VA 参考条件。"
                    if self.mode == "ref2va"
                    else "Comfy Core 正在建立首尾帧视频条件。",
                ),
                "12": (0.20, f"Comfy Core 正在执行 H3 {mode_name} 采样。"),
                "13": (0.93, "Comfy Core 正在执行视频 VAE 解码。"),
                "17": (0.95, "Comfy Core 正在执行音频 VAE 解码。"),
                "15": (0.96, "Comfy Core 正在建立视频流。"),
                "14": (0.97, "Comfy Core 正在编码 MP4。"),
            }
            stage = stages.get(node_id)
            if stage is not None and stage[0] >= self._progress:
                self._progress = stage[0]
                self._report(*stage)
            return
        if event != "progress":
            return
        progress_node = data.get("node")
        node_id = str(progress_node) if progress_node is not None else self.last_node_id
        if node_id != "12" or self._progress >= 0.93:
            return
        value, maximum = data.get("value"), data.get("max")
        if (
            isinstance(value, bool)
            or isinstance(maximum, bool)
            or not isinstance(value, (int, float))
            or not isinstance(maximum, (int, float))
            or not math.isfinite(value)
            or not math.isfinite(maximum)
            or maximum < 1
            or int(value) != value
            or int(maximum) != maximum
            or not 0 <= value <= maximum
        ):
            return
        completed, total = int(value), int(maximum)
        message = self._sampling.update(completed, total)
        if message:
            self._progress = max(self._progress, 0.20 + completed / total * 0.72)
            self._report(self._progress, message)


def _install_progress_hook(comfy_utils: Any, server: _ProgressServer) -> None:
    """把 Comfy 节点内部的 ProgressBar 事件接到最小运行时。"""

    def hook(
        value: int | float,
        total: int | float,
        preview_image: Any,
        prompt_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        del preview_image
        server.send_sync(
            "progress",
            {"value": value, "max": total, "node": node_id, "prompt_id": prompt_id},
        )

    comfy_utils.set_progress_bar_global_hook(hook)


class ComfyCoreRuntime:
    """最小 Comfy Core 进程：只加载子类声明的固定节点；进程退出是最终内存回收边界。

    子类声明 ``BUILTIN_NODE_FILES``、``CUSTOM_NODE_PACKAGES`` 与 ``REQUIRED_NODE_TYPES``，
    并实现 ``_create_progress_server`` 与各自的 ``run``。
    """

    BUILTIN_NODE_FILES: tuple[str, ...] = ()
    CUSTOM_NODE_PACKAGES: tuple[str, ...] = ()
    REQUIRED_NODE_TYPES: frozenset[str] = frozenset()
    PROBE_SAGE_ATTENTION = False

    def __init__(self, comfy_root: Path, work_root: Path, report: Callable[[float, str], None]):
        self.comfy_root = comfy_root.resolve(strict=True)
        self.work_root = work_root.resolve()
        self.input_root = self.work_root / "input"
        self.output_root = self.work_root / "output"
        self.temp_root = self.work_root / "temp"
        self.report = report
        self.execution: Any = None
        self.nodes: Any = None
        self.folder_paths: Any = None
        self.executor: Any = None
        self.progress_server: _ProgressServer | None = None
        self.sage_unavailable_reason: str | None = None

    def initialize(self) -> None:
        if not (self.comfy_root / "nodes.py").is_file():
            raise RuntimeError("STORYRAIL_COMFYUI_ROOT 不是有效的 ComfyUI 目录。")
        self.report(0.02, "正在初始化最小 Comfy Core。")
        sys.path.insert(0, str(self.comfy_root))
        os.environ.setdefault("MIMALLOC_PURGE_DELAY", "0")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("DO_NOT_TRACK", "1")

        with contextlib.redirect_stdout(sys.stderr):
            import comfy_aimdo.control  # noqa: PLC0415
            from comfy.cli_args import args, enables_dynamic_vram  # noqa: PLC0415

            if enables_dynamic_vram():
                headroom = None if args.reserve_vram is None else int(args.reserve_vram * 1024**3)
                try:
                    comfy_aimdo.control.init(
                        simple_vram_headroom=headroom,
                        nvml_pressure=not args.disable_nvml_pressure,
                    )
                except TypeError:
                    try:
                        comfy_aimdo.control.init(simple_vram_headroom=headroom)
                    except TypeError:
                        comfy_aimdo.control.init()

            # 顺序与固定 ComfyUI main.py 一致：cuda allocator 必须先于 torch/模型管理导入。
            importlib.import_module("cuda_malloc")
            execution = importlib.import_module("execution")
            folder_paths = importlib.import_module("folder_paths")
            nodes = importlib.import_module("nodes")
            memory_management = importlib.import_module("comfy.memory_management")
            model_management = importlib.import_module("comfy.model_management")
            model_patcher = importlib.import_module("comfy.model_patcher")
            comfy_utils = importlib.import_module("comfy.utils")

            dynamic_supported = args.enable_dynamic_vram or (
                model_management.torch_version_numeric >= (2, 8)
            )
            if dynamic_supported and (
                args.enable_dynamic_vram
                or (
                    enables_dynamic_vram()
                    and model_management.is_nvidia()
                    and not model_management.is_wsl()
                )
            ):
                try:
                    initialized = comfy_aimdo.control.init_devices(
                        (device.index, int(args.vram_headroom * 1024**3))
                        for device in model_management.get_all_torch_devices()
                    )
                except TypeError:
                    initialized = comfy_aimdo.control.init_devices(
                        device.index for device in model_management.get_all_torch_devices()
                    )
                if initialized:
                    model_patcher.CoreModelPatcher = model_patcher.ModelPatcherDynamic
                    memory_management.aimdo_enabled = True
                    comfy_aimdo.control.set_log_info()

            self.input_root.mkdir(parents=True, exist_ok=True)
            self.output_root.mkdir(parents=True, exist_ok=True)
            self.temp_root.mkdir(parents=True, exist_ok=True)
            folder_paths.set_input_directory(str(self.input_root))
            folder_paths.set_output_directory(str(self.output_root))
            folder_paths.set_temp_directory(str(self.temp_root))

            asyncio.run(nodes.init_public_apis())
            extras = self.comfy_root / "comfy_extras"
            for filename in self.BUILTIN_NODE_FILES:
                path = extras / filename
                if not path.is_file() or not asyncio.run(
                    nodes.load_custom_node(str(path), module_parent="comfy_extras")
                ):
                    raise RuntimeError(f"无法加载固定 Comfy Core 节点：{filename}")
            for package in self.CUSTOM_NODE_PACKAGES:
                path = self.comfy_root / "custom_nodes" / package
                if not (path / "__init__.py").is_file() or not asyncio.run(
                    nodes.load_custom_node(str(path))
                ):
                    raise RuntimeError(f"无法加载固定 custom node：{package}")
            missing = sorted(self.REQUIRED_NODE_TYPES - nodes.NODE_CLASS_MAPPINGS.keys())
            if missing:
                raise RuntimeError(f"Comfy Core 缺少固定节点：{', '.join(missing)}")

            ram_total_gb = model_management.total_ram / 1024.0
            cache_args = {
                "lru": args.cache_lru,
                "ram": min(10.0, max(2.0, ram_total_gb * 0.10)),
                "ram_inactive": min(128.0, ram_total_gb),
            }
            self.progress_server = self._create_progress_server()
            _install_progress_hook(comfy_utils, self.progress_server)
            self.executor = execution.PromptExecutor(
                self.progress_server,
                cache_type=execution.CacheType.RAM_PRESSURE,
                cache_args=cache_args,
            )
            self.execution = execution
            self.nodes = nodes
            self.folder_paths = folder_paths
            if self.PROBE_SAGE_ATTENTION:
                self.sage_unavailable_reason = _probe_sage_attention()
        self.report(
            0.10,
            "最小 Comfy Core 已就绪。"
            if self.sage_unavailable_reason is None
            else f"最小 Comfy Core 已就绪；SageAttention 不可用：{self.sage_unavailable_reason}",
        )

    def _create_progress_server(self) -> Any:
        raise NotImplementedError


class ComfyCoreH3Runtime(ComfyCoreRuntime):
    """固定 FL2VA / Ref2VA 图；同 mode 任务复用进程。"""

    BUILTIN_NODE_FILES = BUILTIN_NODE_FILES
    CUSTOM_NODE_PACKAGES = CUSTOM_NODE_PACKAGES
    REQUIRED_NODE_TYPES = REQUIRED_NODE_TYPES
    PROBE_SAGE_ATTENTION = True

    def _create_progress_server(self) -> _ProgressServer:
        return _ProgressServer(self.report)

    def run(self, request_id: str, request: Request) -> str:
        """执行一次固定图，返回实际生效参数摘要；产物写到 request.output_path。"""
        if (
            request.mode not in {"fl2va", "ref2va"}
            or (
                request.mode == "fl2va"
                and request.first_image is None
                and request.last_image is None
            )
            or (
                request.mode == "ref2va"
                and not any(
                    (
                        request.first_image,
                        request.last_image,
                        request.additional_images,
                        request.reference_audios,
                        request.reference_videos,
                    )
                )
            )
        ):
            raise RuntimeError("Comfy Core H3 收到了不属于它的请求。")
        if request.cfg != 1.0:
            raise RuntimeError("Comfy Core H3 只支持 cfg=1。")
        if self.executor is None or self.execution is None:
            raise RuntimeError("Comfy Core 尚未初始化。")
        if self.progress_server is None:
            raise RuntimeError("Comfy Core 进度回调尚未初始化。")
        if request.sage_attention and self.sage_unavailable_reason is not None:
            # 不静默回退到默认注意力，也不把任务标成 Sage 成功。
            raise RuntimeError(
                f"请求了 SageAttention，但当前环境不可用：{self.sage_unavailable_reason}"
            )
        self.progress_server.reset(request_id, mode=request.mode)

        relative_dir = Path("storyrail") / request_id
        staged_dir = self.input_root / relative_dir
        staged_dir.mkdir(parents=True, exist_ok=False)
        first_name = (
            f"first{request.first_image.suffix.lower()}"
            if request.first_image is not None
            else None
        )
        last_name = (
            f"last{request.last_image.suffix.lower()}" if request.last_image is not None else None
        )
        if request.first_image is not None and first_name is not None:
            shutil.copyfile(request.first_image, staged_dir / first_name)
        if request.last_image is not None and last_name is not None:
            shutil.copyfile(request.last_image, staged_dir / last_name)
        additional_names = tuple(
            f"additional-{index}{image.suffix.lower()}"
            for index, image in enumerate(request.additional_images, start=1)
        )
        for image, image_name in zip(request.additional_images, additional_names, strict=True):
            shutil.copyfile(image, staged_dir / image_name)
        audio_names = tuple(
            f"reference-{index}{audio.suffix.lower()}"
            for index, audio in enumerate(request.reference_audios, start=1)
        )
        for audio, audio_name in zip(request.reference_audios, audio_names, strict=True):
            shutil.copyfile(audio, staged_dir / audio_name)
        video_names = tuple(
            f"reference-video-{index}.mp4"
            for index, _video in enumerate(request.reference_videos, start=1)
        )
        for video, video_name in zip(request.reference_videos, video_names, strict=True):
            stage_reference_video(video, staged_dir / video_name)
        output_dir = self.output_root / "storyrail"
        output_dir.mkdir(parents=True, exist_ok=True)
        for old in output_dir.glob(f"{request_id}_*.mp4"):
            old.unlink()

        workflow = build_h3_workflow(
            H3GraphInputs(
                mode=request.mode,
                prompt=request.prompt,
                width=request.width,
                height=request.height,
                frame_count=request.frame_count,
                seed=request.seed,
                steps=request.steps,
                sage_attention=request.sage_attention,
                selflift=request.selflift,
                filename_prefix=f"storyrail/{request_id}",
                first_image=(relative_dir / first_name).as_posix() if first_name else None,
                last_image=(relative_dir / last_name).as_posix() if last_name else None,
                additional_images=tuple(
                    (relative_dir / image_name).as_posix() for image_name in additional_names
                ),
                reference_audios=tuple(
                    (relative_dir / audio_name).as_posix() for audio_name in audio_names
                ),
                reference_videos=tuple(
                    (relative_dir / video_name).as_posix() for video_name in video_names
                ),
                include_audio=request.save_audio,
            )
        )
        display_mode = request.mode.upper()
        self.report(0.12, f"正在校验固定 H3 {display_mode} 节点图。")
        try:
            with contextlib.redirect_stdout(sys.stderr):
                valid, error, outputs, node_errors = asyncio.run(
                    self.execution.validate_prompt(request_id, workflow, None)
                )
                if not valid:
                    raise RuntimeError(
                        f"固定 H3 {display_mode} 节点图校验失败：{error}; {node_errors}"
                    )
                self.executor.execute(
                    workflow,
                    request_id,
                    extra_data={"client_id": request_id},
                    execute_outputs=outputs,
                )
            if not self.executor.success:
                detail = (
                    self.executor.status_messages[-1] if self.executor.status_messages else None
                )
                raise RuntimeError(_execution_error(display_mode, request, detail))
            source = resolve_saved_video(self.executor.history_result, self.output_root)
            request.output_path.unlink(missing_ok=True)
            shutil.copyfile(source, request.output_path)
            self.report(0.99, f"Comfy Core H3 {display_mode} 产物已回收。")
            return effective_summary(request)
        finally:
            shutil.rmtree(staged_dir, ignore_errors=True)
            for generated in output_dir.glob(f"{request_id}_*"):
                if generated.is_file():
                    generated.unlink()


def _probe_sage_attention() -> str | None:
    """返回 SageAttention 不可用的原因；可用时返回 None。Triton 缓存必须可写。"""
    cache = os.environ.get("TRITON_CACHE_DIR")
    if cache:
        try:
            root = Path(cache)
            root.mkdir(parents=True, exist_ok=True)
            probe = root / f".storyrail-probe-{os.getpid()}"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError as exc:
            return f"Triton 缓存不可写（{exc}）"
    try:
        attention = importlib.import_module("comfy.ldm.modules.attention")
    except ImportError as exc:
        return f"无法导入 Comfy attention 模块（{exc}）"
    if attention.get_attention_function("sage", None) is None:
        return "sageattention 未安装或无法导入"
    return None


def _format_seconds(frame_count: int) -> str:
    return f"{frame_count / 24:.3f}".rstrip("0").rstrip(".")


def effective_summary(request: Request) -> str:
    """请求值与实际生效值：画布、帧数、权重、采样器、注意力后端与 SelfLift。"""
    sampling = (
        f"SelfLift {request.steps // 2}+{request.steps - request.steps // 2} 步"
        if request.selflift
        else f"单阶段 {request.steps} 步"
    )
    return (
        f"H3 {request.mode.upper()} · {request.width}×{request.height} · "
        f"{request.frame_count} 帧 24fps（{_format_seconds(request.frame_count)} 秒，"
        f"请求 {request.duration_seconds:g} 秒）· {DIFFUSION_LABELS[request.steps]} · "
        f"{sampler_name(request.steps, request.selflift)} {sampling} · "
        f"{'Sage' if request.sage_attention else '默认'}注意力"
    )


def _execution_error(display_mode: str, request: Request, detail: Any) -> str:
    text = str(detail)[:800]
    if "out of memory" in text.lower() or "outofmemory" in text.lower():
        return (
            f"H3 {display_mode} CUDA 显存不足（OOM）：{request.width}×{request.height}、"
            f"{request.frame_count} 帧、{request.steps} 步、"
            f"SelfLift {'开' if request.selflift else '关'}。"
            "不会自动降级；可调低分辨率档位或时长后重试。"
        )
    return f"Comfy Core H3 {display_mode} 执行失败：{text}"
