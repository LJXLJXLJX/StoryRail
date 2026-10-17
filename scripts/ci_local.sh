#!/usr/bin/env bash
# 与 .github/workflows/ci.yml 等价的本地工程门禁（README §工程门禁）。
# 用法：./scripts/ci_local.sh          （跳过 slow 标记的重测试）
#       ./scripts/ci_local.sh --full   （全跑，包括 slow）
# 需要 .venv 已安装 dev extras，web/node_modules 已 npm ci。
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  "") PYTEST_MARK="not slow" ;;
  --full) PYTEST_MARK="not slow or slow" ;;
  *)
    echo "用法：$0 [--full]" >&2
    exit 2
    ;;
esac

.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest -n auto -m "$PYTEST_MARK"
.venv/bin/python scripts/check_fixture_freshness.py
.venv/bin/python scripts/gen_web_contracts.py --check
.venv/bin/python scripts/check_doc_links.py

cd web
npm run typecheck
npm test
npm run build
cd ..

git diff --check
echo "ci_local: all gates green"
