"""主机闹钟：单例响铃、参数约束、平台检查，以及项目/Playground 两条 Agent 入口都不触碰业务状态。"""

import asyncio

import pytest
from test_prompt_worksets import fixture
from test_storyrail_mcp import endpoint

from core import host_alarm
from core.application.caller import Caller
from core.host_alarm import ALARM_SECONDS, HostAlarm
from core.playground.commands import execute_command
from core.playground.errors import HostAlarmUnavailableError
from integrations.storyrail_mcp.playground_tools import PLAYGROUND_MODELS, translate_playground


class FakeProcess:
    def __init__(self):
        self.finished = False

    def poll(self):
        return 0 if self.finished else None


class Recorder:
    def __init__(self):
        self.calls = []
        self.processes = []

    def __call__(self, message, seconds):
        self.calls.append((message, seconds))
        self.processes.append(FakeProcess())
        return self.processes[-1]


def test_alarm_rings_once_at_a_time_and_again_after_it_stops():
    spawn = Recorder()
    alarm = HostAlarm(spawn)
    assert alarm.ring("  镜头 3 的\n视频生成完了  ") == {
        "status": "ringing",
        "max_seconds": ALARM_SECONDS,
    }
    assert spawn.calls == [("镜头 3 的 视频生成完了", 120)]
    assert alarm.ring("再叫一次")["status"] == "already_ringing"
    assert len(spawn.calls) == 1
    spawn.processes[-1].finished = True
    assert alarm.ring("第二次任务也结束了")["status"] == "ringing"
    assert len(spawn.calls) == 2


@pytest.mark.parametrize("message", ["", "   ", "字" * 201, None, 3])
def test_alarm_rejects_empty_oversized_or_non_text_message(message):
    spawn = Recorder()
    with pytest.raises(ValueError):
        HostAlarm(spawn).ring(message)
    assert spawn.calls == []


def test_alarm_reports_unsupported_host(monkeypatch):
    monkeypatch.setattr(host_alarm.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="macOS"):
        HostAlarm().ring("完成了")


def test_project_agent_with_read_only_access_rings_without_touching_project(tmp_path, monkeypatch):
    store, service, doc, _ = asyncio.run(fixture(tmp_path))
    spawn = Recorder()
    monkeypatch.setattr(host_alarm.HOST_ALARM, "_spawn", spawn)
    monkeypatch.setattr(host_alarm.HOST_ALARM, "_process", None)
    caller = Caller(
        "alarm-agent",
        "agent",
        frozenset({doc.project_id}),
        frozenset({"project.read"}),
        4102444800,
        (),
        True,
    )

    async def run(server):
        from mcp import Client

        async with Client(server) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert "ring_alarm" in tools
            before = store.path.read_bytes()
            rung = await client.call_tool(
                "ring_alarm", {"project_id": doc.project_id, "message": "全部关键帧已生成"}
            )
            assert not rung.is_error, rung.structured_content
            assert rung.structured_content["data"]["status"] == "ringing"
            again = await client.call_tool(
                "ring_alarm", {"project_id": doc.project_id, "message": "再响一次"}
            )
            assert again.structured_content["data"]["status"] == "already_ringing"
            for invalid in ({"message": ""}, {"message": "x", "extra": 1}):
                rejected = await client.call_tool(
                    "ring_alarm", {"project_id": doc.project_id, **invalid}
                )
                assert rejected.is_error
            assert store.path.read_bytes() == before

    with endpoint(tmp_path, store, service, caller, full_api=True) as (server, _):
        asyncio.run(run(server))
    assert spawn.calls == [("全部关键帧已生成", ALARM_SECONDS)]


def test_playground_ring_alarm_translates_and_reports_unsupported_host(monkeypatch):
    request = PLAYGROUND_MODELS["ring_alarm"].model_validate({"message": "超分跑完了"})
    name, key, arguments = translate_playground("ring_alarm", request)
    assert (name, arguments) == ("playground.ring_alarm", {"message": "超分跑完了"})
    envelope = {"name": name, "idempotency_key": key, "arguments": arguments}

    spawn = Recorder()
    monkeypatch.setattr(host_alarm.HOST_ALARM, "_spawn", spawn)
    monkeypatch.setattr(host_alarm.HOST_ALARM, "_process", None)
    # 闹钟不读 Playground：service 为 None 也能执行。
    result = asyncio.run(execute_command(None, envelope, None))
    assert result == {"data": {"status": "ringing", "max_seconds": ALARM_SECONDS}}

    monkeypatch.setattr(host_alarm.HOST_ALARM, "_process", None)
    monkeypatch.setattr(host_alarm.HOST_ALARM, "_spawn", host_alarm._spawn)
    monkeypatch.setattr(host_alarm.sys, "platform", "linux")
    with pytest.raises(HostAlarmUnavailableError):
        asyncio.run(execute_command(None, envelope, None))
