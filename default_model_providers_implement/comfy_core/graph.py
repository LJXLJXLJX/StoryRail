"""按 mode → steps/权重 → 注意力 → SelfLift 现场构造 H3 固定节点图。

模型名、采样器与 SelfLift 参数由部署端固定；请求只能选择 mode、20/8 步、Sage 开关与 SelfLift 开关，
不能提交任意节点、模型路径或输出路径。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SAVE_NODE_ID = "14"
SAMPLER_NODE_ID = "12"

# 两种 mode 共用 DaSiWa 权重；Turbo V2 已是独立 8 步权重，不再叠加 Turbo LoRA。
DIFFUSION_MODELS = {
    20: "minimax-h3\\DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors",
    8: "minimax-h3\\DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors",
}
DIFFUSION_LABELS = {20: "DaSiWa Hybrid V2", 8: "DaSiWa Hybrid Turbo V2"}
TEXT_ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax-h3\\minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax-h3\\minimax_h3_audio_vae_fp32.safetensors"
# SelfLift 节点只接受 latent_upscale_models 下的文件名。
LATENT_UPSCALER = "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"
SELFLIFT_FIXED_INPUTS = {
    "cfg": 1.0,
    "lowres_scale": 0.5,
    "rho": 0.0,
    "w_min": 0.5,
    "w_max": 1.0,
    "upscaler_model": LATENT_UPSCALER,
    "highres_tiling": False,
    "upscaler_unload": True,
}
FPS = 24

GRAPH_NODE_TYPES = frozenset(
    {
        "BasicGuider",
        "BasicScheduler",
        "CLIPLoader",
        "CreateVideo",
        "GetVideoComponents",
        "KSamplerSelect",
        "LoadAudio",
        "LoadImage",
        "LoadVideo",
        "MiniMaxH3ImageToVideo",
        "MiniMaxH3ReferenceToVideo",
        "ModelAttentionBackend",
        "RandomNoise",
        "SamplerCustomAdvanced",
        "SaveVideo",
        "SelfLiftH3Sampler",
        "UNETLoader",
        "VAEDecode",
        "VAEDecodeAudio",
        "VAELoader",
    }
)


@dataclass(frozen=True, slots=True)
class H3GraphInputs:
    mode: str
    prompt: str
    width: int
    height: int
    frame_count: int
    seed: int
    steps: int
    sage_attention: bool
    selflift: bool
    filename_prefix: str
    first_image: str | None
    last_image: str | None
    additional_images: tuple[str, ...] = ()
    reference_audios: tuple[str, ...] = ()
    reference_videos: tuple[str, ...] = ()
    include_audio: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"fl2va", "ref2va"}:
            raise ValueError("H3 mode 只允许 fl2va 或 ref2va。")
        if self.steps not in DIFFUSION_MODELS:
            raise ValueError("H3 steps 只允许 20 或 8。")
        if self.mode == "fl2va" and self.first_image is None and self.last_image is None:
            raise ValueError("H3 FL2VA workflow 至少需要一个时间锚点。")
        if self.mode == "ref2va" and not any(
            (
                self.first_image,
                self.last_image,
                self.additional_images,
                self.reference_audios,
                self.reference_videos,
            )
        ):
            raise ValueError("H3 Ref2VA workflow 至少需要一个媒体参考。")
        if self.mode == "fl2va" and (
            self.additional_images or self.reference_audios or self.reference_videos
        ):
            raise ValueError("FL2VA workflow 不接受附加参考图、参考音频或参考视频。")
        if len(self.additional_images) > 4 or any(not item for item in self.additional_images):
            raise ValueError("Ref2VA workflow 最多支持 4 张附加参考图。")
        if len(self.reference_audios) > 8 or any(not item for item in self.reference_audios):
            raise ValueError("Ref2VA workflow 最多支持 8 条参考音频。")
        if len(self.reference_videos) > 3 or any(not item for item in self.reference_videos):
            raise ValueError("Ref2VA workflow 最多支持 3 条参考视频。")
        # 潜变量 16 倍下采样后还要 2×2 patchify；FL2VA+SelfLift 实测 848×480、1280×720 失败。
        if self.width % 32 or self.height % 32:
            raise ValueError("H3 画布必须对齐到 32 像素网格。")
        if (self.frame_count - 5) % 17 or self.frame_count < 5:
            raise ValueError("H3 帧数必须是 17k+5。")


def sampler_name(steps: int, selflift: bool) -> str:
    # SelfLift 只支持 euler；20 步单阶段沿用已验证的 res_multistep。
    return "res_multistep" if steps == 20 and not selflift else "euler"


def build_h3_workflow(inputs: H3GraphInputs) -> dict[str, Any]:
    workflow: dict[str, Any] = {
        "3": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": DIFFUSION_MODELS[inputs.steps], "weight_dtype": "default"},
        },
        "4": {
            "class_type": "ModelAttentionBackend",
            "inputs": {
                "model": ["3", 0],
                "attention": "sage attention" if inputs.sage_attention else "default attention",
            },
        },
        "5": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": TEXT_ENCODER, "type": "minimax", "device": "default"},
        },
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "10": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": sampler_name(inputs.steps, inputs.selflift)},
        },
        "11": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": ["4", 0],
                "scheduler": "simple",
                "steps": inputs.steps,
                "denoise": 1.0,
            },
        },
        "13": {
            "class_type": "VAEDecode",
            "inputs": {"samples": [SAMPLER_NODE_ID, 0], "vae": ["6", 0]},
        },
        "15": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["13", 0], "fps": FPS, "bit_depth": 8},
        },
        SAVE_NODE_ID: {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["15", 0],
                "filename_prefix": inputs.filename_prefix,
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    if inputs.mode == "ref2va" or inputs.include_audio:
        workflow["16"] = {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}}
    if inputs.mode == "fl2va":
        _add_fl2va_conditioning(workflow, inputs)
    else:
        _add_ref2va_conditioning(workflow, inputs)
    if inputs.selflift:
        workflow[SAMPLER_NODE_ID] = {
            "class_type": "SelfLiftH3Sampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["7", 0],
                "negative": ["7", 0],
                "vae": ["6", 0],
                "latent_image": ["7", 1],
                "sampler": ["10", 0],
                "sigmas": ["11", 0],
                "seed": inputs.seed,
                "transition_step": inputs.steps // 2,
                **SELFLIFT_FIXED_INPUTS,
            },
        }
    else:
        workflow["8"] = {
            "class_type": "BasicGuider",
            "inputs": {"model": ["4", 0], "conditioning": ["7", 0]},
        }
        workflow["9"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": inputs.seed}}
        workflow[SAMPLER_NODE_ID] = {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["9", 0],
                "guider": ["8", 0],
                "sampler": ["10", 0],
                "sigmas": ["11", 0],
                "latent_image": ["7", 1],
            },
        }
    if inputs.include_audio:
        workflow["17"] = {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": [SAMPLER_NODE_ID, 0], "vae": ["16", 0]},
        }
        workflow["15"]["inputs"]["audio"] = ["17", 0]
    validate_workflow(workflow)
    return workflow


def _add_fl2va_conditioning(workflow: dict[str, Any], inputs: H3GraphInputs) -> None:
    node: dict[str, Any] = {
        "class_type": "MiniMaxH3ImageToVideo",
        "inputs": {
            "clip": ["5", 0],
            "vae": ["6", 0],
            "prompt": inputs.prompt,
            "width": inputs.width,
            "height": inputs.height,
            "length": inputs.frame_count,
        },
    }
    if inputs.first_image is not None:
        workflow["1"] = {"class_type": "LoadImage", "inputs": {"image": inputs.first_image}}
        node["inputs"]["first_frame"] = ["1", 0]
    if inputs.last_image is not None:
        workflow["2"] = {"class_type": "LoadImage", "inputs": {"image": inputs.last_image}}
        node["inputs"]["last_frame"] = ["2", 0]
    workflow["7"] = node


def _add_ref2va_conditioning(workflow: dict[str, Any], inputs: H3GraphInputs) -> None:
    node: dict[str, Any] = {
        "class_type": "MiniMaxH3ReferenceToVideo",
        "inputs": {
            "clip": ["5", 0],
            "vae": ["6", 0],
            "audio_vae": ["16", 0],
            "prompt": inputs.prompt,
            "width": inputs.width,
            "height": inputs.height,
            "length": inputs.frame_count,
            "ref_image_size": "match",
        },
    }
    # <Picture N>：首帧、尾帧在前，附加参考图随后，全部按 Core 给出的稳定顺序从 0 起编号。
    pictures: list[tuple[str, str]] = []
    if inputs.first_image is not None:
        pictures.append(("1", inputs.first_image))
    if inputs.last_image is not None:
        pictures.append(("2", inputs.last_image))
    pictures.extend(
        (str(30 + index), image) for index, image in enumerate(inputs.additional_images, start=1)
    )
    for picture_index, (node_id, image) in enumerate(pictures):
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": image}}
        node["inputs"][f"ref_images.ref_image_{picture_index}"] = [node_id, 0]
    for index, audio in enumerate(inputs.reference_audios):
        node_id = str(18 + index)
        workflow[node_id] = {"class_type": "LoadAudio", "inputs": {"audio": audio}}
        node["inputs"][f"ref_audios.ref_audio_{index}"] = [node_id, 0]
    # 官方 ref_video 输入是 24fps IMAGE 帧：LoadVideo 只产出 VIDEO 对象，须经 GetVideoComponents
    # 取 images；其 audio 输出刻意不接 ref_video_audios，参考视频不引入音轨。
    for index, video in enumerate(inputs.reference_videos, start=1):
        load_id, frames_id = str(40 + index), str(50 + index)
        workflow[load_id] = {"class_type": "LoadVideo", "inputs": {"file": video}}
        workflow[frames_id] = {
            "class_type": "GetVideoComponents",
            "inputs": {"video": [load_id, 0]},
        }
        node["inputs"][f"ref_videos.ref_video_{index - 1}"] = [frames_id, 0]
    workflow["7"] = node


def validate_workflow(workflow: dict[str, Any]) -> None:
    """只允许固定节点类型，且每条连线都指向图内节点，不留孤立的放大器或采样节点。"""
    referenced: set[str] = set()
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or set(node) != {"class_type", "inputs"}:
            raise ValueError(f"H3 workflow 节点 {node_id} 结构不合法。")
        if node["class_type"] not in GRAPH_NODE_TYPES or not isinstance(node["inputs"], dict):
            raise ValueError(f"H3 workflow 节点 {node_id} 类型不受允许。")
        for value in node["inputs"].values():
            if isinstance(value, list):
                if len(value) != 2 or value[0] not in workflow:
                    raise ValueError(f"H3 workflow 节点 {node_id} 引用了不存在的节点。")
                referenced.add(value[0])
    unused = set(workflow) - referenced - {SAVE_NODE_ID}
    if unused:
        raise ValueError(f"H3 workflow 含无用节点：{', '.join(sorted(unused))}")
