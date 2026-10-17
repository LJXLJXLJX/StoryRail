"""Qwen Image 2.1（NoctQ V4）固定节点图与最小 Comfy Core 执行。

模型、文本编码器、VAE、采样器、调度器、参考图像素预算与 KV cache 由部署端固定；请求只能提供
提示词、负向提示词、画布宽高、步数、CFG、seed 与任务目录中的输入图。生图与改图走同一张图：
输入图按顺序进入 ``TextEncodeQwenImage21`` 的 ``image_N``（模型模板给每张图加 ``<imageN>`` 前缀，
改图时第一张是底图）；画布始终来自 ``EmptyLatentImage`` 的宽高，不跟随第一张图的尺寸。
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from default_model_providers_implement.qwen_image_request import QwenImageRequest
from default_model_providers_implement.sampling_progress import SamplingProgress

from .runtime import ComfyCoreRuntime

DIFFUSION_MODEL = "qwen\\NoctQ_V4_int8_convrot.safetensors"
DIFFUSION_LABEL = "NoctQ V4"
TEXT_ENCODER = "qwen\\qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen\\qwen_image_2.1_vae_bf16.safetensors"
SAMPLER = "euler"
SCHEDULER = "simple"
# 参考图送入文本编码器与 VAE 前缩放到约 1024² 像素（保持比例、32 对齐），与官方模板默认一致。
REFERENCE_RESOLUTION = 1024
ENCODE_NODE_ID = "5"
SAMPLER_NODE_ID = "7"
DECODE_NODE_ID = "8"
SAVE_NODE_ID = "9"
MAX_IMAGES = 5

GRAPH_NODE_TYPES = frozenset(
    {
        "CLIPLoader",
        "EmptyLatentImage",
        "KSampler",
        "LoadImage",
        "QwenImage21Cache",
        "SaveImage",
        "TextEncodeQwenImage21",
        "UNETLoader",
        "VAEDecode",
        "VAELoader",
    }
)


@dataclass(frozen=True, slots=True)
class QwenImageGraphInputs:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    cfg: float
    seed: int
    filename_prefix: str
    images: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("Qwen 图片 prompt 不能为空。")
        if self.width % 32 or self.height % 32:
            raise ValueError("Qwen 图片画布必须对齐到 32 像素网格。")
        if len(self.images) > MAX_IMAGES or any(not item for item in self.images):
            raise ValueError(f"Qwen 图片最多支持 {MAX_IMAGES} 张输入图。")


def build_qwen_image_workflow(inputs: QwenImageGraphInputs) -> dict[str, Any]:
    encode: dict[str, Any] = {
        "class_type": "TextEncodeQwenImage21",
        "inputs": {
            "clip": ["3", 0],
            "vae": ["4", 0],
            "prompt": inputs.prompt,
            "negative_prompt": inputs.negative_prompt,
            "resolution": REFERENCE_RESOLUTION,
        },
    }
    workflow: dict[str, Any] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": DIFFUSION_MODEL, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "QwenImage21Cache",
            "inputs": {"model": ["1", 0], "device": "auto", "dtype": "default"},
        },
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": TEXT_ENCODER, "type": "qwen_image", "device": "default"},
        },
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        ENCODE_NODE_ID: encode,
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": inputs.width, "height": inputs.height, "batch_size": 1},
        },
        SAMPLER_NODE_ID: {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "seed": inputs.seed,
                "steps": inputs.steps,
                "cfg": inputs.cfg,
                "sampler_name": SAMPLER,
                "scheduler": SCHEDULER,
                "positive": [ENCODE_NODE_ID, 0],
                "negative": [ENCODE_NODE_ID, 1],
                "latent_image": ["6", 0],
                "denoise": 1.0,
            },
        },
        DECODE_NODE_ID: {
            "class_type": "VAEDecode",
            "inputs": {"samples": [SAMPLER_NODE_ID, 0], "vae": ["4", 0]},
        },
        SAVE_NODE_ID: {
            "class_type": "SaveImage",
            "inputs": {"images": [DECODE_NODE_ID, 0], "filename_prefix": inputs.filename_prefix},
        },
    }
    for index, image in enumerate(inputs.images, start=1):
        node_id = str(10 + index)
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": image}}
        encode["inputs"][f"images.image_{index}"] = [node_id, 0]
    validate_workflow(workflow)
    return workflow


def validate_workflow(workflow: dict[str, Any]) -> None:
    """只允许固定节点类型，且每条连线都指向图内节点，不留孤立节点。"""
    referenced: set[str] = set()
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or set(node) != {"class_type", "inputs"}:
            raise ValueError(f"Qwen 图片 workflow 节点 {node_id} 结构不合法。")
        if node["class_type"] not in GRAPH_NODE_TYPES or not isinstance(node["inputs"], dict):
            raise ValueError(f"Qwen 图片 workflow 节点 {node_id} 类型不受允许。")
        for value in node["inputs"].values():
            if isinstance(value, list):
                if len(value) != 2 or value[0] not in workflow:
                    raise ValueError(f"Qwen 图片 workflow 节点 {node_id} 引用了不存在的节点。")
                referenced.add(value[0])
    unused = set(workflow) - referenced - {SAVE_NODE_ID}
    if unused:
        raise ValueError(f"Qwen 图片 workflow 含无用节点：{', '.join(sorted(unused))}")


def resolve_saved_image(history: Any, output_root: Path) -> Path:
    """从 PromptExecutor 输出中解析并约束唯一的 PNG。"""
    if not isinstance(history, dict):
        raise RuntimeError("Comfy Core 没有返回合法执行记录。")
    outputs = history.get("outputs")
    node = outputs.get(SAVE_NODE_ID) if isinstance(outputs, dict) else None
    values = node.get("images") if isinstance(node, dict) else None
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise RuntimeError("Comfy Core SaveImage 必须且只能产生一张图片。")
    value = values[0]
    if set(value) != {"filename", "subfolder", "type"}:
        raise RuntimeError("Comfy Core 图片输出描述包含未知字段。")
    filename, subfolder = value.get("filename"), value.get("subfolder")
    if (
        not isinstance(filename, str)
        or not filename.lower().endswith(".png")
        or not isinstance(subfolder, str)
        or value.get("type") != "output"
    ):
        raise RuntimeError("Comfy Core 图片输出描述不合法。")
    relative = PurePosixPath(subfolder) / filename
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("Comfy Core 图片输出越过了受控输出区。")
    root = output_root.resolve(strict=True)
    result = (root / Path(*relative.parts)).resolve(strict=True)
    result.relative_to(root)
    with result.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Comfy Core 产物不是真实 PNG。")
    return result


class _QwenProgressServer:
    """把固定图的节点执行与采样步回调映射成单调进度；忽略其它任务的迟到事件。"""

    STAGES = {
        "3": (0.12, "Comfy Core 正在加载 Qwen 文本编码器。"),
        ENCODE_NODE_ID: (0.14, "Comfy Core 正在编码提示词与输入图。"),
        SAMPLER_NODE_ID: (0.20, "Comfy Core 正在执行 Qwen Image 采样。"),
        DECODE_NODE_ID: (0.94, "Comfy Core 正在执行 VAE 解码。"),
        SAVE_NODE_ID: (0.97, "Comfy Core 正在写出 PNG。"),
    }

    def __init__(self, report: Callable[[float, str], None]) -> None:
        self._report = report
        self.reset()

    def reset(self, request_id: str | None = None) -> None:
        self.client_id = request_id
        self.last_node_id: str | None = None
        self._sampling = SamplingProgress("Qwen Image")
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
            self.last_node_id = str(node)
            stage = self.STAGES.get(self.last_node_id)
            if stage is not None and stage[0] >= self._progress:
                self._progress = stage[0]
                self._report(*stage)
            return
        if event != "progress":
            return
        node = data.get("node")
        node_id = str(node) if node is not None else self.last_node_id
        if node_id != SAMPLER_NODE_ID or self._progress >= 0.94:
            return
        value, maximum = data.get("value"), data.get("max")
        if (
            isinstance(value, bool)
            or isinstance(maximum, bool)
            or not isinstance(value, int | float)
            or not isinstance(maximum, int | float)
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


def effective_summary(request: QwenImageRequest) -> str:
    return (
        f"Qwen Image 2.1 · {DIFFUSION_LABEL} · {request.width}×{request.height} · "
        f"{len(request.images)} 张输入图 · {SAMPLER}/{SCHEDULER} {request.steps} 步 · "
        f"CFG {request.cfg:g} · seed {request.seed}"
    )


class ComfyCoreQwenImageRuntime(ComfyCoreRuntime):
    """只加载 ComfyUI 内置 Qwen 节点；相邻 Qwen 任务复用进程。"""

    BUILTIN_NODE_FILES = ("nodes_qwen.py",)
    REQUIRED_NODE_TYPES = GRAPH_NODE_TYPES

    def _create_progress_server(self) -> _QwenProgressServer:
        return _QwenProgressServer(self.report)

    def run(self, request_id: str, request: QwenImageRequest) -> str:
        if self.executor is None or self.execution is None or self.progress_server is None:
            raise RuntimeError("Comfy Core 尚未初始化。")
        self.progress_server.reset(request_id)
        relative_dir = Path("storyrail") / request_id
        staged_dir = self.input_root / relative_dir
        staged_dir.mkdir(parents=True, exist_ok=False)
        names = tuple(
            f"image-{index}{image.suffix.lower()}"
            for index, image in enumerate(request.images, start=1)
        )
        for image, name in zip(request.images, names, strict=True):
            shutil.copyfile(image, staged_dir / name)
        output_dir = self.output_root / "storyrail"
        output_dir.mkdir(parents=True, exist_ok=True)
        for old in output_dir.glob(f"{request_id}_*.png"):
            old.unlink()
        workflow = build_qwen_image_workflow(
            QwenImageGraphInputs(
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                width=request.width,
                height=request.height,
                steps=request.steps,
                cfg=request.cfg,
                seed=request.seed,
                filename_prefix=f"storyrail/{request_id}",
                images=tuple((relative_dir / name).as_posix() for name in names),
            )
        )
        self.report(0.11, "正在校验固定 Qwen Image 节点图。")
        try:
            with contextlib.redirect_stdout(sys.stderr):
                valid, error, outputs, node_errors = asyncio.run(
                    self.execution.validate_prompt(request_id, workflow, None)
                )
                if not valid:
                    raise RuntimeError(f"固定 Qwen Image 节点图校验失败：{error}; {node_errors}")
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
                raise RuntimeError(_execution_error(request, detail))
            source = resolve_saved_image(self.executor.history_result, self.output_root)
            request.output_path.unlink(missing_ok=True)
            shutil.copyfile(source, request.output_path)
            self.report(0.99, "Comfy Core Qwen Image 产物已回收。")
            return effective_summary(request)
        finally:
            shutil.rmtree(staged_dir, ignore_errors=True)
            for generated in output_dir.glob(f"{request_id}_*"):
                if generated.is_file():
                    generated.unlink()


def _execution_error(request: QwenImageRequest, detail: Any) -> str:
    text = str(detail)[:800]
    if "out of memory" in text.lower() or "outofmemory" in text.lower():
        return (
            f"Qwen Image CUDA 显存不足（OOM）：{request.width}×{request.height}、"
            f"{len(request.images)} 张输入图、{request.steps} 步、CFG {request.cfg:g}。"
            "不会自动降级；可调小画布或减少输入图后重试。"
        )
    return f"Comfy Core Qwen Image 执行失败：{text}"
