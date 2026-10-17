from __future__ import annotations

import argparse
import contextlib
import hashlib
import time
import uuid
from pathlib import Path

from core.model_providers.boundary import GenerationPhase
from core.model_providers.http import UrllibTransport, require_success
from core.model_providers.seedvr2_7b_sharp_fp8 import (
    SeedVR2SevenBSharpFP8Provider,
    SeedVR2UpscaleRequest,
    SeedVR2Video,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="SeedVR2 默认服务真实验收。")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--endpoint", required=True, help="Windows 模型服务地址，例如 http://<windows-lan-ip>:8791"
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path("var/secrets/windows-model-service-token"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=3600)
    parser.add_argument("--repeat", type=int, choices=range(1, 4), default=1)
    args = parser.parse_args()

    token = args.token_file.read_text(encoding="ascii").strip()
    transport = UrllibTransport({"Authorization": "Bearer " + token})
    provider = SeedVR2SevenBSharpFP8Provider(args.endpoint, transport)
    session_id = uuid.uuid4().hex
    lease_endpoint = args.endpoint.rstrip("/") + "/control/controller-lease"
    require_success(
        transport.request(
            "POST", lease_endpoint + "/acquire", json_body={"session_id": session_id}
        ),
        {201},
    )
    active_handle = None
    try:
        content = args.input.read_bytes()
        for attempt in range(1, args.repeat + 1):
            active_handle = provider.submit(
                SeedVR2UpscaleRequest(SeedVR2Video("video/mp4", content))
            )
            deadline = time.monotonic() + args.timeout_seconds
            last_message = None
            while True:
                require_success(
                    transport.request(
                        "POST",
                        lease_endpoint + "/heartbeat",
                        json_body={"session_id": session_id},
                    ),
                    {200},
                )
                observation = provider.observe(active_handle)
                if observation.message != last_message:
                    print(
                        f"第 {attempt} 次：{observation.progress:.0%} {observation.message}",
                        flush=True,
                    )
                    last_message = observation.message
                if observation.phase is GenerationPhase.SUCCEEDED:
                    assert observation.artifact is not None
                    result = provider.read_artifact(active_handle, observation.artifact.artifact_id)
                    output = (
                        args.output
                        if attempt == 1
                        else args.output.with_name(
                            f"{args.output.stem}-{attempt}{args.output.suffix}"
                        )
                    )
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(result)
                    print(
                        f"第 {attempt} 次完成：{len(result)} bytes，"
                        f"sha256={hashlib.sha256(result).hexdigest()}",
                        flush=True,
                    )
                    active_handle = None
                    break
                if observation.phase in {GenerationPhase.FAILED, GenerationPhase.CANCELLED}:
                    raise RuntimeError(
                        f"SeedVR2 任务终止：{observation.error_code or observation.message}"
                    )
                if time.monotonic() >= deadline:
                    raise TimeoutError("SeedVR2 验收超时。")
                time.sleep(2)
        return 0
    except BaseException:
        if active_handle is not None:
            with contextlib.suppress(Exception):
                provider.cancel(active_handle)
        raise
    finally:
        transport.request("DELETE", lease_endpoint + "s/" + session_id)


if __name__ == "__main__":
    raise SystemExit(main())
