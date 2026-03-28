#!/bin/sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"
BACKEND_DIR="${ROOT_DIR}/backend"

echo "[1/4] frontend lint"
(cd "${FRONTEND_DIR}" && npm run lint)

echo "[2/4] frontend build"
(cd "${FRONTEND_DIR}" && npx next build --webpack)

echo "[3/4] backend unit tests"
if [ ! -x "${BACKEND_DIR}/.venv/bin/pytest" ]; then
  echo "backend/.venv/bin/pytest not found or not executable" >&2
  exit 1
fi
(cd "${BACKEND_DIR}" && ./.venv/bin/pytest tests/unit)

echo "[4/4] compose smoke"
(cd "${ROOT_DIR}" && sh scripts/ops_smoke_check.sh)
