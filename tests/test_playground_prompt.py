"""PG5-T4：Playground 提示词与项目提示词的逐字一致性与工具覆盖。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "integrations/agent_launcher/PROMPT.md"
PLAYGROUND_PROMPT = ROOT / "integrations/agent_launcher/PLAYGROUND_PROMPT.md"

TOOLS = (
    "playground_capabilities",
    "playground_submit",
    "playground_runs",
    "playground_manage_run",
    "playground_assets",
)


def _dialogue_rule_paragraph() -> str:
    paragraphs = [item.strip() for item in PROMPT.read_text(encoding="utf-8").split("\n\n")]
    return next(item for item in paragraphs if item.startswith("StoryRail 的旁白是独立 TTS 音频"))


def test_playground_prompt_copies_dialogue_rule_verbatim() -> None:
    assert _dialogue_rule_paragraph() in PLAYGROUND_PROMPT.read_text(encoding="utf-8")


def test_playground_prompt_mentions_all_tools() -> None:
    text = PLAYGROUND_PROMPT.read_text(encoding="utf-8")
    for name in TOOLS:
        assert name in text, name


def test_playground_prompt_states_scope_limits_and_manual_calls() -> None:
    text = PLAYGROUND_PROMPT.read_text(encoding="utf-8")
    assert "当前工作区只连接 StoryRail Playground：与任何故事项目无关的模型实验台。" in text
    for capability in ("minimax_h3.fl2va", "minimax_h3.ref2va", "seedvr2_7b_sharp_fp8.upscale"):
        assert capability in text
    assert "最多 4 个" in text
    assert "python /app/client.py list" in text
    assert "python /app/client.py 文件名" in text
    assert "复制到项目" in text


def test_playground_prompt_makes_video_cap_a_hard_stop() -> None:
    """PG6-T2 D4：视频类 run 上限必须是独立的硬性停止条款，而不是附带说明。"""

    text = PLAYGROUND_PROMPT.read_text(encoding="utf-8")
    assert "**算力保护（硬性停止条件，优先于用户的批量要求）**" in text
    assert "最多 4 个" in text
    assert "提交第 5 个之前**必须停下来**" in text
    assert "都**不**构成这里的同意" in text
    assert "只有听到排队情况后的当轮明确答复才算" in text
