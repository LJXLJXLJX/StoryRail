#!/usr/bin/env bash
# 与 .github/workflows/ci.yml 等价的本地工程门禁（README §工程门禁）。
# 用法：./scripts/ci_local.sh ；需要 .venv 已安装 dev extras，web/node_modules 已 npm ci。
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest
.venv/bin/python scripts/check_fixture_freshness.py
.venv/bin/python scripts/gen_web_contracts.py --check
.venv/bin/python scripts/check_doc_links.py
.venv/bin/python scripts/harness/benchmark/report.py --check

cd web
npm run typecheck
npm test
npm run build
cd ..

git diff --check
echo "ci_local: all gates green"
