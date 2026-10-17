"""R08 原生 Pi 启动器；只配置本轮合成网关，不装配 StoryRail Agent adapter。"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    config = json.loads(Path("/workspace/config.json").read_text())
    root = Path("/workspace/pi-config")
    root.mkdir(exist_ok=True)
    (root / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "evaluation": {
                        "api": "anthropic-messages",
                        "baseUrl": config["gateway_url"],
                        "apiKey": config["model_token"],
                        "models": [
                            {
                                "id": "kimi-for-coding",
                                "name": "Kimi K2.8 Preview",
                                "reasoning": True,
                                "input": ["text", "image"],
                                "contextWindow": 262144,
                                "maxTokens": 32768,
                                "cost": {
                                    "input": 0.95,
                                    "output": 4,
                                    "cacheRead": 0.19,
                                    "cacheWrite": 0,
                                },
                                "compat": {
                                    "allowEmptySignature": True,
                                    "forceAdaptiveThinking": True,
                                },
                                "headers": {"User-Agent": "pi (linux; arm64)"},
                            }
                        ],
                    }
                }
            }
        )
    )
    (root / "settings.json").write_text(
        json.dumps(
            {
                "retry": {"enabled": False, "provider": {"maxRetries": 0}},
                "compaction": {"enabled": False},
            }
        )
    )
    os.environ["PI_CODING_AGENT_DIR"] = str(root)
    phase = sys.argv[1]
    prompt = Path("/workspace/" + phase + ".md").read_text()
    with Path("/workspace/" + phase + "-pi.jsonl").open("w") as output:
        result = subprocess.run(
            [
                "pi",
                "--print",
                "--mode",
                "json",
                "--no-session",
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-context-files",
                "--no-approve",
                "--provider",
                "evaluation",
                "--model",
                "kimi-for-coding",
                "--thinking",
                "high",
                prompt,
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=900,
        )
    print(json.dumps({"phase": phase, "exit_code": result.returncode}), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
