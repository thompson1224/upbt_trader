# Upbit AI Trader — 작업 진행 현황

> 최종 업데이트: 2026-03-21

---

## 완료된 작업

### 1. 프로젝트 구조 설계 및 생성

```
upbit-ai-trader/
├── backend/
│   ├── apps/
│   │   ├── gateway/            # FastAPI REST + WebSocket 게이트웨이 (port 8000)
│   │   ├── market_data_service/ # Upbit WebSocket 수집 서비스
│   │   ├── strategy_service/   # AI 신호 생성 서비스
│   │   ├── execution_service/  # 주문 실행 서비스
│   │   ├── risk_service/       # 사전 위험관리
│   │   └── backtest_service/   # 백테스팅 엔진
│   ├── libs/
│   │   ├── ai/                 # Claude API 클라이언트
│   │   ├── config/             # 설정 관리 (pydantic-settings)
│   │   ├── db/                 # SQLAlchemy 모델 + 세션
│   │   └── upbit/              # REST + WebSocket 클라이언트
│   ├── migrations/             # Alembic 마이그레이션
│   ├── schemas/                # Pydantic 응답 스키마
│   └── scripts/                # 실행 스크립트
└── frontend/
    └── src/
        ├── app/                # Next.js 15 App Router 페이지
        ├── components/         # UI 컴포넌트
        ├── hooks/              # WebSocket 훅
        ├── services/           # API 클라이언트
        ├── store/              # Zustand 상태관리
        └── types/              # TypeScript 타입
```

---

### 2. 백엔드 구현 완료 목록

#### DB 모델 (SQLAlchemy 2.0 Async)
| 파일 | 테이블 | 설명 |
|------|--------|------|
| `libs/db/models/coin.py` | `coins` | 업비트 KRW 마켓 목록 |
| `libs/db/models/candle.py` | `candles_1m` | 1분봉 OHLCV 데이터 |
| `libs/db/models/indicator.py` | `indicator_snapshots` | RSI/MACD/BB/EMA 스냅샷 |
| `libs/db/models/sentiment.py` | `sentiment_snapshots` | Claude API 감성 분석 결과 |
| `libs/db/models/signal.py` | `signals` | AI 매매 신호 |
| `libs/db/models/order.py` | `orders`, `fills` | 주문 및 체결 내역 |
| `libs/db/models/position.py` | `positions` | 현재 포지션 |
| `libs/db/models/backtest.py` | `backtest_runs`, `backtest_trades`, `backtest_metrics` | 백테스트 결과 |

#### 마이그레이션
- `migrations/versions/001_initial_schema.py`: 전체 11개 테이블 DDL (인덱스 포함)

#### 서비스별 구현
| 서비스 | 파일 | 핵심 기능 |
|--------|------|-----------|
| Gateway | `apps/gateway/main.py` | FastAPI lifespan, DB 연결 확인, Router 등록 |
| Gateway API | `apps/gateway/api/v1/` | markets, signals, orders, portfolio, backtests, settings |
| Gateway WS | `apps/gateway/ws/` | market_ws, signal_ws, order_ws |
| Market Data | `apps/market_data_service/main.py` | Upbit WS 수집, candles_1m 저장, 243개 KRW 마켓 동기화 |
| Strategy | `apps/strategy_service/main.py` | 60초 루프, TA 계산, Claude 감성분석, 신호 융합·저장 |
| Execution | `apps/execution_service/main.py` | 신호 폴링(5s), 위험검증, pyupbit 주문, 체결동기화(10s) |
| Risk | `apps/risk_service/guards/pre_trade_guard.py` | 일일손실한도, 포지션한도, 킬스위치 |
| Backtest | `apps/backtest_service/engine/backtest_engine.py` | 이벤트기반 백테스트, Walk-forward |

#### 핵심 라이브러리
| 파일 | 설명 |
|------|------|
| `libs/upbit/rest_client.py` | pyupbit 래퍼 (시세, 주문, 잔고) |
| `libs/upbit/websocket_client.py` | Upbit WS 클라이언트 (자동 재연결, ping/pong) |
| `libs/ai/claude_client.py` | Claude API 감성 분석 (10분 캐시, TA fallback) |
| `libs/config/settings.py` | pydantic-settings 기반 환경변수 관리 |
| `libs/db/session.py` | AsyncSession factory, get_db 의존성 |

#### 지표 계산 (`apps/strategy_service/indicators/calculator.py`)
- RSI (기간 14, Wilder EMA)
- MACD (12/26/9)
- Bollinger Bands (20/2σ, %B 포함)
- EMA 20/50

#### 신호 융합 (`apps/strategy_service/fusion/signal_fusion.py`)
```
final_score = 0.6 × TA_score + 0.4 × sentiment_score
신뢰도 = |final_score| × 100
side: buy(>0.2) / sell(<-0.2) / hold
```

---

### 3. 프론트엔드 구현 완료 목록

#### 페이지
| 경로 | 파일 | 내용 |
|------|------|------|
| `/` | `app/(dashboard)/page.tsx` | 메인 대시보드 |
| `/market` | `app/market/page.tsx` | 마켓 리스트 |
| `/backtest` | `app/backtest/page.tsx` | 백테스트 실행 |
| `/settings` | `app/settings/page.tsx` | 설정 페이지 |

#### 컴포넌트
| 파일 | 설명 |
|------|------|
| `components/dashboard/AISignalPanel.tsx` | AI 신호 패널 |
| `components/dashboard/MarketWatchlist.tsx` | 마켓 워치리스트 |
| `components/dashboard/PositionPanel.tsx` | 포지션 현황 |
| `components/charts/TradingViewChart.tsx` | 캔들차트 (Lightweight Charts) |
| `components/layout/GlobalHeader.tsx` | 글로벌 헤더 |
| `components/layout/Sidebar.tsx` | 사이드바 네비게이션 |
| `hooks/useUpbitWS.ts` | WebSocket 훅 |
| `store/useMarketStore.ts` | Zustand 마켓 상태 |
| `store/useTradeStore.ts` | Zustand 거래 상태 |

---

### 4. 인프라 설정 (로컬, no Docker)

| 항목 | 내용 |
|------|------|
| PostgreSQL | Homebrew, DB: `upbit_trader`, User: `trader` |
| Redis | Homebrew (`brew services start redis`) |
| Python | 3.9 (시스템), venv: `backend/.venv` |
| Node.js | 25.x |

---

### 5. 버그 수정 이력

| 이슈 | 원인 | 해결 |
|------|------|------|
| `TypeError: X \| None` (SQLAlchemy 모델) | Python 3.9 미지원 union syntax | `Optional[X]` 로 전환, `from __future__ import annotations` 제거 |
| `TypeError: X \| None` (FastAPI 라우터) | 동일 | `Optional[str]` 전환 |
| `TypeError: X \| None` (Pydantic 스키마) | 동일 | `Optional[X]` 전환 |
| `NoSuchModuleError` (Alembic) | alembic.ini placeholder URL | `migrations/env.py` 에 `.env` 파서 추가 |
| `InsufficientPrivilege` (PostgreSQL) | schema public 권한 없음 | `GRANT ALL ON SCHEMA public TO trader` |
| `uvicorn: command not found` | 시스템 Python 사용 | `run_local.sh` 에서 `.venv/bin/` 명시 |
| `numpy==2.1.2 not found` | Python 3.9 미지원 버전 | `numpy==2.0.2` 로 변경 |
| `psycopg-binary not found` | 잘못된 패키지명 | `psycopg[binary]==3.2.4` 로 변경 |
| `greenlet` 없음 | SQLAlchemy async 의존성 누락 | `pip install greenlet` |
| `cannot adapt type 'dict'` (market_warning) | Upbit API 반환값 dict를 그대로 삽입 | `"CAUTION" if ... else None` 으로 수정 |

---

## 미완료 / 다음 작업

| 우선순위 | 항목 | 메모 |
|----------|------|------|
| 높음 | Upbit API 키 입력 | `.env` 에 `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY` 설정 필요 |
| 높음 | Claude API 키 입력 | `.env` 에 `CLAUDE_API_KEY` 설정 필요 |
| 중간 | 프론트엔드 API 연동 검증 | 실제 신호/주문 데이터 UI 표시 확인 |
| 중간 | 백테스트 UI 동작 확인 | `/backtest` 페이지 E2E 테스트 |
| 중간 | WebSocket 실시간 데이터 검증 | 대시보드 실시간 업데이트 확인 |
| 낮음 | 테스트 코드 작성 | pytest 단위 테스트 |
| 낮음 | CI/CD 설정 | GitHub Actions |
