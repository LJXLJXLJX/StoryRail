"""R09 的产品安装边界；删除 runtime 不得带走专业资源或媒体适配器。"""

import inspect
from pathlib import Path

import core
import server
from core.director_proposals.professional_contracts import CONTRACTS, read_contract
from core.model_providers.codex_image import CodexImageProvider
from core.structured_director import StructuredDirectorService


def test_product_has_no_vendor_execution_modules_or_injection():
    root = Path(core.__file__).parent
    for name in ("agent_roles", "agent_threads"):
        assert not (root / name).exists()
    assert not (root.parent / "agent_thread_adapters").exists()
    for name in ("agent_runtime.py", "agent_monitor.py"):
        assert not (Path(server.__file__).parent / name).exists()
    params = inspect.signature(StructuredDirectorService).parameters
    assert not any(
        name in params
        for name in (
            "director_router",
            "director_session",
            "script_proposer",
            "keyframe_planner",
            "narration_reviewer",
            "h3_prompt_writer",
        )
    )
    assert not hasattr(StructuredDirectorService, "instruct_director")
    assert not hasattr(StructuredDirectorService, "built_in_assistant_available")
    assert CodexImageProvider.__module__.startswith("core.model_providers.")


def test_all_professional_resources_ship_without_runtime():
    assert set(CONTRACTS) == {
        "reference_library",
        "script",
        "narration",
        "keyframe",
        "location",
        "video_prompt",
    }
    for capability in CONTRACTS:
        contract = read_contract(capability)
        assert contract["resources"][0]["name"] == "SKILL.md"
        assert all(
            item["text"].strip() and len(item["sha256"]) == 64 for item in contract["resources"]
        )
