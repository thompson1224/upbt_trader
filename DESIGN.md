# Upbit AI Trader - Architecture Design

**Version:** 0.3.0
**Last Updated:** 2026-03-29

---

## Overview

AI 기반 암호화폐 자동매매 플랫폼. Upbit 한국 거래소의 KRW 마켓에서 거래.

**핵심 기능:**
- 기술적 분석 (RSI, MACD, 볼린저밴드, EMA)
- AI 감성 분석 (Groq LLM + Fear & Greed Index)
- 위험 관리 (일일 손익 제한, 연속 손실 제한)
- 백테스트 및 Walk-forward 분석

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (Next.js)                              │
│                    http://localhost:3000 (default)                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           API Gateway (FastAPI)                              │
│                      http://localhost:8001                                   │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   Settings   │  │   Signals    │  │   Orders     │  │  Portfolio   │   │
│  │     API      │  │     API      │  │     API      │  │     API      │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   Markets    │  │    Audit     │  │  Backtests   │  │    Risk      │   │
│  │     API      │  │     API      │  │     API      │  │     API      │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
         │                                                    │
         ▼                                                    │
┌─────────────────┐                         ┌─────────────────────────────────┐
│     Redis       │◄────── Pub/Sub ──────────│       Backend Services          │
│   (Message Bus) │                          └─────────────────────────────────┘
└─────────────────┘                                      │
    │                                                      │
    ├── upbit:signal ──────────────► strategy_service ──► signals table
    ├── upbit:trade_event ─────────► risk_service
    ├── upbit:risk:request ────────► risk_service (RPC)
    ├── upbit:risk:response ◄────── risk_service (RPC)
    └── upbit:orderbook ───────────► market_data_service
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Backend Services (Python)                            │
├─────────────────┬─────────────────┬─────────────────┬───────────────────────┤
│ market_data     │   strategy      │   execution     │      risk            │
│ service         │   service       │   service      │      service         │
│                 │                 │                 │                       │
│ - WebSocket     │ - TA calculation│ - Signal poll  │ - Account tracking   │
│ - Candle fetch │ - Sentiment (Groq│ - Order exec   │ - Daily P&L          │
│ - Indicator     │   + Fear&Greed)│ - SL/TP check  │ - Consecutive losses │
│                 │ - Signal fusion │ - Risk guard   │ - Portfolio monitor  │
│                 │                 │                 │                       │
├─────────────────┴─────────────────┴─────────────────┴───────────────────────┤
│                         backtest_service                                     │
│                    (Polling Worker)                                         │
│                    - Single mode backtest                                   │
│                    - Walk-forward analysis                                   │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PostgreSQL                                        │
│                                                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────────┐    │
│  │  coins  │  │candles  │  │ signals │  │ orders  │  │backtest_*   │    │
│  │         │  │  _1m    │  │         │  │         │  │  (runs,     │    │
│  │         │  │         │  │         │  │         │  │  trades,    │    │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │  metrics,   │    │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │  windows)   │    │
│  │positions│  │  fills  │  │indicators│  │sentiment │  └─────────────┘    │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Services

### 1. Gateway Service
**Port:** 8001
**Technology:** FastAPI + Uvicorn

REST API의 진입점. 모든 클라이언트 요청을 처리.

**주요 API:**
| Prefix | Description |
|--------|-------------|
| `/api/v1/settings/*` | API keys, auto-trade, thresholds |
| `/api/v1/signals/*` | Signal history and status |
| `/api/v1/orders/*` | Order history |
| `/api/v1/portfolio/*` | Positions, daily P&L |
| `/api/v1/backtests/*` | Backtest runs and results |
| `/api/v1/risk/*` | Risk metrics and status |
| `/api/v1/markets/*` | Market data |
| `/api/v1/audit/*` | Audit log |

### 2. Market Data Service
**Technology:** Python + httpx + asyncio

Upbit WebSocket 및 REST API에서 시장 데이터 수집.

**职责:**
- 1분봉 캔들 수집 → `candles_1m` 테이블
- 실시간 호가창 → Redis `upbit:orderbook`
- 지표 계산 → `indicator_snapshots` 테이블

### 3. Strategy Service
**Technology:** Python + pandas + asyncio

신호 생성 핵심 로직.

**처리 흐름:**
1. 상위 10개 코인 선별 (24h 거래량 기준)
2. 각 코인별 200개 1분봉 로드
3. 기술적 지표 계산 (RSI, MACD, Bollinger, EMA)
4. **Groq 감성 분석** (30분 캐시, 코인별)
5. Fear & Greed Index (Groq 실패 시 폴백)
6. TA(60%) + Sentiment(40%) 융합
7. 1시간봉 추세 필터
8. 신호 생성 → `signals` 테이블
9. Redis pub/sub으로 신호 브로드캐스트

**신호 융합 공식:**
```
final_score = (0.6 * ta_score * ta_confidence + 0.4 * sentiment_score * sentiment_confidence) 
              / (0.6 * ta_confidence + 0.4 * sentiment_confidence)
```

### 4. Execution Service
**Technology:** Python + asyncio

주문 실행 및 체결 처리.

**주요 기능:**
- 신호 폴링 (5초 간격)
- **위험 평가** (RPC → risk_service, 폴백: 로컬 PreTradeRiskGuard)
- 업비트 REST API로 주문 전송
- 미체결 주문 동기화 (10초 간격)
- SL/TP 모니터링 (10초 간격)
- 잔고 동기화 (30초 간격)

**RPC 통신 (risk_service):**
```
Request:  upbit:risk:request  {request_id, side, market, suggested_qty, entry_price, stop_loss, account}
Response: upbit:risk:response {request_id, approved, reason, adjusted_qty}
```

### 5. Risk Service
**Technology:** Python + asyncio

계좌 위험 관리 및 모니터링.

**주요 기능:**
- Redis pub/sub으로 trade event 수신
- **계좌 상태 추적** (일일 P&L, 연속 손실, 가용 잔고)
- **포트폴리오 위험 평가** (60초 간격)
- Risk metrics 발행 (30초 간격) → Redis
- RPC 핸들러 (risk_service가 직접 evaluate)

**알림 타입:**
- `daily_loss_limit` - 일일 손실 제한 도달
- `consecutive_losses` - 연속 손실 임계값 초과
- `max_positions` - 최대 포지션 수 초과
- `position_concentration` - 포지션 집중도 과다

### 6. Backtest Service
**Technology:** Python + pandas + asyncio

백테스트 워커 (Polling 방식).

**동작 방식:**
1. 10초마다 DB에서 `status=pending` 레코드 폴링
2. Single mode 또는 Walk-forward mode로 백테스트 실행
3. 결과 DB 저장 (`backtest_runs`, `backtest_trades`, `backtest_metrics`, `backtest_windows`)

**API:**
```bash
POST /api/v1/backtests/runs  # 백테스트 요청 (status=pending)
GET  /api/v1/backtests/runs/{id}  # 상태 조회
GET  /api/v1/backtests/runs/{id}/metrics  # 결과 Metrics
```

---

## Database Schema

### Core Tables

| Table | Description |
|-------|-------------|
| `coins` | 거래 대상 코인 (market symbol) |
| `candles_1m` | 1분봉 캔들 데이터 |
| `indicator_snapshots` | 기술적 지표 스냅샷 |
| `sentiment_snapshots` | 감성 분석 결과 |
| `signals` | 생성된 신호 (매수/매도/홀드) |
| `orders` | 주문 내역 |
| `fills` | 체결 내역 |
| `positions` | 현재 포지션 |

### Backtest Tables

| Table | Description |
|-------|-------------|
| `backtest_runs` | 백테스트 실행 레코드 |
| `backtest_trades` | 백테스트 중 거래 내역 |
| `backtest_metrics` | 백테스트 성과 지표 |
| `backtest_windows` | Walk-forward 윈도우별 결과 |

### Risk Tables

| Table | Description |
|-------|-------------|
| `runtime_state` | 일일 P&L, 연속 손실 등 상태 |

---

## Redis Data Structures

| Key | Type | Description | TTL |
|-----|------|-------------|-----|
| `upbit:signal` | Pub/Sub | 신호 브로드캐스트 | - |
| `upbit:trade_event` | Pub/Sub | 체결/손절/익절 이벤트 | - |
| `upbit:risk:request` | Pub/Sub | 위험 평가 RPC 요청 | - |
| `upbit:risk:response` | Pub/Sub | 위험 평가 RPC 응답 | - |
| `risk:daily_pnl:*` | String | 일일 손익 (날짜별) | 48h |
| `risk:loss_streak` | String | 연속 손실 횟수 | - |
| `risk:metrics` | JSON | 현재 위험 지표 | 30s |
| `risk:status` | String | healthy/warning/critical | 30s |
| `auto_trade:enabled` | String | 자동매매 ON/OFF | - |

---

## Risk Management

### Pre-Trade Risk Guard

주문 실행 전 위험 검증:

1. **일일 손실 제한** - 기본 3% (설정 가능)
2. **연속 손실 제한** - 5회 연속 손실 시 거래 중단
3. **최대 포지션 수** - 기본 5개
4. **단일 거래 금액 제한** - 기본 1%
5. **마켓 워닝 필터** - CAUTION/WARNING 상태 코인 거부

### Position Sizing

```python
risk_budget = equity * 0.01  # 1% 위험 예산
risk_per_trade = entry_price - stop_loss
qty = min(risk_budget / risk_per_trade, max_position_qty)
```

### Stop Loss / Take Profit

- **기본 손절:** 3% (설정 가능)
- **기본 익절:** 6% (설정 가능)

---

## Configuration

### Environment Variables (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `UPBIT_ACCESS_KEY` | 업비트 API Access Key | - |
| `UPBIT_SECRET_KEY` | 업비트 API Secret Key | - |
| `GROQ_API_KEY` | Groq API Key (감성 분석) | - |
| `DATABASE_URL` | PostgreSQL 연결 URL | - |
| `REDIS_URL` | Redis 연결 URL | redis://localhost:6379/0 |

### Risk Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `risk_max_daily_loss_pct` | 0.03 | 일일 최대 손실 (3%) |
| `risk_max_position_pct` | 0.10 | 최대 포지션 비율 (10%) |
| `risk_max_single_trade_pct` | 0.01 | 단일 거래 최대 비율 (1%) |
| `risk_default_stop_loss_pct` | 0.03 | 기본 손절 비율 (3%) |
| `risk_default_take_profit_pct` | 0.06 | 기본 익절 비율 (6%) |
| `min_buy_final_score` | 0.40 | 매수 최소 점수 threshold |

---

## Dependencies

### External APIs

| API | Purpose | Rate Limit |
|-----|---------|------------|
| Upbit REST | 주문, 잔고, 캔들 | 10 req/sec |
| Upbit WebSocket | 실시간 호가 | - |
| Groq API | 감성 분석 | 14,400 req/day |
| Fear & Greed Index | 시장 심리 | 1 req/day |

### Docker Services

| Service | Image | Purpose |
|---------|-------|---------|
| postgres | postgres:16-alpine | 메인 데이터베이스 |
| redis | redis:7-alpine | 메시지 버스, 캐시 |

---

## Deployment

```bash
# 전체 서비스 실행
docker compose up -d

# 특정 서비스만
docker compose up -d risk backtest

# 상태 확인
docker compose ps

# 로그 확인
docker compose logs -f strategy
```

---

## Future Improvements

1. **실시간 portfolio rebalancing**
2. **다변량 분석 기반 신호 개선**
3. **실시간 新闻/社交媒体 분석 통합**
4. **고급 포트폴리오 최적화 (MPT)**
