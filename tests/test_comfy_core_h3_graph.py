from __future__ import annotations

import itertools
import json
import tempfile
import unittest
from pathlib import Path

from default_model_providers_implement.comfy_core.graph import (
    DIFFUSION_MODELS,
    LATENT_UPSCALER,
    SAMPLER_NODE_ID,
    SAVE_NODE_ID,
    H3GraphInputs,
    build_h3_workflow,
    validate_workflow,
)
from default_model_providers_implement.comfy_core.runtime import _execution_error, effective_summary
from default_model_providers_implement.h3_request import parse_request


def _inputs(mode: str, steps: int, sage: bool, selflift: bool, **extra) -> H3GraphInputs:
    values = {
        "mode": mode,
        "prompt": "<Picture 1> A red car moves toward the flag.",
        "width": 1280,
        "height": 704,
        "frame_count": 73,
        "seed": 7,
        "steps": steps,
        "sage_attention": sage,
        "selflift": selflift,
        "filename_prefix": "storyrail/task",
        "first_image": "storyrail/task/first.png",
        "last_image": None,
    }
    values.update(extra)
    return H3GraphInputs(**values)


def _types(workflow: dict) -> dict[str, str]:
    return {node_id: node["class_type"] for node_id, node in workflow.items()}


class ComfyCoreH3GraphTests(unittest.TestCase):
    def test_every_combination_builds_a_closed_graph(self) -> None:
        for mode, steps, sage, selflift in itertools.product(
            ("fl2va", "ref2va"), (20, 8), (True, False), (True, False)
        ):
            with self.subTest(mode=mode, steps=steps, sage=sage, selflift=selflift):
                workflow = build_h3_workflow(_inputs(mode, steps, sage, selflift))
                types = _types(workflow)
                self.assertEqual(workflow["3"]["inputs"]["unet_name"], DIFFUSION_MODELS[steps])
                self.assertEqual(
                    workflow["4"]["inputs"],
                    {
                        "model": ["3", 0],
                        "attention": "sage attention" if sage else "default attention",
                    },
                )
                self.assertEqual(
                    workflow["11"]["inputs"],
                    {"model": ["4", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0},
                )
                self.assertEqual(
                    types["7"],
                    "MiniMaxH3ImageToVideo" if mode == "fl2va" else "MiniMaxH3ReferenceToVideo",
                )
                self.assertNotIn("MiniMaxH3SigmaShift", types.values())
                self.assertEqual(types["17"], "VAEDecodeAudio")
                self.assertEqual(workflow["15"]["inputs"]["fps"], 24)
                self.assertEqual(types[SAVE_NODE_ID], "SaveVideo")

    def test_twenty_steps_single_stage_uses_res_multistep(self) -> None:
        workflow = build_h3_workflow(_inputs("fl2va", 20, True, False))
        self.assertEqual(workflow["10"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(workflow[SAMPLER_NODE_ID]["class_type"], "SamplerCustomAdvanced")
        self.assertEqual(workflow["8"]["class_type"], "BasicGuider")
        self.assertEqual(workflow["9"]["inputs"], {"noise_seed": 7})
        self.assertNotIn(LATENT_UPSCALER, json.dumps(workflow), "关闭 SelfLift 时不能保留放大器")

    def test_selflift_uses_euler_and_half_transition(self) -> None:
        for steps, transition in ((20, 10), (8, 4)):
            with self.subTest(steps=steps):
                workflow = build_h3_workflow(_inputs("ref2va", steps, False, True))
                sampler = workflow[SAMPLER_NODE_ID]
                self.assertEqual(sampler["class_type"], "SelfLiftH3Sampler")
                self.assertEqual(workflow["10"]["inputs"]["sampler_name"], "euler")
                self.assertEqual(sampler["inputs"]["transition_step"], transition)
                self.assertEqual(sampler["inputs"]["seed"], 7)
                self.assertEqual(sampler["inputs"]["upscaler_model"], LATENT_UPSCALER)
                self.assertEqual(
                    {
                        key: sampler["inputs"][key]
                        for key in (
                            "cfg",
                            "lowres_scale",
                            "rho",
                            "w_min",
                            "w_max",
                            "highres_tiling",
                            "upscaler_unload",
                        )
                    },
                    {
                        "cfg": 1.0,
                        "lowres_scale": 0.5,
                        "rho": 0.0,
                        "w_min": 0.5,
                        "w_max": 1.0,
                        "highres_tiling": False,
                        "upscaler_unload": True,
                    },
                )
                self.assertEqual(sampler["inputs"]["positive"], ["7", 0])
                self.assertEqual(sampler["inputs"]["latent_image"], ["7", 1])
                self.assertEqual(sampler["inputs"]["vae"], ["6", 0])
                # SelfLift 自带噪声与 guider；单阶段节点不能残留。
                self.assertNotIn("8", workflow)
                self.assertNotIn("9", workflow)

    def test_turbo_single_stage_uses_euler_without_lora(self) -> None:
        workflow = build_h3_workflow(_inputs("fl2va", 8, True, False))
        self.assertEqual(workflow["10"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(workflow[SAMPLER_NODE_ID]["class_type"], "SamplerCustomAdvanced")
        self.assertIn("TurboV2", workflow["3"]["inputs"]["unet_name"])
        self.assertFalse(any("Lora" in node["class_type"] for node in workflow.values()))

    def test_ref2va_numbers_pictures_audio_and_video_in_stable_order(self) -> None:
        workflow = build_h3_workflow(
            _inputs(
                "ref2va",
                20,
                True,
                True,
                last_image="storyrail/task/last.png",
                additional_images=("storyrail/task/additional-1.png",),
                reference_audios=("storyrail/task/reference-1.wav",),
                reference_videos=("storyrail/task/reference-video-1.mp4",),
            )
        )
        inputs = workflow["7"]["inputs"]
        self.assertEqual(inputs["ref_images.ref_image_0"], ["1", 0])
        self.assertEqual(inputs["ref_images.ref_image_1"], ["2", 0])
        self.assertEqual(inputs["ref_images.ref_image_2"], ["31", 0])
        self.assertEqual(inputs["ref_audios.ref_audio_0"], ["18", 0])
        self.assertEqual(inputs["ref_videos.ref_video_0"], ["51", 0])
        self.assertEqual(inputs["audio_vae"], ["16", 0])
        self.assertNotIn("ref_video_audios.ref_video_audio_0", inputs)

    def test_ref2va_builds_without_images_when_audio_is_present(self) -> None:
        workflow = build_h3_workflow(
            _inputs(
                "ref2va",
                20,
                True,
                False,
                first_image=None,
                last_image=None,
                reference_audios=("storyrail/task/reference-1.wav",),
            )
        )
        inputs = workflow["7"]["inputs"]
        self.assertEqual(workflow["7"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertFalse(any(key.startswith("ref_images.") for key in inputs))
        self.assertEqual(inputs["ref_audios.ref_audio_0"], ["18", 0])
        self.assertFalse(any(key.startswith("ref_videos.") for key in inputs))
        self.assertEqual(inputs["audio_vae"], ["16", 0])
        with self.assertRaisesRegex(ValueError, "至少需要一个媒体参考"):
            _inputs("ref2va", 20, True, False, first_image=None, last_image=None)

    def test_ref2va_reference_audios_stop_at_official_node_maximum(self) -> None:
        # 官方 MiniMaxH3ReferenceToVideo 的 ref_audios Autogrow 只声明 ref_audio_0..2。
        audios = tuple(f"storyrail/task/reference-{index}.wav" for index in range(1, 4))
        inputs = build_h3_workflow(_inputs("ref2va", 20, True, False, reference_audios=audios))[
            "7"
        ]["inputs"]
        self.assertEqual(
            sorted(key for key in inputs if key.startswith("ref_audios.")),
            [f"ref_audios.ref_audio_{index}" for index in range(3)],
        )
        with self.assertRaisesRegex(ValueError, "最多支持 3 条参考音频"):
            _inputs("ref2va", 20, True, False, reference_audios=(*audios, "extra.wav"))

    def test_fl2va_rejects_reference_inputs_and_missing_anchor(self) -> None:
        with self.assertRaisesRegex(ValueError, "不接受"):
            _inputs("fl2va", 20, True, True, reference_audios=("a.wav",))
        with self.assertRaisesRegex(ValueError, "时间锚点"):
            _inputs("fl2va", 20, True, True, first_image=None)
        with self.assertRaisesRegex(ValueError, "20 或 8"):
            _inputs("fl2va", 12, True, True)
        # 1280×720 在真机 FL2VA+SelfLift 上 reshape 失败：画布必须是 32 的倍数。
        with self.assertRaisesRegex(ValueError, "32 像素"):
            _inputs("fl2va", 20, True, True, height=720)
        with self.assertRaisesRegex(ValueError, "17k"):
            _inputs("fl2va", 20, True, True, frame_count=72)

    def test_fl2va_without_generated_audio_drops_audio_nodes(self) -> None:
        workflow = build_h3_workflow(_inputs("fl2va", 20, True, False, include_audio=False))
        self.assertNotIn("16", workflow)
        self.assertNotIn("17", workflow)
        self.assertNotIn("audio", workflow["15"]["inputs"])

    def test_validator_rejects_unknown_types_dangling_links_and_orphans(self) -> None:
        workflow = build_h3_workflow(_inputs("fl2va", 20, True, False))
        with self.assertRaisesRegex(ValueError, "类型不受允许"):
            validate_workflow({**workflow, "99": {"class_type": "PythonEval", "inputs": {}}})
        broken = json.loads(json.dumps(workflow))
        broken["13"]["inputs"]["vae"] = ["404", 0]
        with self.assertRaisesRegex(ValueError, "不存在"):
            validate_workflow(broken)
        with self.assertRaisesRegex(ValueError, "无用节点"):
            validate_workflow(
                {**workflow, "99": {"class_type": "VAELoader", "inputs": {"vae_name": "x"}}}
            )


class EffectiveSummaryTests(unittest.TestCase):
    def _request(self, **overrides):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "first.png").write_bytes(b"x")
        value = {
            "schema": "storyrail_h3_runtime_request_v5",
            "mode": "fl2va",
            "prompt": "A red car.",
            "width": 1920,
            "height": 1088,
            "duration_seconds": 15,
            "seed": 1,
            "steps": 8,
            "cfg": 1.0,
            "sage_attention": True,
            "selflift": True,
            "save_audio": True,
            "first_image": "first.png",
            "last_image": None,
            "additional_images": [],
            "reference_audios": [],
            "reference_videos": [],
            **overrides,
        }
        (root / "request.json").write_text(json.dumps(value), encoding="utf-8")
        return parse_request(root / "request.json")

    def test_summary_reports_requested_and_effective_values(self) -> None:
        request = self._request()
        self.assertEqual(request.frame_count, 362)
        summary = effective_summary(request)
        self.assertIn("1920×1088", summary)
        self.assertIn("362 帧 24fps（15.083 秒，请求 15 秒）", summary)
        self.assertIn("DaSiWa Hybrid Turbo V2", summary)
        self.assertIn("SelfLift 4+4 步", summary)
        self.assertIn("Sage注意力", summary)

    def test_out_of_memory_is_reported_without_downgrade(self) -> None:
        message = _execution_error(
            "FL2VA", self._request(), "torch.OutOfMemoryError: CUDA out of memory"
        )
        self.assertIn("OOM", message)
        self.assertIn("1920×1088", message)
        self.assertIn("不会自动降级", message)


if __name__ == "__main__":
    unittest.main()
