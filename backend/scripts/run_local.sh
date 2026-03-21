#!/bin/bash
# 로컬 개발 환경 실행 스크립트

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

cd "$BACKEND_DIR"

# .env 체크
if [ ! -f .env ]; then
  echo "ERROR: .env 파일이 없습니다. .env.example을 복사하여 설정하세요."
  echo "  cp .env.example .env"
  exit 1
fi

export PYTHONPATH="$BACKEND_DIR"

# venv Python/uvicorn 경로
PYTHON="$BACKEND_DIR/.venv/bin/python"
UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"

echo "=== 게이트웨이 서버 시작 (port 8000) ==="
"$UVICORN" apps.gateway.main:app --host 0.0.0.0 --port 8000 --reload &
GATEWAY_PID=$!

echo "=== 마켓 데이터 서비스 시작 ==="
"$PYTHON" -m apps.market_data_service.main &
MARKET_PID=$!

echo "=== 전략 서비스 시작 ==="
"$PYTHON" -m apps.strategy_service.main &
STRATEGY_PID=$!

echo "=== 주문 실행 서비스 시작 ==="
"$PYTHON" -m apps.execution_service.main &
EXECUTION_PID=$!

echo ""
echo "서비스 실행 중..."
echo "  Gateway:     http://localhost:8000"
echo "  Docs:        http://localhost:8000/docs"
echo "  Ctrl+C 로 종료"

# 종료 핸들러
cleanup() {
  echo "서비스 종료 중..."
  kill $GATEWAY_PID $MARKET_PID $STRATEGY_PID $EXECUTION_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
