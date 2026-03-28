#!/bin/sh

set -eu

GATEWAY_HOST_PORT="${GATEWAY_HOST_PORT:-8001}"
GATEWAY_BASE_URL="${GATEWAY_BASE_URL:-http://localhost:${GATEWAY_HOST_PORT}}"
FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-3000}"
FRONTEND_BASE_URL="${FRONTEND_BASE_URL:-http://localhost:${FRONTEND_HOST_PORT}}"

echo "[1/7] docker compose ps"
docker compose ps

echo "[2/7] gateway health"
curl -fsS "${GATEWAY_BASE_URL}/health"
echo

echo "[3/7] trading switches"
curl -fsS "${GATEWAY_BASE_URL}/api/v1/settings/auto-trade"
echo
curl -fsS "${GATEWAY_BASE_URL}/api/v1/settings/external-position-stop-loss"
echo

echo "[4/7] audit events"
curl -fsS "${GATEWAY_BASE_URL}/api/v1/audit-events?limit=5"
echo

echo "[5/7] performance summary"
curl -fsS "${GATEWAY_BASE_URL}/api/v1/portfolio/performance?limit=5" | grep -q '"summary"'
echo "ok"

echo "[6/7] frontend host routes"
root_html="$(curl -fsS "${FRONTEND_BASE_URL}/")"
printf '%s' "${root_html}" | grep -q "Upbit AI Trader"
printf '%s' "${root_html}" | grep -q "연결 확인 중"
printf '%s' "${root_html}" | grep -q "자동매매 확인 중"
! printf '%s' "${root_html}" | grep -q "연결 끊김"
! printf '%s' "${root_html}" | grep -q "자동매매 OFF"

backtest_html="$(curl -fsS "${FRONTEND_BASE_URL}/backtest")"
printf '%s' "${backtest_html}" | grep -q "백테스팅"
printf '%s' "${backtest_html}" | grep -q "자동매매 확인 중"
! printf '%s' "${backtest_html}" | grep -q "자동매매 OFF"

performance_html="$(curl -fsS "${FRONTEND_BASE_URL}/performance/market/KRW-BTC")"
printf '%s' "${performance_html}" | grep -q "KRW-BTC"
echo "ok"

echo "[7/7] frontend /settings via internal service"
docker compose exec -T gateway python - <<'PY'
import urllib.request
with urllib.request.urlopen("http://frontend:3000/settings", timeout=20) as r:
    print(r.status)
PY
