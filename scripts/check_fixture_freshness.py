"""fixture freshness 门禁：重跑生成器并与提交版本做规范化比较。

生成物含每次运行都不同的随机 ID（uuid4），无法直接 `git diff --exit-code`；
这里把两侧 JSON 中的 32 位十六进制 ID 统一改写为占位符后再比较，结构、字段名、
revision 等任何 schema 漂移仍会暴露。CI 与 scripts/ci_local.sh 调用本脚本。

用法（仓库根目录）：python scripts/check_fixture_freshness.py
退出码：0 新鲜；1 漂移（stdout 输出 unified diff）。
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATORS = (
    ("tests/build_playground_recipe_fixture.py", Path("web/src/test/playground_recipes.json")),
    ("tests/build_video_recipe_fixture.py", Path("web/src/test/video_recipes.json")),
    ("tests/build_story_reader_fixture.py", Path("web/src/test/story_reader_fixture.json")),
    (
        "tests/test_architecture_acceptance.py",
        Path("web/src/test/mixed_approval_fixture.json"),
    ),
)
_HEX32 = re.compile(r"\b[0-9a-f]{32}\b")


def _canonical_key(key: str) -> str:
    return _HEX32.sub("<id>", str(key))


def _canonical(value, key: str | None = None):
    """递归规范化，保持键顺序与重复键（用 pair 列表表示，避免 <id> 键互相覆盖）。

    - 32 位十六进制 ID（uuid4，每次运行随机）→ ``<id>``，键、值、内嵌文本同样处理；
    - ``seed`` 数值 → ``<seed>``（Segment 视频 seed 由随机 Segment ID 派生，同样不稳定）。
    结构、字段名、revision 等 schema 漂移不受影响。
    """
    if isinstance(value, dict):
        return [[_canonical_key(k), _canonical(v, k)] for k, v in value.items()]
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if key == "seed" and (
        isinstance(value, (int, float)) or (isinstance(value, str) and value.isdecimal())
    ):
        return "<seed>"
    if isinstance(value, str):
        return _HEX32.sub("<id>", value)
    return value


def _canonical_text(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return (json.dumps(_canonical(value), ensure_ascii=False, indent=2) + "\n").splitlines()


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="storyrail-freshness-") as directory:
        for generator, committed_relative in GENERATORS:
            regenerated = Path(directory) / committed_relative.name
            subprocess.run(
                [sys.executable, generator, str(regenerated)],
                cwd=REPO_ROOT,
                check=True,
            )
            committed = REPO_ROOT / committed_relative
            before = _canonical_text(committed)
            after = _canonical_text(regenerated)
            if before == after:
                print(f"fresh: {committed_relative}")
                continue
            failures.append(committed_relative)
            print(f"STALE: {committed_relative}（重跑 {generator} 并提交新 fixture）")
            print(
                "\n".join(
                    difflib.unified_diff(
                        before,
                        after,
                        fromfile=f"committed/{committed_relative}",
                        tofile=f"regenerated/{committed_relative.name}",
                        lineterm="",
                    )
                )
            )
    if failures:
        return 1
    print("fixture freshness: all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
