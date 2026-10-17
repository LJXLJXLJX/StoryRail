"""Web 契约生成物与 schema 源保持一致。"""

from core.web_contracts.ts_emit import render
from scripts.gen_web_contracts import main


def test_generated_web_contracts_match_schema_source() -> None:
    assert main(["--check"]) == 0


def test_generated_contracts_cover_snapshot_and_proposals() -> None:
    types, validation = render()
    assert types.startswith("// 勿手改，由 scripts/gen_web_contracts.py 生成。")
    assert validation.startswith("// 勿手改，由 scripts/gen_web_contracts.py 生成。")
    assert "export interface StructuredDirectorSnapshot" in types
    assert "export interface ReferenceLibraryProposal" in types
    assert "export interface VideoPromptProposal" in types
    assert 'value === "prepare_references"' not in validation
    assert "refineWorkspaceLayers" in validation
    assert "snapshotConsistencyError" in validation
