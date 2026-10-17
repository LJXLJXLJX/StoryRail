from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from default_model_providers_implement import agy_worker


def test_prompt_preserves_operation_ratio_and_ordered_inputs(tmp_path: Path) -> None:
    images = [tmp_path / "base.png", tmp_path / "reference.png"]
    prompt = agy_worker._prompt("edit", "改为雨夜", "9:16", images)
    assert "编辑第一张底图" in prompt
    assert "目标画幅：9:16" in prompt
    assert prompt.index(str(images[0])) < prompt.index(str(images[1]))
    assert prompt.endswith("只返回生成图片的绝对路径，不要附加说明。")


def test_result_path_rejects_outside_controlled_roots(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    output_root = tmp_path / "agy-output"
    outside = tmp_path / "outside.png"
    task_dir.mkdir()
    output_root.mkdir()
    outside.write_bytes(b"image")
    with (
        patch.dict("os.environ", {"STORYRAIL_AGY_OUTPUT_ROOT": str(output_root)}),
        pytest.raises(RuntimeError, match="受控输出目录"),
    ):
        agy_worker._result_path({"response": str(outside)}, task_dir=task_dir, started_ns=0)


def test_generate_accepts_fresh_image_even_if_later_cli_step_fails(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    output_root = tmp_path / "agy-output"
    task_dir.mkdir()
    output_root.mkdir()
    generated = output_root / "generated.jpg"

    def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        Image.new("RGB", (160, 100), "red").save(generated, format="JPEG")
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"status": "ERROR", "response": str(generated)}),
            stderr="model capacity unavailable after image generation",
        )

    with (
        patch.dict("os.environ", {"STORYRAIL_AGY_OUTPUT_ROOT": str(output_root)}),
        patch("default_model_providers_implement.agy_worker.subprocess.run", side_effect=run),
    ):
        agy_worker.generate(task_dir, "generate", "红色圆形", "16:9", [])

    with Image.open(task_dir / "output.png") as output:
        assert output.size[0] * 9 == output.size[1] * 16
    agent = (task_dir / ".agents/agents/storyrail-image/agent.md").read_text()
    assert "excludeDefaultComponents: true" in agent
    assert "generate_image" in agent
    assert "run_shell_command" not in agent
