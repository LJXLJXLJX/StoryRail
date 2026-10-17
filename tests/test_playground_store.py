"""PG1-T3：playground.json 编解码与原子持久化 Store。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.model_providers.minimax_h3.manifest import MANIFEST as H3_MANIFEST
from core.playground.codec import parse_document, serialize_document
from core.playground.models import (
    PLAYGROUND_SCHEMA_VERSION,
    AssetOrigin,
    PlaygroundAsset,
    PlaygroundDocument,
    PlaygroundRequestRecord,
    PlaygroundRun,
    RunPhase,
    canonical_json,
)
from core.playground.store import PlaygroundStore
from core.structured_director.models import NarrationLanguage
from tests.playground_fixtures import real_mp4_bytes
from tests.playground_recipes import PlaygroundCapability

TS = "2026-09-28T03:12:45.123456+00:00"
SHA256 = "9f2c0c3b6a1e4d7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f"
RUN_ID = "5c9e1a2b3c4d5e6f708192a3b4c5d6e7"
OTHER_RUN_ID = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"


def make_asset(**overrides) -> PlaygroundAsset:
    values: dict[str, object] = {
        "id": SHA256[:32],
        "media_type": "image/png",
        "byte_count": 1024,
        "sha256": SHA256,
        "relative_path": "assets/images/imported/雨夜街道-9f2c0c3b6a.png",
        "duration_seconds": None,
        "origin": AssetOrigin("imported"),
        "created_at": TS,
    }
    values.update(overrides)
    return PlaygroundAsset(**values)  # type: ignore[arg-type]


def make_run(**overrides) -> PlaygroundRun:
    values: dict[str, object] = {
        "id": RUN_ID,
        "recipe": H3_MANIFEST.recipe("minimax_h3.fl2va"),
        "capability": PlaygroundCapability.VIDEO_FL2VA,
        "phase": RunPhase.QUEUED,
        "progress": 0.0,
        "message": "首尾帧视频任务已提交。",
        "parameters_json": canonical_json(
            {
                "prompt": "雨夜街道",
                "aspect_ratio": "16:9",
                "duration_seconds": 6.0,
                "seed": 1234,
                "first_frame_asset_id": SHA256[:32],
                "last_frame_asset_id": None,
            }
        ),
        "input_asset_ids": (SHA256[:32],),
        "seed": 1234,
        "plugin_id": "fake_fl2va",
        "plugin_version": 1,
        "external_id": "external-1",
        "output_asset_id": None,
        "result_json": None,
        "error_code": None,
        "cancellation_requested": False,
        "retry_of": None,
        "note": "cfg 默认",
        "dismissed": False,
        "created_at": TS,
        "updated_at": TS,
    }
    values.update(overrides)
    return PlaygroundRun(**values)  # type: ignore[arg-type]


def make_record() -> PlaygroundRequestRecord:
    return PlaygroundRequestRecord(
        request_id="a" * 64,
        caller_id="agent-3b1c",
        idempotency_key="fl2va-seed-1234",
        request_digest="b" * 64,
        operation="playground.submit_run",
        receipt_json='{"receipt":{"status":"succeeded"},"data":{}}',
        created_at=TS,
    )


@pytest.fixture
def store(stories_root: Path) -> PlaygroundStore:
    return PlaygroundStore(stories_root / ".playground")


def test_ensure_created_is_idempotent(store: PlaygroundStore) -> None:
    first = store.ensure_created()
    second = store.ensure_created()
    assert first.revision == 1
    assert second.revision == 1
    assert store.read() == first
    assert store.path.is_file()


def test_roundtrip_preserves_document(store: PlaygroundStore) -> None:
    store.ensure_created()
    second_asset = make_asset(
        id=OTHER_RUN_ID,
        media_type="video/mp4",
        byte_count=8812345,
        sha256="0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9",
        relative_path="assets/videos/runs/FL2VA-5c9e1a2b-0a1b2c3d4e.mp4",
        duration_seconds=6.0,
        origin=AssetOrigin("run_output", run_id=RUN_ID),
    )
    document = replace(
        store.read(),
        revision=2,
        assets=(make_asset(), second_asset),
        runs=(make_run(id=RUN_ID, output_asset_id=None), make_run(id=OTHER_RUN_ID)),
        application_requests=(make_record(),),
    )
    stored = store.commit(lambda _previous: document)
    assert stored.revision == 2
    assert store.read() == document

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert isinstance(raw["runs"][0]["parameters"], dict)
    assert list(raw) == ["schema_version", "revision", "assets", "runs", "application_requests"]


def test_parse_rejects_unknown_and_missing_fields() -> None:
    document = PlaygroundDocument(schema_version=PLAYGROUND_SCHEMA_VERSION, revision=1)
    root = serialize_document(document)

    with pytest.raises(ValueError, match="缺失或未声明"):
        parse_document({**root, "extra": 1})
    with pytest.raises(ValueError, match="缺失或未声明"):
        parse_document({key: value for key, value in root.items() if key != "runs"})

    asset_document = serialize_document(replace(document, assets=(make_asset(),)))
    stored_asset = asset_document["assets"][0]
    with pytest.raises(ValueError, match="缺失或未声明"):
        parse_document({**root, "assets": [{**stored_asset, "x": 1}]})
    with pytest.raises(ValueError, match="缺失或未声明"):
        parse_document(
            {
                **root,
                "assets": [{key: value for key, value in stored_asset.items() if key != "sha256"}],
            }
        )

    run_document = serialize_document(replace(document, runs=(make_run(),)))
    with pytest.raises(ValueError, match="缺失或未声明"):
        parse_document({**root, "runs": [{**run_document["runs"][0], "unexpected": None}]})
    with pytest.raises(ValueError, match="缺失或未声明"):
        parse_document(
            {
                **root,
                "runs": [
                    {key: value for key, value in run_document["runs"][0].items() if key != "phase"}
                ],
            }
        )


def test_parse_rejects_other_schema_version() -> None:
    with pytest.raises(ValueError, match="schema 版本不受支持"):
        parse_document(
            {
                "schema_version": PLAYGROUND_SCHEMA_VERSION - 1,
                "revision": 1,
                "assets": [],
                "runs": [],
                "application_requests": [],
            }
        )


def test_codec_rejects_run_with_invalid_parameters(store: PlaygroundStore) -> None:
    document = store.ensure_created()
    stored = replace(
        document,
        revision=2,
        runs=(make_run(),),
    )
    store.commit(lambda _previous: stored)
    import json

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["runs"][0]["parameters"].pop("duration_seconds")
    with pytest.raises(ValueError, match="参数键不匹配"):
        parse_document(raw)

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["runs"][0]["seed"] = 7
    with pytest.raises(ValueError, match="run.seed 与参数不一致"):
        parse_document(raw)

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["runs"][0]["input_asset_ids"] = []
    with pytest.raises(ValueError, match="run.input_asset_ids 与参数不一致"):
        parse_document(raw)


def test_commit_requires_revision_increment(store: PlaygroundStore) -> None:

    store.ensure_created()
    with pytest.raises(RuntimeError, match="revision 提交不一致"):
        store.commit(lambda previous: replace(previous, revision=previous.revision + 2))
    with pytest.raises(RuntimeError, match="revision 提交不一致"):
        store.commit(lambda previous: replace(previous, revision=previous.revision))
    current = store.read()
    assert store.commit(lambda previous: previous) == current
    assert store.read().revision == 1


def test_ingest_asset_dedupes_by_sha(store: PlaygroundStore, png_bytes: bytes) -> None:
    document = store.ensure_created()
    updated, asset = store.ingest_asset(
        document,
        media_type="image/png",
        content=png_bytes,
        origin_dir="imported",
        label="雨夜街道",
        origin=AssetOrigin("imported"),
        created_at=TS,
    )
    again, same = store.ingest_asset(
        replace(updated, revision=updated.revision + 1),
        media_type="image/png",
        content=png_bytes,
        origin_dir="runs",
        label="另一个名字",
        origin=AssetOrigin("run_output", run_id=RUN_ID),
        created_at=TS,
    )
    assert same == asset
    assert len(again.assets) == 1
    assert asset.relative_path.startswith("assets/images/imported/雨夜街道-")
    assert (store.root_directory / asset.relative_path).is_file()


def test_ingest_asset_rejects_bad_signature(store: PlaygroundStore, wav_bytes: bytes) -> None:
    document = store.ensure_created()
    with pytest.raises(ValueError, match="不一致"):
        store.ingest_asset(
            document,
            media_type="image/png",
            content=wav_bytes,
            origin_dir="imported",
            label="参考",
            origin=AssetOrigin("imported"),
            created_at=TS,
        )


def test_ingest_asset_reads_mp4_duration_from_bytes(store: PlaygroundStore) -> None:
    document = store.ensure_created()
    updated, asset = store.ingest_asset(
        document,
        media_type="video/mp4",
        content=real_mp4_bytes(24, 2.0),
        origin_dir="imported",
        label="运镜参考",
        origin=AssetOrigin("imported"),
        created_at=TS,
    )
    assert updated.assets == (asset,)
    assert asset.duration_seconds == pytest.approx(2.0)


def test_read_asset_verifies_hash(store: PlaygroundStore, png_bytes: bytes) -> None:
    document = store.ensure_created()
    updated, asset = store.ingest_asset(
        document,
        media_type="image/png",
        content=png_bytes,
        origin_dir="imported",
        label="雨夜街道",
        origin=AssetOrigin("imported"),
        created_at=TS,
    )
    store.commit(lambda _previous: replace(updated, revision=updated.revision + 1))
    assert store.read_asset(asset.id)[1] == png_bytes

    path = store.root_directory / asset.relative_path
    path.write_bytes(png_bytes + b"tampered")
    with pytest.raises(ValueError, match="内容校验失败"):
        store.read_asset(asset.id)

    with pytest.raises(FileNotFoundError):
        store.read_asset("f" * 32)


def test_symlinked_root_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / ".playground-real"
    real.mkdir()
    link = tmp_path / ".playground"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="不能是符号链接"):
        PlaygroundStore(link)


def test_project_workspace_list_ignores_playground_directory(stories_root: Path) -> None:
    from core.project_settings import ProjectAspectRatio
    from core.project_workspaces import ProjectWorkspaceStore

    PlaygroundStore(stories_root / ".playground").ensure_created()
    workspaces = ProjectWorkspaceStore(stories_root)
    created = workspaces.create(
        "雨夜",
        "# 完整导演方案\n\n小满带着红色行李箱等候末班车。",
        aspect_ratio=ProjectAspectRatio.LANDSCAPE,
        narration_languages=tuple(NarrationLanguage),
    )
    listed = workspaces.list()
    assert [item.id for item in listed] == [created.id]
