from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import AudioEffectRequest, apply_audio_effect, preset_names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StoryRail 确定性音频效果试听工具")
    parser.add_argument("input", type=Path, help="输入 PCM WAV")
    parser.add_argument("output", type=Path, help="输出 PCM16 WAV")
    parser.add_argument("--effect", choices=("radio",), default="radio")
    parser.add_argument("--preset", choices=preset_names(), default="weak_signal")
    parser.add_argument("--strength", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--start", type=float, help="可选处理起点（秒，必须与 --end 同时提供）")
    parser.add_argument("--end", type=float, help="可选处理终点（秒，必须与 --start 同时提供）")
    parser.add_argument("--metadata", type=Path, help="可选的事件时间线 JSON 输出")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="覆盖一个 radio 参数；可重复使用",
    )
    arguments = parser.parse_args(argv)
    try:
        request = AudioEffectRequest(
            effect=arguments.effect,
            preset=arguments.preset,
            strength=arguments.strength,
            seed=arguments.seed,
            parameters=_parse_overrides(arguments.overrides),
            start_seconds=arguments.start,
            end_seconds=arguments.end,
        )
        result = apply_audio_effect(arguments.input.read_bytes(), request)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_bytes(result.audio)
        if arguments.metadata:
            arguments.metadata.parent.mkdir(parents=True, exist_ok=True)
            arguments.metadata.write_text(
                json.dumps(result.metadata.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


def _parse_overrides(items: list[str]) -> dict[str, float | int | bool | None]:
    result: dict[str, float | int | bool | None] = {}
    for item in items:
        name, separator, raw = item.partition("=")
        if not separator or not name or name in result:
            raise ValueError(f"--set 必须是唯一的 NAME=VALUE：{item}")
        lowered = raw.lower()
        if lowered == "none":
            value: float | int | bool | None = None
        elif lowered in {"true", "false"}:
            value = lowered == "true"
        else:
            try:
                value = float(raw) if any(mark in raw.lower() for mark in (".", "e")) else int(raw)
            except ValueError as exc:
                raise ValueError(f"--set 值必须是数字、true、false 或 none：{item}") from exc
        result[name] = value
    return result


if __name__ == "__main__":
    raise SystemExit(main())
