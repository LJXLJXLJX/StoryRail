"""调试模式：MCP instructions 最前面注入同一份调试提示词，非调试连接不受影响。"""

from integrations.storyrail_mcp.app import create_playground_server, create_server, debug_prompt


def test_debug_prompt_leads_instructions_only_in_debug_mode():
    prompt = debug_prompt()
    assert prompt.startswith("# 调试模式（第一优先级）")
    for factory in (create_server, create_playground_server):
        normal = factory(None).instructions
        debug = factory(None, debug=True).instructions
        assert prompt not in normal
        assert debug == prompt + "\n\n" + normal
