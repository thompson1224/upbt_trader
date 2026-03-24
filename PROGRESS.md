# Upbit AI Trader — 작업 진행 현황

> 최종 업데이트: 2026-03-24

---

## 아키텍처 개요

```
[프론트엔드 :3000]
      │  REST (axios)          WebSocket
      ▼                           ▼
[Gateway :8000]  ←── Redis pub/sub ←── [market_data_service]
      │                                 [strategy_service]
      │                                 [execution_service]
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
| `strategy` | — | 60초 주기 신호 생성 (Groq AI) → Redis 발행 |
| `execution` | — | 신호 폴링 → Risk Guard → Upbit 주문 → Redis 발행 |
| `risk` | — | 위험관리 서비스 (stub, 로직은 execution에 통합) |
| `backtest` | — | 백테스팅 엔진 (stub) |
| `frontend` | 3000 | Next.js 앱 |

---

## v0.1.0 — 초기 릴리즈

### 백엔드

#### DB 모델 (SQLAlchemy 2.0 Async)

| 파일 | 테이블 | 설명 |
|------|--------|------|
| `libs/db/models/coin.py` | `coins` | KRW 마켓 목록 |
| `libs/db/models/candle.py` | `candles_1m` | 1분봉 OHLCV |
| `libs/db/models/indicator.py` | `indicator_snapshots` | RSI/MACD/BB/EMA |
| `libs/db/models/sentiment.py` | `sentiment_snapshots` | AI 감성 분석 결과 |
| `libs/db/models/signal.py` | `signals` | AI 매매 신호 |
| `libs/db/models/order.py` | `orders`, `fills` | 주문 / 체결 |
| `libs/db/models/position.py` | `positions` | 현재 포지션 |
| `libs/db/models/backtest.py` | `backtest_runs`, `backtest_trades`, `backtest_metrics` | 백테스트 |

#### 신호 생성 파이프라인

```
Candle 200개 조회
  → RSI(14) / MACD(12-26-9) / Bollinger Bands(20/2σ) / EMA(20,50) 계산
  → AI 감성 분석 (10분 캐시)
  → 신호 융합: final_score = 0.6×TA + 0.4×sentiment
  → side: buy(>0.2) / sell(<-0.2) / hold
  → DB 저장 + Redis "upbit:signal" 발행
```

---

## v0.1.1 — Docker 환경 구성 및 버그 수정 (2026-03-21)

- Next.js standalone 빌드 설정 추가
- `app/page.tsx` vs `app/(dashboard)/page.tsx` URL 충돌 해결
- Docker 서비스명으로 DB/Redis 호스트 수정
- ENCRYPTION_KEY 유효한 Fernet 키로 교체
- backtest/risk service stub 생성
- Redis pub/sub 브릿지 구현 (`market_ws.py`, `signal_ws.py`)

---

## v0.1.2 — Risk Guard 연동 버그 수정 (2026-03-21)

`execution_service`에 P0 버그 4개 수정:

1. `market_warning` bool 타입 오류 → `_is_market_warning()` 함수로 교정
2. `daily_pnl` 항상 0 → KST 오늘 0시 이후 매도 fill 기반 실시간 계산
3. `consecutive_losses` 항상 0 → 최근 매도 체결 역순 손실 스트릭 계산
4. `entry_price` 단위 오류 → `get_ticker()` 실시간 현재가 사용

추가:
- `libs/upbit/rest_client.py` — `get_ticker()` 추가
- N+1 쿼리 → 단일 세션 JOIN 배치 조회
- UTC → KST 기준 교정

---

## v0.2.0 — 자동매매 파이프라인 완성 + Groq AI 교체 (2026-03-24)

### AI 엔진 교체: Claude/Ollama/Gemini → Groq

| 항목 | 이전 | 현재 |
|------|------|------|
| AI 제공자 | Ollama (로컬) → Gemini (클라우드) | **Groq** (클라우드) |
| 모델 | llama-3.2 / gemini-1.5-flash | **llama-3.1-8b-instant** |
| 비용 | 로컬 GPU 또는 유료 | **무료 14,400 req/day** |
| 지연시간 | 수 초 | ~0.3초 (Groq 특화 추론 칩) |
| 설정 | `OLLAMA_BASE_URL` / `GEMINI_API_KEY` | **`GROQ_API_KEY`** |

#### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `backend/libs/ai/groq_client.py` | **신규** — httpx + Semaphore(5), JSON mode |
| `backend/libs/ai/gemini_client.py` | **삭제** |
| `backend/libs/ai/ollama_client.py` | **삭제** |
| `backend/libs/config/settings.py` | `groq_api_key`, `groq_model` 추가 |
| `backend/apps/strategy_service/main.py` | `GroqClient` 사용으로 교체 |
| `backend/apps/gateway/api/v1/settings.py` | `POST /secrets/groq-key` 엔드포인트 |
| `backend/.env` | `GROQ_API_KEY`, `GROQ_MODEL` 추가 |

### 자동매매 파이프라인 완성

#### 백엔드 신규/수정

| 파일 | 변경 내용 |
|------|-----------|
| `backend/apps/gateway/ws/trade_event_ws.py` | **신규** — Redis `upbit:trade_event` → `/ws/trade-events` 브릿지 |
| `backend/apps/gateway/ws/trade_event_ws.py` | Redis `upbit:position_update` → `/ws/portfolio` 브릿지 |
| `backend/apps/gateway/main.py` | trade_event, portfolio 구독 태스크 등록 |
| `backend/apps/gateway/api/v1/orders.py` | Coin JOIN으로 market명 반환, bid/ask → buy/sell 매핑 |

#### 프론트엔드 신규/수정

**스토어 (Zustand)**

| 파일 | 변경 내용 |
|------|-----------|
| `frontend/src/store/useTradeStore.ts` | `setAutoTrading(enabled)` 추가 |
| `frontend/src/store/useMarketStore.ts` | `minConfidence` 상태 + `setMinConfidence()` |
| `frontend/src/store/useNotificationStore.ts` | **신규** — 토스트 알림 (최대 5개, 5초 자동 해제) |

**훅**

| 파일 | 변경 내용 |
|------|-----------|
| `frontend/src/hooks/useUpbitWS.ts` | `useTradeEventWS()` 훅 추가 — `/ws/trade-events` 구독 → 토스트 |

**컴포넌트**

| 파일 | 변경 내용 |
|------|-----------|
| `frontend/src/components/layout/AutoTradeToggle.tsx` | **신규** — 활성화 확인 다이얼로그, 낙관적 업데이트 |
| `frontend/src/components/layout/GlobalHeader.tsx` | `<AutoTradeToggle />` 사용, 서버 상태 hydration |
| `frontend/src/components/dashboard/PositionPanel.tsx` | WebSocket ticker에서 실시간 P&L 계산 (폴링 없음) |
| `frontend/src/components/dashboard/ConfidenceFilter.tsx` | **신규** — 슬라이더 (0-100%, 5% 단위) |
| `frontend/src/components/dashboard/AISignalPanel.tsx` | `<ConfidenceFilter />` 추가, minConfidence 필터링 |
| `frontend/src/components/common/ToastContainer.tsx` | **신규** — 우하단 고정, 타입별 색상 |
| `frontend/src/components/common/WSInitializer.tsx` | `useTradeEventWS()` 등록 |

**페이지/레이아웃**

| 파일 | 변경 내용 |
|------|-----------|
| `frontend/src/app/(dashboard)/layout.tsx` | `<ToastContainer />` 추가 |
| `frontend/src/app/settings/page.tsx` | Groq API 키 입력 UI (orange Zap 아이콘) |
| `frontend/src/app/orders/page.tsx` | **신규** — 주문 내역 (state/side 필터, 10초 갱신) |
| `frontend/src/components/layout/Sidebar.tsx` | `/orders` 네비게이션 추가 |

### Gateway REST/WebSocket API (누적)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/markets` | 전체 마켓 목록 |
| GET | `/api/v1/markets/{market}/candles` | 캔들 데이터 |
| GET | `/api/v1/signals` | AI 신호 목록 |
| GET | `/api/v1/orders` | 주문 내역 |
| GET | `/api/v1/positions` | 포지션 현황 |
| GET | `/api/v1/portfolio/equity-curve` | 수익 곡선 |
| POST | `/api/v1/backtests/runs` | 백테스트 실행 |
| POST | `/api/v1/secrets/upbit-keys` | 업비트 API 키 저장 (암호화) |
| POST | `/api/v1/secrets/groq-key` | Groq API 키 저장 |
| PATCH | `/api/v1/settings/auto-trade` | 자동매매 ON/OFF |
| GET | `/api/v1/settings/auto-trade` | 자동매매 상태 조회 |
| WS | `/ws/market` | 실시간 시세 (ticker) |
| WS | `/ws/signals` | 실시간 AI 신호 |
| WS | `/ws/trade-events` | 실시간 체결/SL/TP 알림 |
| WS | `/ws/portfolio` | 실시간 포지션 업데이트 |

---

## v0.2.1 — 안정성 버그 수정 (2026-03-24)

### 수정된 버그

#### 1. market_data_service Redis stale 연결 (`market_data_service/main.py`)
- **증상**: 서비스 장기 가동(3일+) 후 실시간 시세가 프론트엔드에 미전달
- **원인**: TCP 타임아웃 후 stale된 `aioredis` 클라이언트가 `publish()` 예외를 조용히 삼킴
- **수정**: `_get_redis()` 함수 추가 — `ping()` 헬스체크 후 stale 연결 자동 재생성

#### 2. Gateway WebSocket 좀비 구독 누적 (`gateway/ws/*.py`)
- **증상**: uvicorn `--reload` 트리거마다 Redis 구독자가 누적(1 → N개), 동일 데이터 N회 브로드캐스트
- **원인**: `asyncio.CancelledError`는 `BaseException`이므로 `except Exception`에서 잡히지 않아 Redis 연결이 닫히지 않음
- **수정**: 4개 구독 함수 모두에 `except asyncio.CancelledError: raise` + `finally: await r.aclose()` 추가
  - `gateway/ws/market_ws.py` — `start_redis_subscriber()`
  - `gateway/ws/signal_ws.py` — `start_redis_subscriber()`
  - `gateway/ws/trade_event_ws.py` — `start_trade_event_subscriber()`, `start_portfolio_subscriber()`

#### 3. Groq TPM 초과 방지 (`strategy_service/main.py`)
- **증상**: Groq API 429 오류 (`Limit 6000, Used 5997`)
- **원인**: 20개 마켓 × ~300 tokens = ~6,000 tokens/분, Groq 무료 플랜 TPM 한도 초과
- **수정**:
  - `TOP_MARKETS_BY_VOLUME`: 20 → **10** (분당 ~3,000 tokens)
  - `batch_size`: 10 → **5**, 배치 간 10초 딜레이 추가

---

## 현재 상태 (2026-03-24 기준)

| 항목 | 상태 |
|------|------|
| 전체 서비스 기동 | ✅ 정상 |
| 실시간 시세 WebSocket | ✅ 정상 (Redis 브릿지) |
| AI 신호 생성 (Groq) | ✅ 정상 (캔들 50개 이상 시 자동 시작) |
| Risk Guard 연동 | ✅ 정상 |
| 자동 주문 실행 | ✅ 정상 (자동매매 ON 시) |
| SL/TP 모니터 | ✅ 정상 (10초 주기) |
| 체결 이벤트 WebSocket | ✅ 정상 (`/ws/trade-events`) |
| 포지션 실시간 업데이트 | ✅ 정상 (`/ws/portfolio`) |
| 자동매매 ON/OFF 토글 | ✅ 정상 (확인 다이얼로그) |
| 실시간 P&L | ✅ 정상 (WS ticker 기반, 폴링 없음) |
| 신뢰도 필터 슬라이더 | ✅ 정상 |
| 토스트 알림 | ✅ 정상 (체결/SL/TP/리젝) |
| 주문 내역 페이지 | ✅ 정상 |
| 설정 페이지 (Groq 키) | ✅ 정상 |
| 백테스트 UI | ⚠️ 미검증 (backtest_service stub) |

---

## 미완료 / 다음 작업

| 우선순위 | 항목 | 메모 |
|----------|------|------|
| 높음 | `backtest_service` 실제 구현 | 현재 stub 상태 |
| 중간 | `daily_pnl` 정밀화 | 별도 일일 스냅샷 테이블 설계 필요 |
| 중간 | DB 마이그레이션 전략 | 현재 `create_all`, Alembic 전환 필요 |
| 중간 | 백테스트 UI 연동 확인 | `/backtest` 페이지 E2E |
| 낮음 | Settings API DB 저장 구현 | 현재 os.environ 임시 저장 |
| 낮음 | 테스트 코드 작성 | pytest 단위 테스트 |
| 낮음 | CI/CD | GitHub Actions |
