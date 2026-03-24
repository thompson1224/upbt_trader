#!/bin/sh

set -eu

echo "[1/5] docker compose ps"
docker compose ps

echo "[2/5] gateway health"
curl -fsS http://localhost:8000/health
echo

echo "[3/5] trading switches"
curl -fsS http://localhost:8000/api/v1/settings/auto-trade
echo
curl -fsS http://localhost:8000/api/v1/settings/external-position-stop-loss
echo

echo "[4/5] audit events"
curl -fsS "http://localhost:8000/api/v1/audit-events?limit=5"
echo

echo "[5/5] frontend /settings via internal service"
docker compose exec -T gateway python - <<'PY'
import urllib.request
with urllib.request.urlopen("http://frontend:3000/settings", timeout=20) as r:
    print(r.status)
PY
