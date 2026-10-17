"""Kimi真实网关协议回归：只替换宿主认证及fetch，不访问模型。"""

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def write_fake_modules(tmp_path):
    """写出宿主认证/刷新与 fetch 替身；不访问真实模型。"""
    auth = tmp_path / "auth.mjs"
    oauth = tmp_path / "oauth.mjs"
    preload = tmp_path / "fetch.mjs"
    auth.write_text(
        "export const AuthStorage={create:()=>({"
        "modify:async(_,fn)=>await fn({access:'fake',expires:0})})};"
    )
    oauth.write_text(
        "export const kimiCodingOAuth={refresh:async(c,signal)=>{"
        "if(!signal)throw Error();return c;}};"
    )
    preload.write_text(
        "globalThis.fetch=async(url,options)=>{"
        "if(url!=='https://api.kimi.com/coding/v1/messages')throw Error('wrong origin');"
        "const s='data:'+JSON.stringify({type:'message_start',message:{usage:"
        "{input_tokens:11,cache_read_input_tokens:7}}})+'\\n\\n'+"
        "'data: '+JSON.stringify({type:'message_delta',usage:{output_tokens:5}})+'\\n\\n'+"
        "'data:'+JSON.stringify({type:'message_stop'})+'\\n\\n';"
        "return new Response(new ReadableStream({start(c){"
        "const bytes=new TextEncoder().encode(s);"
        "for(let i=0;i<bytes.length;i+=3)c.enqueue(bytes.slice(i,i+3));c.close();}}));};"
    )
    return auth, oauth, preload


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def send_message(port, trial="fixture"):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/trial/{trial}/v1/messages",
        data=json.dumps({"model": "kimi-for-coding", "stream": True}).encode(),
        headers={"x-api-key": "fake"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_for_outcomes(ledger):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        records = json.loads(ledger.read_text()) if ledger.exists() else []
        if records and all(r["outcome"] != "pending" for r in records):
            return records
        time.sleep(0.01)
    raise AssertionError("gateway did not persist trial outcomes in time")


def test_kimi_stream_usage_without_space_and_unlimited_restart(tmp_path):
    auth, oauth, preload = write_fake_modules(tmp_path)
    port = free_port()
    ledger = tmp_path / "ledger.json"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "authorized": True,
                "limit": None,
                "mode": "kimi_messages",
                "port": port,
                "authModule": str(auth),
                "oauthModule": str(oauth),
                "ledger": str(ledger),
                "trials": {"fixture": {"token": "fake"}},
            }
        )
    )
    gateway = Path(__file__).resolve().parents[1] / "scripts/harness/real_agent/meter_gateway.mjs"

    for count in [13, 1]:
        process = subprocess.Popen(
            ["node", "--import", str(preload), str(gateway), str(config)],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert process.stdout.readline().strip() == "KIMI_GATEWAY_READY"
            for _ in range(count):
                status, body = send_message(port)
                assert status == 200
                assert b"message_stop" in body
            wait_for_outcomes(ledger)
        finally:
            process.terminate()
            process.wait(timeout=5)
    records = json.loads(ledger.read_text())
    assert len(records) == 14
    assert all(r["outcome"] == "completed" for r in records)
    assert all(
        r["usage"]
        == {
            "input_tokens": 11,
            "cache_read_input_tokens": 7,
            "output_tokens": 5,
        }
        for r in records
    )


def test_kimi_gateway_enforces_optional_request_limit(tmp_path):
    """显式 maxRequests 时超限按 402 拒绝；缺省仍保持不限次语义（上一个用例锁定）。"""

    auth, oauth, preload = write_fake_modules(tmp_path)
    port = free_port()
    ledger = tmp_path / "ledger.json"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "authorized": True,
                "limit": None,
                "mode": "kimi_messages",
                "maxRequests": 1,
                "port": port,
                "authModule": str(auth),
                "oauthModule": str(oauth),
                "ledger": str(ledger),
                "trials": {"fixture": {"token": "fake"}},
            }
        )
    )
    gateway = Path(__file__).resolve().parents[1] / "scripts/harness/real_agent/meter_gateway.mjs"
    process = subprocess.Popen(
        ["node", "--import", str(preload), str(gateway), str(config)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "KIMI_GATEWAY_READY"
        status, _ = send_message(port)
        assert status == 200
        status, body = send_message(port)
        assert status == 402
        assert b"evaluation_budget_exhausted" in body
        records = wait_for_outcomes(ledger)
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert len(records) == 1
    assert records[0]["outcome"] == "completed"


def test_kimi_gateway_enforces_per_trial_request_limit(tmp_path):
    auth, oauth, preload = write_fake_modules(tmp_path)
    port = free_port()
    ledger = tmp_path / "ledger.json"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "authorized": True,
                "limit": None,
                "mode": "kimi_messages",
                "port": port,
                "authModule": str(auth),
                "oauthModule": str(oauth),
                "ledger": str(ledger),
                "trials": {"fixture": {"token": "fake", "maxRequests": 1}},
            }
        )
    )
    gateway = Path(__file__).resolve().parents[1] / "scripts/harness/real_agent/meter_gateway.mjs"
    process = subprocess.Popen(
        ["node", "--import", str(preload), str(gateway), str(config)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "KIMI_GATEWAY_READY"
        assert send_message(port)[0] == 200
        assert send_message(port)[0] == 402
        records = wait_for_outcomes(ledger)
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert len(records) == 1
