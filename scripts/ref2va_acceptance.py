from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from core.http_transport import UrllibTransport
from core.model_provider import GenerationPhase

from core.model_providers.minimax_h3.ref2va import (
    H3ReferenceFrame,
    MiniMaxH3Ref2VAProvider,
    MiniMaxH3Ref2VARequest,
)

PROMPT = (
    "A red wind-up toy car drives smoothly from the left toward the yellow flag on a clean white "
    "tabletop. Static camera, consistent lighting, realistic toy motion."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="MiniMax H3 Ref2VA 三轮真实验收")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8787")
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--last", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=448)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--steps", type=int, choices=(20, 8), default=8)
    parser.add_argument("--sage-attention", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--selflift", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    first = H3ReferenceFrame("image/png", args.first.read_bytes())
    last = H3ReferenceFrame("image/png", args.last.read_bytes())
    headers = None
    if args.token_file:
        headers = {"Authorization": "Bearer " + args.token_file.read_text().strip()}
    provider = MiniMaxH3Ref2VAProvider(args.endpoint, UrllibTransport(headers))
    cases = {
        "first-only": (first, None),
        "last-only": (None, last),
        "first-and-last": (first, last),
    }
    report = []
    for index, (name, (opening, closing)) in enumerate(cases.items(), start=1):
        print(f"[{index}/3] submit {name}", flush=True)
        handle = provider.submit(
            MiniMaxH3Ref2VARequest(
                prompt=PROMPT,
                reference_audios=(),
                first_frame=opening,
                last_frame=closing,
                width=args.width,
                height=args.height,
                duration_seconds=args.duration,
                seed=314159 + index,
                steps=args.steps,
                cfg=1.0,
                save_audio=False,
                sage_attention=args.sage_attention,
                selflift=args.selflift,
            )
        )
        while True:
            observation = provider.observe(handle)
            print(
                json.dumps(
                    {
                        "case": name,
                        "phase": observation.phase,
                        "progress": observation.progress,
                        "message": observation.message,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if observation.phase in {
                GenerationPhase.SUCCEEDED,
                GenerationPhase.FAILED,
                GenerationPhase.CANCELLED,
            }:
                break
            time.sleep(5)
        if observation.phase is not GenerationPhase.SUCCEEDED:
            raise RuntimeError(f"{name} 失败：{observation.message}")
        video_path = args.output_dir / f"{name}.mp4"
        video_path.write_bytes(provider.read_artifact(handle, observation.artifact.artifact_id))
        case_report = extract_and_compare(
            video_path,
            first_source=args.first if opening else None,
            last_source=args.last if closing else None,
        )
        report.append({"case": name, "video": video_path.name, **case_report})
        (args.output_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


def extract_and_compare(
    video_path: Path, *, first_source: Path | None, last_source: Path | None
) -> dict[str, object]:
    import av

    frames = []
    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        for frame in container.decode(stream):
            frames.append(frame.to_image().convert("RGB"))
    if not frames:
        raise RuntimeError(f"{video_path.name} 没有可解码视频帧。")
    first_actual, last_actual = frames[0], frames[-1]
    first_path = video_path.with_name(video_path.stem + "-actual-first.png")
    last_path = video_path.with_name(video_path.stem + "-actual-last.png")
    first_actual.save(first_path)
    last_actual.save(last_path)
    comparisons = {}
    if first_source:
        comparisons["first"] = _comparison(
            first_source, first_actual, video_path.with_name(video_path.stem + "-compare-first.png")
        )
    if last_source:
        comparisons["last"] = _comparison(
            last_source, last_actual, video_path.with_name(video_path.stem + "-compare-last.png")
        )
    return {"decoded_frame_count": len(frames), "comparisons": comparisons}


def _comparison(source_path: Path, actual, output_path: Path) -> dict[str, object]:
    from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat

    with Image.open(source_path) as source:
        expected = ImageOps.fit(source.convert("RGB"), actual.size, method=Image.Resampling.LANCZOS)
    difference = ImageChops.difference(expected, actual)
    mean = ImageStat.Stat(difference).mean
    normalized_mae = sum(mean) / (3 * 255)
    sheet = Image.new("RGB", (actual.width, actual.height * 2 + 32), "white")
    sheet.paste(expected, (0, 16))
    sheet.paste(actual, (0, actual.height + 32))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 2), "EXPECTED (cover fitted)", fill="black")
    draw.text((8, actual.height + 18), "ACTUAL DECODED FRAME", fill="black")
    sheet.save(output_path)
    return {
        "comparison_image": output_path.name,
        "normalized_mean_absolute_error": round(normalized_mae, 6),
        "expected_size": list(expected.size),
        "actual_size": list(actual.size),
    }


if __name__ == "__main__":
    raise SystemExit(main())
