"""一致性资源与所有 Agent 入口的交付约束；不作为模型遵守规则的证明。"""

from pathlib import Path

from core.director_proposals.professional_contracts import (
    CONTRACTS,
    consistency_instruction,
    read_contract,
)
from integrations.storyrail_mcp.app import create_server


def test_shared_rule_reaches_launcher_and_generic_mcp_without_copy_button():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "integrations/agent_launcher/PROMPT.md").read_text()
    instructions = create_server(None).instructions
    shared = consistency_instruction()
    assert shared in launcher
    assert shared in instructions
    web_instruction = (root / "web/src/director_workspace/consistency_instruction.ts").read_text()
    assert shared in web_instruction
    for text in (launcher, instructions):
        assert "read_professional_contract" in text
        assert "shared/storyrail-consistency-review/SKILL.md" in text
        assert "只读校对不写入" in text
    assert "当前没有 UI 内的“刷新凭据”按钮" in launcher
    assert "停止当前 Agent 启动终端" in launcher
    assert "只重启 Core、gateway 或 MCP 不会刷新项目连接" in launcher
    assert "当前没有 UI 内的刷新凭据功能" in instructions
    assert "停止当前 Agent 启动终端" in instructions
    assert "独立 TTS 音频" in launcher
    assert "绝不能把剧本旁白、解说词或 narrator 文本写入" in launcher
    assert "预留后期主旁白音频叠加通道" in launcher
    assert "只有 `scene.driver` 为 `narration` 时再加" in launcher
    assert "除 `<d>` 台词外无其它人类语音" in launcher
    assert "导演方案写明的配乐与音乐入点就是明确要求" in launcher
    assert set(CONTRACTS) == {
        "reference_library",
        "script",
        "narration",
        "keyframe",
        "location",
        "video_prompt",
    }


def test_shared_skill_delivers_both_modes_and_scope_boundaries():
    resource = next(
        r
        for r in read_contract("script", include=("consistency-review",))["resources"]
        if r["name"] == "shared/storyrail-consistency-review/SKILL.md"
    )
    text = resource["text"]
    for obligation in (
        "不写入",
        "不能扩大为全项目回改",
        "不授予任何工具权限",
    ):
        assert obligation in text


def test_consistency_skill_covers_many_to_many_shot_segment_relations():
    """Shot 与 Segment 是多对多覆盖：改一侧时检查另一侧的全部覆盖关系。"""
    resource = next(
        r
        for r in read_contract("script", include=("consistency-review",))["resources"]
        if r["name"] == "shared/storyrail-consistency-review/SKILL.md"
    )
    text = " ".join(resource["text"].split())
    for required in (
        "Shot 与 Segment 是多对多覆盖关系",
        "一个 Shot 可被多个相邻 Segment 覆盖",
        "一个 Segment 可覆盖 多个相邻 Shot",
        "覆盖该 Shot 的全部 Segment",
        "覆盖的全部 Shot",
        "共享边界 Shot 的两段是延续 同一镜头",
    ):
        assert required in text, required


def test_agent_entries_view_images_natively_without_cli_tools():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "integrations/agent_launcher/PROMPT.md").read_text()
    server = create_server(None)
    for text in (launcher, server.instructions):
        assert "read_media_input" in text
        assert "原生" in text and "多模态视觉能力" in text
        assert "不要调用 ffmpeg、ImageMagick、Python/PIL" in text
        assert "如实报告" in text
        assert "没有多模态视觉能力" in text
        assert "请用户提供各图的内容" in text
        assert "暂停相关提示词编写与生成" in text
        assert "直接拒绝需要看图的任务" not in text
