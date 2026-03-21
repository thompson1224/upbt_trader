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
| `execution` | — | 신호 폴링 → Risk Guard → Upbit 주문 |
| `risk` | — | 위험관리 서비스 (stub, 로직은 execution에 통합) |
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
| `libs/upbit/rest_client.py` | pyupbit 래퍼 (시세, 주문, 잔고, **현재가**) |
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

- **원인**: Next.js App Router에서 `app/page.tsx`와 `app/(dashboard)/page.tsx`가 동일한 `/` URL로 충돌.

#### 4. `backend/.env` — Docker 서비스명으로 호스트 수정

```dotenv
# 변경 전
DATABASE_URL=postgresql+psycopg://trader:trader_secret@localhost:5432/upbit_trader
REDIS_URL=redis://localhost:6379/0

# 변경 후
DATABASE_URL=postgresql+psycopg://trader:trader_secret@postgres:5432/upbit_trader
REDIS_URL=redis://redis:6379/0
```

#### 5. `backend/.env` — ENCRYPTION_KEY 유효한 Fernet 키로 교체

- **원인**: 플레이스홀더 값은 `ValueError` 발생 → 설정 저장 500 에러.

#### 6. backtest/risk service stub 생성

- **원인**: `docker-compose.yml`에 실행 명령이 있으나 파일 없음 → `Restarting` 루프.

#### 7. Redis pub/sub 브릿지 구현

```
market_data_service  →  Redis "upbit:ticker"  →  gateway market_ws.py  →  /ws/market
strategy_service     →  Redis "upbit:signal"  →  gateway signal_ws.py  →  /ws/signals
```

---

## v0.1.2 — Risk Guard 연동 버그 수정 (2026-03-21)

### 배경

`execution_service`에 `PreTradeRiskGuard` import 및 호출 코드는 이미 존재했으나,
4개 P0 버그로 인해 위험관리 로직이 실제로 동작하지 않는 상태였음.

### 수정 내용

#### 1. `libs/upbit/rest_client.py` — `get_ticker()` 추가

```python
async def get_ticker(self, market: str) -> float | None:
    """현재가 조회 (공개 API)."""
```

- 실시간 현재가를 Upbit REST API에서 직접 조회

#### 2. `apps/market_data_service/main.py` — market_warning upsert 수정

```python
# 변경 전: is_active만 업데이트
set_={"is_active": True}

# 변경 후: market_warning도 동기화
set_={"is_active": True, "market_warning": "CAUTION" if ... else None}
```

- **원인**: 최초 INSERT 시에만 market_warning 설정, 이후 upsert에서 갱신 안 됨

#### 3. `apps/execution_service/main.py` — P0 버그 4개 수정

**Bug 1: `market_warning` bool 타입 오류**

```python
# 변경 전 (버그)
market_warning=bool(coin_obj.market_warning)  # bool("NONE") = True → 모든 거래 차단

# 변경 후
_MARKET_WARNING_VALUES = {"CAUTION", "WARNING", "PRICE_FLUCTUATIONS", "TRADING_VOLUME_SOARING"}
market_warning=_is_market_warning(coin.market_warning)  # "NONE" → False
```

**Bug 2 & 3: `daily_pnl`, `consecutive_losses` 항상 0 고정**

```python
# 변경 전 (버그)
daily_pnl=0.0,          # 일일 손실 한도 무력화
consecutive_losses=0,    # 연속 손실 제한 무력화

# 변경 후: _compute_risk_metrics() 단일 세션 배치 조회
# - KST 오늘 0시 이후 매도 fill 기반 daily_pnl 계산
# - 최근 매도 체결 20건 역순 손실 스트릭으로 consecutive_losses 계산
```

**Bug 4: `entry_price` 단위 오류**

```python
# 변경 전 (버그)
entry_price = signal.suggested_stop_loss * (1/(1-0.03)) if ... else 0
# fallback: krw_balance * 0.1  ← 잔고 금액을 가격으로 사용

# 변경 후: 실시간 현재가 사용
entry_price = await self.upbit.get_ticker(coin.market)
# ticker 실패 시 즉시 "rejected" 처리 (무한 재처리 방지)
```

**추가 수정:**
- N+1 쿼리 → 단일 세션 JOIN 배치 조회
- UTC 기준 → `ZoneInfo("Asia/Seoul")` KST 기준으로 교정
- ticker 실패 시 signal을 "rejected" 처리 (기존: "new" 상태 유지 → 무한 재시도)
- 미사용 import (`date`, `func`) 제거
- `coin_obj` 중복 DB 조회 제거

---

## 현재 상태 (2026-03-21 기준)

| 항목 | 상태 |
|------|------|
| 전체 서비스 기동 | ✅ 정상 |
| 실시간 시세 WebSocket | ✅ 정상 (Redis 브릿지) |
| AI 신호 생성 | ✅ 정상 (캔들 50개 이상 시 자동 시작) |
| Risk Guard 연동 | ✅ 정상 (v0.1.2 수정 완료) |
| 자동 주문 실행 | ✅ 준비 완료 (신호 생성 시 자동 동작) |
| 설정 페이지 키 저장 | ✅ 정상 |
| 백테스트 UI | ⚠️ 미검증 (backtest_service stub) |

---

## 미완료 / 다음 작업

| 우선순위 | 항목 | 메모 |
|----------|------|------|
| 높음 | `backtest_service` 실제 구현 | 현재 stub 상태 |
| 중간 | `daily_pnl` 정밀화 | 현재 포지션 avg_entry_price 기준 근사치, 별도 일일 스냅샷 테이블 설계 필요 |
| 중간 | DB 마이그레이션 전략 | 현재 `create_all` 사용, Alembic으로 전환 필요 |
| 중간 | 백테스트 UI 연동 확인 | `/backtest` 페이지 E2E |
| 낮음 | Settings API DB 저장 구현 | 현재 os.environ 임시 저장 (`.env`로 우회 가능) |
| 낮음 | 테스트 코드 작성 | pytest 단위 테스트 |
| 낮음 | CI/CD | GitHub Actions |
