#!/usr/bin/env python3
"""生成 web/src/api/types.ts 与 validation.ts，或用 --check 确认没有漂移。

用法（仓库根目录）：
  python scripts/gen_web_contracts.py
  python scripts/gen_web_contracts.py --check
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TYPES_PATH = REPO_ROOT / "web/src/api/types.ts"
VALIDATION_PATH = REPO_ROOT / "web/src/api/validation.ts"
INSTRUCTION_PATH = REPO_ROOT / "web/src/director_workspace/consistency_instruction.ts"
INSTRUCTION_SOURCE = REPO_ROOT / "core/director_proposals/skills/consistency_instruction.md"


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in arguments
    from core.web_contracts.ts_emit import render

    types, validation = render()
    instruction = _instruction_module()
    if check:
        stale = []
        for path, expected in (
            (TYPES_PATH, types),
            (VALIDATION_PATH, validation),
            (INSTRUCTION_PATH, instruction),
        ):
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != expected:
                stale.append(path.relative_to(REPO_ROOT))
        if stale:
            joined = "、".join(str(path) for path in stale)
            print(f"STALE: {joined}（运行 python scripts/gen_web_contracts.py 后提交）")
            return 1
        print("web contracts: fresh")
        return 0
    TYPES_PATH.write_text(types, encoding="utf-8")
    VALIDATION_PATH.write_text(validation, encoding="utf-8")
    INSTRUCTION_PATH.write_text(instruction, encoding="utf-8")
    print(f"wrote {TYPES_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {VALIDATION_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {INSTRUCTION_PATH.relative_to(REPO_ROOT)}")
    return 0


def _instruction_module() -> str:
    text = INSTRUCTION_SOURCE.read_text(encoding="utf-8").strip()
    escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return (
        "// 勿手改，由 scripts/gen_web_contracts.py 生成。\n"
        f"export const CONSISTENCY_INSTRUCTION = `{escaped}`;\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
