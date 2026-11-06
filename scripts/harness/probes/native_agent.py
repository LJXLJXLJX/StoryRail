"""真实 Pi 原生工具验收，本地确定性假模型，不访问任何模型厂商。"""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

calls = []


class Model(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = payload["model"]
        calls.append(model)
        used_tool = any(m.get("role") == "tool" for m in payload["messages"])
        if used_tool:
            delta, finish = {"content": "合成原生工具验收已执行。"}, "stop"
        else:
            command = (
                "python /app/scripts/harness/probes/agent_probe.py"
                if model == "parent"
                else 'python -c "from pathlib import Path; '
                "assert not Path('/state/core_canary').exists(); "
                "Path('/workspace/child-ok').write_text('ok')\""
            )
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_native_probe",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps({"command": command, "timeout": 90}),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for content, reason in [(delta, None), ({}, finish)]:
            chunk = {
                "id": "local-canary",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": model,
                "choices": [{"index": 0, "delta": content, "finish_reason": reason}],
            }
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *_args):
        pass


def main():
    config = Path("/workspace/pi-agent")
    config.mkdir(exist_ok=True)
    (config / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "canary": {
                        "baseUrl": "http://127.0.0.1:19000/v1",
                        "api": "openai-completions",
                        "apiKey": "synthetic",
                        "models": [
                            {"id": "parent", "reasoning": False},
                            {"id": "child", "reasoning": False},
                        ],
                    }
                }
            }
        )
    )
    server = ThreadingHTTPServer(("127.0.0.1", 19000), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                "pi",
                "--print",
                "--no-session",
                "--provider",
                "canary",
                "--model",
                "parent",
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "probe",
            ],
            env={**os.environ, "PI_CODING_AGENT_DIR": str(config)},
            capture_output=True,
            text=True,
            timeout=180,
        )
        Path("/workspace/pi-output.txt").write_text(result.stdout + result.stderr)
        summary = {
            "pi_exit_code": result.returncode,
            "parent_model_calls": calls.count("parent"),
            "child_model_calls": calls.count("child"),
            "real_model_calls": 0,
            "pi_version": subprocess.check_output(["pi", "--version"], text=True).strip(),
        }
        Path("/workspace/native-agent.json").write_text(json.dumps(summary))
        print(json.dumps(summary))
        if result.returncode != 0 or not Path("/workspace/probe.json").exists():
            raise RuntimeError("Pi 原生工具验收未完成，检查隔离输出。")
        if not all(json.loads(Path("/workspace/probe.json").read_text()).values()):
            raise RuntimeError("隔离检查存在失败项。")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
