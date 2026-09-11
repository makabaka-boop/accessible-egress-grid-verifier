#!/usr/bin/env bash
# 一次性验收脚本：后端 pytest + 前端 vitest + 真实 HTTP 契约冒烟 + Playwright e2e。
# 任一步失败即以非零码退出，不做任何占位放行。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_BASE_URL="${API_BASE_URL:-http://localhost:${API_PORT:-8000}}"
WEB_BASE_URL="${WEB_BASE_URL:-http://localhost:${WEB_PORT:-8080}}"
export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-$WEB_BASE_URL}"
echo "==> [1/4] 后端单元/接口测试 (pytest)"
(cd api && python3 -m pytest -q)

echo "==> [2/4] 前端单元测试 (vitest)"
(cd web && npm test)

echo "==> [3/4] 对运行中的 api/web 做 HTTP 契约冒烟"
API_BASE_URL="$API_BASE_URL" WEB_BASE_URL="$WEB_BASE_URL" \
    python3 scripts/smoke_contract.py

echo "==> [4/4] 浏览器端到端测试 (Playwright @ $PLAYWRIGHT_BASE_URL)"
(cd web && npx playwright test)

echo ""
echo "✅ 验收全部通过：pytest / vitest / HTTP 契约 / Playwright e2e"
