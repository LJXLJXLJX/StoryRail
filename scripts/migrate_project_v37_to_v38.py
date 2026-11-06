"""一次性把本机 v37 project.json 升到 v38：每个 Keyframe 补 reuse_keyframe_id=null。

Core 不读取旧 schema；本脚本只供作者在本机显式运行，迁移前备份原文件，
迁移后用 Core 当前 codec 完整解析校验，失败则不写入。

用法：.venv/bin/python scripts/migrate_project_v37_to_v38.py <project 目录> [...]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.structured_director.codec.document import _parse_document  # noqa: E402


def migrate(project_directory: Path) -> str:
    path = project_directory / "project.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path} 不是普通文件。")
    document = json.loads(path.read_text(encoding="utf-8"))
    version = document.get("schema_version")
    if version == 38:
        return f"{path}: 已是 v38，跳过"
    if version != 37:
        raise ValueError(f"{path}: schema_version={version}，只迁移 v37。")
    plan = document["structured_director"].get("keyframe_plan")
    for keyframe in [] if plan is None else plan["keyframes"]:
        if "reuse_keyframe_id" in keyframe:
            raise ValueError(f"{path}: Keyframe 已含 v38 字段，不是干净的 v37。")
        keyframe["reuse_keyframe_id"] = None
    document["schema_version"] = 38
    _parse_document(document)

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup = (
        project_directory.parent
        / ".migration-backups"
        / f"schema37-{stamp}-{document['project_id']}"
        / "project.json"
    )
    backup.parent.mkdir(parents=True, exist_ok=False)
    shutil.copy2(path, backup)
    temporary = path.with_name(f".project.json.migrate-{stamp}.tmp")
    with temporary.open("x", encoding="utf-8") as target:
        target.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)
    return f"{path}: v37 → v38（备份 {backup}）"


def main(arguments: list[str]) -> int:
    if not arguments:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    for argument in arguments:
        print(migrate(Path(argument).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
