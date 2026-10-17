"""文档链接检查：仓库内 Markdown 的相对链接必须可达。

用法：
    .venv/bin/python scripts/check_doc_links.py

扫描仓库内全部 ``*.md``，忽略代码块内的示例，检查 ``[文本](目标)`` /
``![文本](目标)`` 形式的相对路径链接是否指向仓库内真实存在的文件或目录。
外部 URL、纯锚点和 mailto 不检查。任何断链都会打印并返回非零状态，
供 ``scripts/ci_local.sh`` 与 ``.github/workflows/ci.yml`` 使用。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

# 不参与检查的目录：虚拟环境、依赖、构建产物与业务项目状态。
# 隐藏目录（.venv/.research_sources/.stories 等）一律跳过。
SKIP_DIRS = {
    "build",
    "dist",
    "node_modules",
    "var",
    "__pycache__",
    "storyrail.egg-info",
}

_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        parts = path.relative_to(ROOT).parts
        if any(part.startswith(".") or part in SKIP_DIRS for part in parts):
            continue
        files.append(path)
    return sorted(files)


def _strip_fenced_code(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            lines.append("")
            continue
        lines.append("" if in_fence else line)
    return "\n".join(lines)


def _is_external(target: str) -> bool:
    return (
        target.startswith(("http://", "https://", "mailto:", "tel:", "#", "file://"))
        or target.startswith("<")
        or "://" in target
    )


def check() -> list[str]:
    problems: list[str] = []
    for path in _markdown_files():
        text = _strip_fenced_code(path.read_text(encoding="utf-8"))
        for match in _LINK.finditer(text):
            raw = match.group(1)
            if _is_external(raw):
                continue
            target = unquote(raw.split("#", 1)[0].split("?", 1)[0])
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                line = text[: match.start()].count("\n") + 1
                problems.append(f"{path.relative_to(ROOT)}:{line}: 断链 -> {raw}")
    return problems


def main() -> int:
    files = _markdown_files()
    problems = check()
    if problems:
        print(f"文档链接检查失败：{len(problems)} 处断链")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"文档链接检查通过：{len(files)} 个 Markdown 文件，无断链。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
