"""真实模型网关预算在转发前落盘，进程重启不能重置。"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def test_gateway_budget_survives_restart(tmp_path):
    config = tmp_path / "gateway.json"
    ledger = tmp_path / "requests.json"
    config.write_text(
        json.dumps(
            {
                "authorized": True,
                "real": False,
                "mode": "openai_responses",
                "maxRequests": 12,
                "port": 0,
                "ledger": str(ledger),
                "trials": {
                    "fixture": {"token": "synthetic", "maxRequests": 12},
                    "small": {"token": "synthetic", "maxRequests": 1},
                },
            }
        )
    )
    script = Path(__file__).resolve().parents[1] / "scripts/harness/real_agent/meter_gateway.mjs"

    def start():
        process = subprocess.Popen(
            ["node", str(script), str(config)],
            stdout=subprocess.PIPE,
            text=True,
        )
        port = json.loads(process.stdout.readline())["gateway_port"]
        return process, f"http://127.0.0.1:{port}/trial/fixture/codex/responses"

    def send(url, model="gpt-5.6-sol", compressed=False, token="synthetic"):
        data = json.dumps(
            {"model": model, "reasoning": {"effort": "medium"}, "stream": True}
        ).encode()
        headers = {"Authorization": "Bearer " + token}
        if compressed:
            data = subprocess.check_output(
                [
                    "node",
                    "-e",
                    "process.stdout.write(require('node:zlib').zstdCompressSync("
                    "require('node:fs').readFileSync(0)))",
                ],
                input=data,
            )
            headers["Content-Encoding"] = "zstd"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    process, url = start()
    try:
        assert send(url, "different-model") == 400
        assert send(url, token="wrong") == 403
        assert not ledger.exists()
        small = url.replace("/fixture/", "/small/")
        assert send(small, compressed=True) == 200
        assert send(small) == 402
        assert [send(url) for _ in range(11)] == [200] * 11
        assert send(url) == 402
    finally:
        process.terminate()
        process.wait(timeout=5)
    process, url = start()
    try:
        assert send(url) == 402
        records = json.loads(ledger.read_text())
        assert len(records) == 12
        assert all(record["outcome"] == "dry_run" for record in records)
    finally:
        process.terminate()
        process.wait(timeout=5)
