# Upbit AI Trader — 작업 진행 현황

> 최종 업데이트: 2026-03-21

---

## 아키텍처 개요

```
[프론트엔드 :3000]
      │  REST (axios)          WebSocket
      ▼                           ▼
[Gateway :8000]  ←── Redis pub/sub ←── [market_data_service]
      │                                 [strategy_service]
      ▼
[PostgreSQL :5432]   [Redis :6379]
```

### 서비스 목록

| 서비스 | 포트 | 역할 |
|--------|------|------|
| `postgres` | 5432 | 메인 데이터베이스 |
| `redis` | 6379 | 캐시 / pub-sub 브릿지 |
| `gateway` | 8000 | FastAPI REST + WebSocket |
| `market_data` | — | Upbit WS → DB + Redis 발행 |
| `strategy` | — | 60초 주기 신호 생성 → Redis 발행 |
| `execution` | — | 신호 폴링 → Upbit 주문 |
| `risk` | — | 위험관리 가드 (stub) |
| `backtest` | — | 백테스팅 엔진 (stub) |
| `frontend` | 3000 | Next.js 16 앱 |

---

## v0.1.0 — 초기 릴리즈 (최초 커밋)

### 백엔드

#### DB 모델 (SQLAlchemy 2.0 Async)

| 파일 | 테이블 | 설명 |
|------|--------|------|
| `libs/db/models/coin.py` | `coins` | KRW 마켓 목록 |
| `libs/db/models/candle.py` | `candles_1m` | 1분봉 OHLCV |
| `libs/db/models/indicator.py` | `indicator_snapshots` | RSI/MACD/BB/EMA |
| `libs/db/models/sentiment.py` | `sentiment_snapshots` | Claude 감성 분석 결과 |
| `libs/db/models/signal.py` | `signals` | AI 매매 신호 |
| `libs/db/models/order.py` | `orders`, `fills` | 주문 / 체결 |
| `libs/db/models/position.py` | `positions` | 현재 포지션 |
| `libs/db/models/backtest.py` | `backtest_runs`, `backtest_trades`, `backtest_metrics` | 백테스트 |

#### 핵심 라이브러리

| 파일 | 설명 |
|------|------|
| `libs/upbit/rest_client.py` | pyupbit 래퍼 (시세, 주문, 잔고) |
| `libs/upbit/websocket_client.py` | Upbit WS 클라이언트 (자동 재연결) |
| `libs/ai/claude_client.py` | Claude API 감성 분석 (10분 캐시) |
| `libs/config/settings.py` | pydantic-settings 환경변수 관리 |
| `libs/db/session.py` | AsyncSession factory |

#### 신호 생성 파이프라인

```
Candle 200개 조회
  → RSI(14) / MACD(12-26-9) / Bollinger Bands(20/2σ) / EMA(20,50) 계산
  → Claude API 감성 점수 (10분 캐시)
  → 신호 융합: final_score = 0.6×TA + 0.4×sentiment
  → side: buy(>0.2) / sell(<-0.2) / hold
  → DB 저장 + Redis "upbit:signal" 발행
```

#### Gateway REST API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/markets` | 전체 마켓 목록 |
| GET | `/api/v1/markets/{market}/candles` | 캔들 데이터 |
| GET | `/api/v1/signals` | AI 신호 목록 |
| GET | `/api/v1/orders` | 주문 내역 |
| GET | `/api/v1/positions` | 포지션 현황 |
| GET | `/api/v1/portfolio/equity-curve` | 수익 곡선 |
| POST | `/api/v1/backtests/runs` | 백테스트 실행 |
| POST | `/api/v1/secrets/upbit-keys` | 업비트 키 저장 |
| POST | `/api/v1/secrets/claude-key` | Claude 키 저장 |
| WS | `/ws/market` | 실시간 시세 |
| WS | `/ws/signals` | 실시간 AI 신호 |
| WS | `/ws/orders` | 실시간 주문 |

### 프론트엔드

| 경로 | 파일 | 설명 |
|------|------|------|
| `/` | `app/(dashboard)/page.tsx` | 메인 대시보드 |
| `/market` | `app/market/page.tsx` | 전체 마켓 |
| `/backtest` | `app/backtest/page.tsx` | 백테스트 |
| `/settings` | `app/settings/page.tsx` | API 키 설정 |

---

## v0.1.1 — Docker 환경 구성 및 버그 수정 (2026-03-21)

### 변경 내용

#### 1. `docker-compose.yml` 활용

기존 `docker-compose.yml` 기반으로 전체 서비스 컨테이너화 구동.

#### 2. `frontend/next.config.ts` — standalone 빌드 설정 추가

```ts
// 변경 전
const nextConfig: NextConfig = {};

// 변경 후
const nextConfig: NextConfig = { output: "standalone" };
```

- **원인**: Dockerfile이 `.next/standalone` 디렉토리를 COPY하는데 설정 누락으로 빌드 실패.

#### 3. `frontend/src/app/page.tsx` 삭제

- **원인**: Next.js App Router에서 `app/page.tsx`와 `app/(dashboard)/page.tsx`가 동일한 `/` URL로 충돌. `create-next-app` 기본 템플릿 페이지(Vercel 링크 포함) 삭제 후 `(dashboard)/page.tsx`가 `/`를 담당.

#### 4. `backend/.env` — Docker 서비스명으로 호스트 수정

```dotenv
# 변경 전
DATABASE_URL=postgresql+psycopg://trader:trader_secret@localhost:5432/upbit_trader
REDIS_URL=redis://localhost:6379/0

# 변경 후
DATABASE_URL=postgresql+psycopg://trader:trader_secret@postgres:5432/upbit_trader
REDIS_URL=redis://redis:6379/0
```

- **원인**: Docker 컨테이너 간 통신은 서비스명으로 DNS 해석. `localhost`는 컨테이너 자신을 가리킴.

#### 5. `backend/.env` — ENCRYPTION_KEY 유효한 Fernet 키로 교체

```dotenv
# 변경 전
ENCRYPTION_KEY=change-me-fernet-key-32-bytes-base64

# 변경 후
ENCRYPTION_KEY=h-b1lBh5HVD8nKT0S5YkdHdyVSOiPHmU62_xT1T-RXQ=
```

- **원인**: Fernet은 URL-safe base64 인코딩된 32바이트 키가 필요. 플레이스홀더 값은 `ValueError` 발생 → 설정 저장 500 에러.

#### 6. `apps/backtest_service/main.py` / `apps/risk_service/main.py` 생성

- **원인**: `docker-compose.yml`에 `python -m apps.backtest_service.main` 명령이 설정되어 있으나 파일 없음 → `Restarting` 루프. 서비스 stub 생성으로 안정화.

#### 7. Redis pub/sub 브릿지 구현

**문제**: `market_data_service`와 `strategy_service`가 데이터를 DB에만 저장하고 Gateway WebSocket으로 전달하지 않아 프론트엔드에 실시간 데이터 미표시.

**해결**: Redis pub/sub 채널을 브릿지로 사용.

```
market_data_service  →  Redis "upbit:ticker"  →  gateway market_ws.py  →  /ws/market
strategy_service     →  Redis "upbit:signal"  →  gateway signal_ws.py  →  /ws/signals
```

변경 파일:
- `apps/market_data_service/main.py`: `on_tick()` 에서 `redis.publish("upbit:ticker", ...)` 추가
- `apps/strategy_service/main.py`: 신호 저장 후 `redis.publish("upbit:signal", ...)` 추가
- `apps/gateway/ws/market_ws.py`: `start_redis_subscriber()` 함수 추가
- `apps/gateway/ws/signal_ws.py`: `start_redis_subscriber()` 함수 추가
- `apps/gateway/main.py`: lifespan에서 두 구독자 태스크 시작

---

## 현재 상태 (2026-03-21 기준)

| 항목 | 상태 |
|------|------|
| 전체 서비스 기동 | 정상 |
| 실시간 시세 WebSocket | 정상 (Redis 브릿지 완료) |
| 설정 페이지 키 저장 | 정상 (Fernet 키 수정) |
| AI 신호 WebSocket | 정상 (Redis 브릿지 완료) |
| AI 신호 생성 시작 | 최소 50개 1분봉 누적 후 (~50분) |
| 자동 주문 실행 | 미검증 (실계좌 API 키 필요) |
| 백테스트 UI | 미검증 |

---

## 미완료 / 다음 작업

| 우선순위 | 항목 | 메모 |
|----------|------|------|
| 높음 | 자동매매 E2E 검증 | 설정 페이지에서 키 입력 후 신호→주문 흐름 확인 |
| 높음 | `backtest_service` 실제 구현 | 현재 stub 상태 |
| 높음 | `risk_service` 실제 구현 | guards/ 로직은 있으나 main.py stub 상태 |
| 중간 | DB 마이그레이션 전략 | 현재 `create_all` 사용, Alembic으로 전환 필요 |
| 중간 | 백테스트 UI 연동 확인 | `/backtest` 페이지 E2E |
| 낮음 | 테스트 코드 작성 | pytest 단위 테스트 |
| 낮음 | CI/CD | GitHub Actions |
