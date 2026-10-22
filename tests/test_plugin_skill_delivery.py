"""插件提示词 Skill 全文只经专业契约交付；工作集只给目录，避免逐 Segment 重复传输。"""

import asyncio
import hashlib

from test_prompt_worksets import fixture

from core.structured_director.prompt_worksets import video_prompt_workset
from core.structured_director.reads.professional_worksets import contract_read


def test_video_workset_lists_plugin_skills_and_contract_carries_text(tmp_path):
    _store, service, document, _ = asyncio.run(fixture(tmp_path))
    registry = service._registry
    segment_id = document.video_plan.segments[0].segment_id

    workset = video_prompt_workset(
        document,
        segment_id,
        provider_recipes=service.provider_recipe_views(),
        provider_catalog=registry,
    )
    [index] = workset["plugin_skills"]
    assert index["name"] == "h3-prompt-writing"
    assert index["resources"]
    assert all(set(item) == {"name", "sha256", "bytes"} for item in index["resources"])

    contract = contract_read(document, {"capability": "video_prompt"}, provider_catalog=registry)
    plugin = {
        item["name"]: item
        for item in contract["resources"]
        if item["name"].startswith("plugin/h3-prompt-writing/")
    }
    assert set(plugin) == {
        f"plugin/h3-prompt-writing/{item['name']}" for item in index["resources"]
    }
    for item in index["resources"]:
        resource = plugin[f"plugin/h3-prompt-writing/{item['name']}"]
        assert hashlib.sha256(resource["text"].encode()).hexdigest() == item["sha256"]

    # 契约内容未变化时 if_hash 只回 unchanged，Skill 正文不再重复传输。
    unchanged = contract_read(
        document,
        {"capability": "video_prompt", "if_hash": contract["hash"]},
        provider_catalog=registry,
    )
    assert unchanged == {"unchanged": True, "hash": contract["hash"]}


def test_contract_without_provider_catalog_has_no_plugin_resources(tmp_path):
    _store, _service, document, _ = asyncio.run(fixture(tmp_path))
    contract = contract_read(document, {"capability": "video_prompt"})
    assert not any(item["name"].startswith("plugin/") for item in contract["resources"])
