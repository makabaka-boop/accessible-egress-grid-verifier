#!/usr/bin/env bash
# 本地（非 Docker）一键验收：先启动 api 与 web dev server，再跑 verify/verify.sh。
# 容器内验收请使用 compose：
#   docker compose build verify && docker compose run --rm verify
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"

cleanup() {
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> 启动 API（uvicorn :${API_PORT}）"
(
  cd api
  python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT}"
) &
API_PID=$!

echo "==> 启动 Web（vite :${WEB_PORT}，代理到 API）"
(
  cd web
  VITE_API_PROXY="http://127.0.0.1:${API_PORT}" npx vite --host 127.0.0.1 --port "${WEB_PORT}"
) &
WEB_PID=$!

# 等待两个服务就绪（最多 60 秒）
for i in $(seq 1 60); do
  curl -sf "http://127.0.0.1:${API_PORT}/api/health" >/dev/null 2>&1 && break
  sleep 1
done
for i in $(seq 1 60); do
  curl -sfI "http://127.0.0.1:${WEB_PORT}/" >/dev/null 2>&1 && break
  sleep 1
done

export API_BASE_URL="http://127.0.0.1:${API_PORT}"
export WEB_BASE_URL="http://127.0.0.1:${WEB_PORT}"
export PLAYWRIGHT_BASE_URL="http://127.0.0.1:${WEB_PORT}"

bash verify/verify.sh
