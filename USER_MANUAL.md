# Upbit AI Trader — 사용자 매뉴얼

> 업비트 기반 AI 자동매매 웹앱 로컬 실행 가이드

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [최초 설치](#2-최초-설치)
3. [환경변수 설정](#3-환경변수-설정)
4. [데이터베이스 초기화](#4-데이터베이스-초기화)
5. [서버 실행](#5-서버-실행)
6. [서버 종료](#6-서버-종료)
7. [화면 구성 및 사용법](#7-화면-구성-및-사용법)
8. [자동매매 활성화](#8-자동매매-활성화)
9. [백테스트 실행](#9-백테스트-실행)
10. [트러블슈팅](#10-트러블슈팅)

---

## 1. 사전 요구사항

### 필수 소프트웨어

| 소프트웨어 | 버전 | 설치 확인 |
|-----------|------|----------|
| Python | 3.9+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| PostgreSQL | 14+ | `psql --version` |
| Redis | 6+ | `redis-cli --version` |

### Homebrew로 설치 (macOS)

```bash
brew install postgresql@14 redis
brew services start postgresql@14
brew services start redis
```

---

## 2. 최초 설치

### 2-1. 저장소 클론 후 프로젝트 루트로 이동

```bash
cd "/Users/ljmac/CC Projects/upbit-ai-trader"
```

### 2-2. 백엔드 Python 가상환경 설치

```bash
cd backend

# 가상환경 생성
python3 -m venv .venv

# 의존성 설치
.venv/bin/pip install -r requirements.txt

# greenlet 별도 설치 (SQLAlchemy async 필수)
.venv/bin/pip install greenlet
```

### 2-3. 프론트엔드 의존성 설치

```bash
cd ../frontend
npm install
```

### 2-4. PostgreSQL 데이터베이스 및 사용자 생성

```bash
psql postgres -c "CREATE USER trader WITH PASSWORD 'trader_secret';"
psql postgres -c "CREATE DATABASE upbit_trader OWNER trader;"
psql postgres -c "ALTER DATABASE upbit_trader OWNER TO trader;"
psql upbit_trader -c "GRANT ALL ON SCHEMA public TO trader;"
```

---

## 3. 환경변수 설정

```bash
cd "/Users/ljmac/CC Projects/upbit-ai-trader/backend"
cp .env.example .env
```

`.env` 파일을 열어 아래 항목을 반드시 입력하세요:

```dotenv
# ─── 필수 입력 ─────────────────────────────────────

# 업비트 API 키 (https://upbit.com/mypage/open_api_management)
UPBIT_ACCESS_KEY=여기에_액세스키_입력
UPBIT_SECRET_KEY=여기에_시크릿키_입력

# Claude API 키 (https://console.anthropic.com)
CLAUDE_API_KEY=여기에_클로드_API키_입력

# ─── 선택 입력 (기본값으로 동작) ───────────────────

# DB (기본값 사용 가능)
DATABASE_URL=postgresql+psycopg://trader:trader_secret@localhost:5432/upbit_trader

# Redis (기본값 사용 가능)
REDIS_URL=redis://localhost:6379/0

# 위험관리 파라미터
RISK_MAX_DAILY_LOSS_PCT=0.03     # 일일 최대 손실 3%
RISK_MAX_POSITION_PCT=0.10       # 종목당 최대 비중 10%
RISK_MAX_SINGLE_TRADE_PCT=0.01   # 단건 최대 거래 1%
```

> **주의**: 업비트 API 키는 **IP 허용** 설정이 필요합니다. 업비트 마이페이지 > Open API 관리에서 현재 IP를 화이트리스트에 추가하세요.

---

## 4. 데이터베이스 초기화

최초 1회만 실행합니다.

```bash
cd "/Users/ljmac/CC Projects/upbit-ai-trader/backend"
.venv/bin/alembic upgrade head
```

성공 시:
```
INFO  [alembic.runtime.migration] Running upgrade -> 001, initial schema
```

---

## 5. 서버 실행

### 백엔드 (터미널 1)

```bash
cd "/Users/ljmac/CC Projects/upbit-ai-trader/backend"
bash scripts/run_local.sh
```

실행되는 서비스:
| 서비스 | 포트 | 역할 |
|--------|------|------|
| Gateway API | 8000 | REST API + WebSocket |
| Market Data | - | 업비트 실시간 수집 |
| Strategy | - | AI 신호 생성 (60초 주기) |
| Execution | - | 자동 주문 실행 |

정상 실행 확인:
```
INFO:     Application startup complete.        ← Gateway 정상
INFO:__main__:Synced 243 KRW markets           ← Market Data 정상
INFO:__main__:Strategy service started.        ← Strategy 정상
INFO:__main__:Execution service started.       ← Execution 정상
```

### 프론트엔드 (터미널 2)

```bash
cd "/Users/ljmac/CC Projects/upbit-ai-trader/frontend"
npm run dev
```

브라우저에서 접속:
- **앱**: http://localhost:3000
- **API 문서 (Swagger)**: http://localhost:8000/docs

---

## 6. 서버 종료

```bash
# 백엔드 (터미널 1에서 Ctrl+C) 또는 강제 종료:
pkill -f "uvicorn apps.gateway"
pkill -f "apps.market_data_service.main"
pkill -f "apps.strategy_service.main"
pkill -f "apps.execution_service.main"

# 프론트엔드 (터미널 2에서 Ctrl+C) 또는:
pkill -f "next dev"
```

---

## 7. 화면 구성 및 사용법

### 메인 대시보드 (`/`)

```
┌──────────────────────────────────────────┐
│  헤더: 잔고 | 오늘 손익 | 연결 상태       │
├──────────┬───────────────────────────────┤
│ 사이드바  │  마켓 워치리스트               │
│ - 대시보드│  AI 신호 패널                 │
│ - 마켓   │  포지션 현황                  │
│ - 설정   │  캔들 차트                    │
│ - 백테스트│                               │
└──────────┴───────────────────────────────┘
```

| 패널 | 설명 |
|------|------|
| 마켓 워치리스트 | 실시간 시세, 등락률 |
| AI 신호 패널 | 최신 매수/매도 신호, 신뢰도, TA/감성 점수 |
| 포지션 현황 | 현재 보유 종목, 평균단가, 평가손익 |
| 캔들 차트 | TradingView 기반 1분봉 차트 |

### AI 신호 패널 읽는 법

| 필드 | 의미 |
|------|------|
| `side: buy` | 매수 신호 |
| `side: sell` | 매도 신호 |
| `side: hold` | 관망 |
| `confidence` | 신뢰도 (0~100%) |
| `ta_score` | 기술적 지표 점수 (-1~1) |
| `sentiment_score` | Claude AI 감성 점수 (-1~1) |
| `final_score` | 최종 점수 = 0.6×TA + 0.4×감성 |
| `suggested_stop_loss` | 권장 손절가 |
| `suggested_take_profit` | 권장 익절가 |

### 마켓 페이지 (`/market`)

전체 243개 KRW 마켓 목록, 실시간 시세 확인

### 설정 페이지 (`/settings`)

- 자동매매 활성화/비활성화
- 위험관리 파라미터 조정
- API 키 관리

---

## 8. 자동매매 활성화

> **주의**: 실제 자산이 거래됩니다. 소액으로 테스트 후 사용하세요.

1. `/settings` 페이지 접속
2. 업비트 API 키 입력 (또는 `.env` 파일에 설정)
3. 위험관리 파라미터 확인:
   - 일일 최대 손실: 기본 3% (초과 시 당일 거래 중단)
   - 종목당 최대 비중: 기본 10%
   - 단건 최대 거래: 기본 1%
4. 자동매매 토글 **ON**

**신호 → 주문 흐름:**
```
Strategy (60초마다 신호 생성)
  └→ final_score > 0.2 → BUY 신호
  └→ final_score < -0.2 → SELL 신호
       └→ Risk Guard 검증 통과
            └→ Upbit API 주문 전송
                 └→ 체결 동기화 (10초마다)
```

---

## 9. 백테스트 실행

`/backtest` 페이지에서:

| 입력 | 설명 |
|------|------|
| 마켓 | 백테스트할 종목 (예: KRW-BTC) |
| 시작일 / 종료일 | 기간 선택 |
| 초기 자본 | 시뮬레이션 시작 금액 |
| 전략 | hybrid_v1 (기본) |

결과:
| 지표 | 설명 |
|------|------|
| 총 수익률 | 기간 전체 수익률 |
| 최대 낙폭 (MDD) | 최대 손실 구간 |
| 샤프 비율 | 위험 대비 수익률 |
| 승률 | 수익 거래 / 전체 거래 |
| 총 거래 횟수 | |

---

## 10. 트러블슈팅

### PostgreSQL 연결 오류

```bash
# PostgreSQL 실행 확인
brew services list | grep postgresql

# 재시작
brew services restart postgresql@14

# 연결 테스트
psql -U trader -d upbit_trader -c "SELECT 1;"
```

### Redis 연결 오류

```bash
brew services restart redis
redis-cli ping  # PONG 응답 확인
```

### 패키지 설치 오류

```bash
cd "/Users/ljmac/CC Projects/upbit-ai-trader/backend"
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install greenlet
```

### 포트 충돌 (8000, 3000)

```bash
# 포트 점유 프로세스 확인
lsof -i :8000
lsof -i :3000

# 강제 종료
lsof -ti:8000 | xargs kill -9
lsof -ti:3000 | xargs kill -9
```

### Alembic 마이그레이션 오류

```bash
cd "/Users/ljmac/CC Projects/upbit-ai-trader/backend"

# 현재 상태 확인
.venv/bin/alembic current

# 처음부터 다시 (주의: 데이터 삭제)
psql -U trader -d upbit_trader -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
psql -U trader -d upbit_trader -c "GRANT ALL ON SCHEMA public TO trader;"
.venv/bin/alembic upgrade head
```

### 업비트 API 오류

- `401 Unauthorized`: API 키 확인 및 IP 화이트리스트 등록
- `429 Too Many Requests`: 요청 빈도 초과 (strategy 루프 간격 조정)
- WebSocket 연결 끊김: 자동 재연결 (최대 30초 지수백오프)

### 전략 서비스가 신호를 생성하지 않을 때

1. DB에 코인이 있는지 확인: `psql -U trader -d upbit_trader -c "SELECT COUNT(*) FROM coins;"`
2. 캔들 데이터가 쌓이고 있는지 확인 (RSI 최소 15개, MACD 최소 35개 필요)
3. `LOG_LEVEL=DEBUG` 설정 후 로그 확인

---

## API 레퍼런스

백엔드 실행 후 http://localhost:8000/docs 에서 Swagger UI로 전체 API 확인 가능.

주요 엔드포인트:

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/markets` | 전체 마켓 목록 |
| GET | `/api/v1/markets/{market}/candles` | 캔들 데이터 |
| GET | `/api/v1/signals` | AI 신호 목록 |
| GET | `/api/v1/orders` | 주문 내역 |
| GET | `/api/v1/portfolio` | 포트폴리오 현황 |
| POST | `/api/v1/backtests` | 백테스트 실행 |
| WS | `/ws/market` | 실시간 시세 WebSocket |
| WS | `/ws/signals` | 실시간 신호 WebSocket |
| WS | `/ws/orders` | 실시간 주문 WebSocket |
