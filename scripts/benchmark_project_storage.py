"""T13：仅在TemporaryDirectory内测量当前schema，不读真实作品或调用Provider。"""

from __future__ import annotations

import argparse
import base64
import json
import math
import platform
import statistics
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from core.director_proposals import (
    CharacterCardProposal,
    NarrationCueProposal,
    NarrationTrackProposal,
    NarratorProfileProposal,
    ReferenceLibraryProposal,
    SceneProposal,
    SegmentBoundaryProposal,
    ShotProposal,
    ShotSegmentProposal,
    StructuredDirectorScriptProposal,
)
from core.project_settings import ProjectAspectRatio
from core.structured_director import StructuredDirectorService, StructuredDirectorStore
from core.structured_director.codec import _parse_document, serialize_document
from core.structured_director.models import (
    GenerationOperation,
    ImageAssetCategory,
    NarrationLanguage,
    ReferenceGeneration,
    ReferenceGenerationKind,
    ReferenceGenerationPhase,
)
from core.structured_director.reads.semantic_projection import (
    build_semantic_projection,
    build_semantic_tree,
)
from core.structured_director.reads.snapshot_view import serialize_snapshot

TEXT = "甲将白色杯子递给乙，乙在木桌右侧接稳，右侧窗光保持一致。" * 20
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


def create_sample(root: Path, kind: str, count: int):
    pid = uuid4().hex
    directory = root / pid
    directory.mkdir()
    store = StructuredDirectorStore(directory, pid)
    store.create_project(
        title="合成存储基准",
        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
        director_plan_markdown="# 导演方案\n" + TEXT[:300] * count,
        narration_languages=tuple(NarrationLanguage),
    )
    store.begin_reference_proposal()
    document = store.apply_reference_proposal(
        ReferenceLibraryProposal(
            (CharacterCardProposal("甲", "蓝衣", "平静"),),
            NarratorProfileProposal("旁白", "清晰", "Clear"),
        )
    )
    character = document.reference_library.characters[0].id
    scenes = []
    for index in range(count):
        narration = kind == "narration" or (kind == "mixed" and index % 2 == 0)
        shots = (
            ()
            if narration
            else tuple(
                ShotProposal(
                    (character,),
                    "固定中景。",
                    "固定。",
                    TEXT,
                    "安静室内环境声。",
                    None,
                    (
                        ShotSegmentProposal(3, TEXT, (), None),
                        ShotSegmentProposal(
                            3,
                            TEXT,
                            (),
                            SegmentBoundaryProposal("continuity_anchor", "保持杯子交接边界。"),
                        ),
                    ),
                )
                for _ in range(5)
            )
        )
        cues = (
            (
                NarrationCueProposal(
                    None,
                    None,
                    NarrationTrackProposal(TEXT, 42),
                    NarrationTrackProposal("Benchmark narration.", 42),
                ),
            )
            if narration
            else ()
        )
        scenes.append(
            SceneProposal(
                f"Scene {index + 1}",
                TEXT,
                "白墙木桌右窗。",
                shots,
                cues,
                "narration" if narration else "drama",
            )
        )
    document = confirm_fixture_references(store)
    store.begin_script_proposal(expected_revision=document.revision)
    document = store.apply_script_proposal(StructuredDirectorScriptProposal(tuple(scenes)))
    document = store.import_image_asset(
        media_type="image/png",
        content=PNG,
        category=ImageAssetCategory.CHARACTER_REFERENCE,
        expected_revision=document.revision,
    )
    # 合成已终结历史；完整dataclass/Store校验，不提交外部任务。计时不包含fixture装配。
    generations = tuple(
        ReferenceGeneration(
            id=uuid4().hex,
            kind=ReferenceGenerationKind.CHARACTER_LOOK_SHEET,
            operation=GenerationOperation.GENERATE,
            target_id=character,
            phase=ReferenceGenerationPhase.FAILED,
            progress=0,
            message="合成历史",
            prompt_text=TEXT,
            input_asset_ids=(),
            sample_text=None,
            seed=None,
            plugin_id="synthetic",
            plugin_version=1,
            external_id="synthetic-" + uuid4().hex,
            output_asset_id=None,
            error_code="synthetic_failure",
            cancellation_requested=False,
            retry_of=None,
        )
        for _ in range(count * 20)
    )
    store._atomic_write(replace(document, revision=document.revision + 1, generations=generations))
    return store


def measure(operation, iterations):
    operation()  # warmup; filesystem and Python caches are intentionally warm
    timings = []
    value = None
    for _ in range(iterations):
        start = time.perf_counter_ns()
        value = operation()
        timings.append((time.perf_counter_ns() - start) / 1_000_000)
    ordered = sorted(timings)
    return {
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "samples_ms": [round(x, 3) for x in timings],
    }, value


def benchmark(store, iterations):
    document = store.read()
    raw = store.path.read_bytes()
    parsed = json.loads(raw)
    service = StructuredDirectorService(store)
    scenes = document.director_script.scenes
    outline_request = {
        "level": "outline",
        "scope": {"project_id": document.project_id},
        "limit": 50,
    }
    scene_request = {
        "level": "scene",
        "scope": {"scene_ids": [scenes[0].id]},
        "extensions": ["text"],
    }
    rows, values = {}, {}
    operations = {
        "read_bytes": store.path.read_bytes,
        "json_decode": lambda: json.loads(raw),
        "construct_validate": lambda: _parse_document(parsed),
        "graph_validate": lambda: replace(document),
        "store_read": store.read,
        "serialize_model": lambda: serialize_document(document),
        "json_encode": lambda: json.dumps(parsed, ensure_ascii=False, indent=2),
        "legacy_ui_snapshot": lambda: serialize_snapshot(document, service, "/fixture"),
        "ui_outline_page": lambda: build_semantic_projection(document, outline_request),
        "agent_scene_workset": lambda: build_semantic_projection(document, scene_request),
        "agent_full_tree": lambda: build_semantic_tree(document, tuple(s.id for s in scenes)),
    }
    for name, operation in operations.items():
        rows[name], values[name] = measure(operation, iterations)
    current = document

    def commit():
        nonlocal current
        current = replace(current, revision=current.revision + 1)
        store._atomic_write(current)

    rows["atomic_commit"], _ = measure(commit, iterations)
    for name in ["legacy_ui_snapshot", "ui_outline_page", "agent_scene_workset", "agent_full_tree"]:
        rows[name]["json_bytes"] = len(json.dumps(values[name], ensure_ascii=False).encode())
    return {
        "schema_version": document.schema_version,
        "json_bytes": len(raw),
        "counts": {
            "scenes": len(scenes),
            "shots": sum(len(s.shots) for s in scenes),
            "segments": sum(len(h.segments) for s in scenes for h in s.shots),
            "assets": len(document.assets),
            "generations": len(document.generations),
            "runs": len(document.director_runs),
        },
        "measurements": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--scales", type=int, nargs="+", default=[10, 50, 100])
    args = parser.parse_args()
    if args.iterations < 3 or any(n < 1 or n > 100 for n in args.scales):
        parser.error("iterations至少3；Scene规模须为1至100。")
    report = {
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "iterations": args.iterations,
            "warmup": 1,
            "cache": "OS/Python warm, no cache eviction, sequential, GC default",
        },
        "budget_ms": {
            "store_read_p95": 250,
            "atomic_commit_p95": 500,
            "ui_outline_page_p95": 100,
            "agent_scene_workset_p95": 100,
        },
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="storyrail-storage-benchmark-") as directory:
        for kind in ["narration", "drama", "mixed"]:
            for count in args.scales:
                store = create_sample(Path(directory), kind, count)
                result = {"kind": kind, **benchmark(store, args.iterations)}
                report["cases"].append(result)
                print(
                    json.dumps(
                        {
                            "kind": kind,
                            "counts": result["counts"],
                            "json_bytes": result["json_bytes"],
                        }
                    ),
                    flush=True,
                )
    report["temporary_projects_removed"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def confirm_fixture_references(store):
    """隔离合成项目以正式人类命令建立审核前置条件。"""
    from core.application.caller import Caller
    from core.director_commands import DirectorCommand
    from core.structured_director.application_requests import execute_atomic_request

    document = store.read()
    caller = Caller(
        "fixture-human",
        "human",
        frozenset({document.project_id}),
        frozenset({"human.write"}),
        4102444800,
    )
    return execute_atomic_request(
        store,
        DirectorCommand(
            "reference.confirm_review", document.revision, "fixture-reference-review", {}
        ),
        caller,
    ).document


if __name__ == "__main__":
    main()
