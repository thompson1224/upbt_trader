# Upbit AI Trader — 사용자 매뉴얼

> 업비트 기반 AI 자동매매 웹앱 · Docker 실행 가이드
> 버전: v0.2.0 (2026-03-24)

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [최초 설치 및 실행](#2-최초-설치-및-실행)
3. [API 키 설정](#3-api-키-설정)
4. [서버 관리](#4-서버-관리)
5. [화면 구성 및 사용법](#5-화면-구성-및-사용법)
6. [자동매매 동작 방식](#6-자동매매-동작-방식)
7. [위험관리 설정](#7-위험관리-설정)
8. [백테스트 실행](#8-백테스트-실행)
9. [트러블슈팅](#9-트러블슈팅)
10. [API 레퍼런스](#10-api-레퍼런스)

---

## 1. 사전 요구사항

### 필수

- **Docker Desktop** (macOS: [docker.com](https://www.docker.com/products/docker-desktop/))

### 확인

```bash
docker --version        # Docker version 24+ 권장
docker compose version  # v2.x 이상
```

> Docker Desktop 앱을 실행한 상태에서 아래 명령을 진행하세요.

---

## 2. 최초 설치 및 실행

### 2-1. 저장소 클론

```bash
git clone https://github.com/thompson1224/upbt_trader.git
cd upbt_trader
```

### 2-2. 환경변수 파일 설정

`backend/.env` 파일에 API 키를 입력합니다:

```dotenv
# Upbit API
UPBIT_ACCESS_KEY=여기에_액세스키_입력
UPBIT_SECRET_KEY=여기에_시크릿키_입력

# Groq API (무료 AI 감성분석 - console.groq.com 에서 발급)
GROQ_API_KEY=gsk_...
```

> 나머지 값들(DB, Redis, JWT 등)은 기본값으로 동작합니다.

### 2-3. 전체 서비스 빌드 및 실행

```bash
docker compose up -d --build
```

최초 실행 시 Docker 이미지 빌드로 **5~10분** 소요됩니다.

### 2-4. 실행 확인

```bash
docker compose ps
```

모든 서비스가 `Up` 상태인지 확인:

```
NAME                            STATUS
upbit-ai-trader-postgres-1      Up (healthy)
upbit-ai-trader-redis-1         Up (healthy)
upbit-ai-trader-gateway-1       Up
upbit-ai-trader-market_data-1   Up
upbit-ai-trader-strategy-1      Up
upbit-ai-trader-execution-1     Up
upbit-ai-trader-risk-1          Up
upbit-ai-trader-backtest-1      Up
upbit-ai-trader-frontend-1      Up
```

### 2-5. 접속

| URL | 설명 |
|-----|------|
| **http://localhost:3000** | 웹 앱 (대시보드) |
| http://localhost:8000/docs | API 문서 (Swagger UI) |
| http://localhost:8000/health | 게이트웨이 상태 확인 |

---

## 3. API 키 설정

### 방법 A — `.env` 파일 직접 편집 (권장)

`backend/.env` 파일 수정 후 서비스 재시작:

```dotenv
UPBIT_ACCESS_KEY=여기에_액세스키
UPBIT_SECRET_KEY=여기에_시크릿키
GROQ_API_KEY=gsk_...
```

```bash
docker compose restart strategy execution gateway
```

### 방법 B — 웹 UI

1. http://localhost:3000/settings 접속
2. 업비트 API 키 / Groq API 키 입력 후 저장

> ⚠️ 웹 UI로 저장한 키는 컨테이너 재시작 시 초기화됩니다. `.env` 방법(A)을 권장합니다.

---

### 업비트 API 키 발급

1. [업비트](https://upbit.com) 로그인
2. 마이페이지 → Open API 관리
3. **주문하기** 권한 체크
4. 현재 서버 IP 주소를 허용 IP에 추가
5. Access Key / Secret Key 복사

> **주의**: IP 허용 없이는 주문 시 `401 Unauthorized` 오류 발생.

### Groq API 키 발급 (무료)

1. [console.groq.com](https://console.groq.com) 접속
2. Google 계정으로 로그인
3. "API Keys" → "Create API Key"
4. `gsk_...` 형태 키 복사 (신용카드 불필요, 완전 무료)

---

## 4. 서버 관리

### 시작 / 중지 / 재시작

```bash
docker compose up -d          # 시작
docker compose stop           # 중지 (데이터 유지)
docker compose restart        # 전체 재시작
```

### 특정 서비스만 재시작

```bash
docker compose restart strategy     # AI 신호 서비스 (Groq 설정 변경 후)
docker compose restart execution    # 주문 실행 서비스
docker compose restart gateway      # API 게이트웨이
```

### 완전 삭제 (데이터 포함)

```bash
docker compose down -v        # 컨테이너 + DB 볼륨 삭제
```

### 로그 확인

```bash
docker compose logs -f strategy             # AI 신호 생성 실시간 로그
docker compose logs -f execution            # 주문 실행 실시간 로그
docker compose logs strategy --tail=30 | grep "Signal generated"   # 신호만 확인
docker compose logs execution --tail=30 | grep -E "Order|rejected" # 주문만 확인
```

---

## 5. 화면 구성 및 사용법

### 5-1. 메인 대시보드 (`/`)

**접속:** http://localhost:3000

```
┌─────────────────────────────────────────────────────────┐
│  헤더: BTC/ETH 시세 | 총 자산 | 일 손익 | 자동매매 ON/OFF  │
├──────────┬───────────────────────────┬───────────────────┤
│          │   캔들 차트                │  AI 신호 패널      │
│ 사이드바  │   (1분봉, LightweightCharts)│  [신뢰도 슬라이더] │
│          │                           │  신호 목록         │
│ - 대시보드│───────────────────────────│                   │
│ - 마켓   │  마켓 워치리스트            │  포지션 현황       │
│ - 주문내역│  (실시간 시세)             │  (실시간 P&L)     │
│ - 백테스팅│                           │                   │
│ - 설정   │                           │                   │
└──────────┴───────────────────────────┴───────────────────┘
```

| 패널 | 설명 |
|------|------|
| **캔들 차트** | 선택된 마켓의 1분봉 차트 (실시간) |
| **마켓 워치리스트** | 주요 마켓 실시간 시세 및 등락률 |
| **AI 신호 패널** | 최신 매수/매도 신호, TA/감성 점수, 신뢰도 필터 |
| **포지션 현황** | 현재 보유 종목, 평균단가, **실시간 평가손익(%)** |

### 5-2. 자동매매 ON/OFF 토글

헤더 우측의 **[자동매매 OFF/ON]** 버튼:
- **OFF → ON**: 확인 다이얼로그 표시 후 활성화 → Redis에 상태 저장
- **ON → OFF**: 즉시 비활성화 (진행 중인 SL/TP 청산은 계속 실행됨)
- 서버 재시작 후에도 마지막 상태 유지

> ⚠️ **주의**: ON으로 설정하면 AI 신호에 따라 실제 자산이 거래됩니다.

### 5-3. AI 신호 패널 읽는 법

| 필드 | 의미 |
|------|------|
| `BUY` (초록) | 매수 신호 |
| `SELL` (빨강) | 매도 신호 |
| `HOLD` (회색) | 관망 |
| **AI 점수** | final_score (-1.0 ~ +1.0) |
| **TA** | 기술적 지표 점수 (60% 비중) |
| **감성** | Groq AI 감성 점수 (40% 비중) |
| **신뢰도** | 신호 확신도 (%) |

**신뢰도 필터 슬라이더**: 패널 상단의 슬라이더로 신뢰도 임계값 조정 (기본 50%)

> AI 신호는 서비스 최초 기동 후 **약 50분** 뒤부터 표시됩니다.
> `ta_only=False` 로그 → Groq API 정상 동작 중

### 5-4. 포지션 현황 패널

- 보유 종목별 수량, 평균단가, 현재가 표시
- **실시간 평가손익**: WebSocket 시세에서 자동 계산 (API 호출 없음)
- SL(손절가) / TP(익절가) 표시
- 상단 총 미실현 손익 요약

### 5-5. 주문 내역 (`/orders`)

```
[전체/done/wait/cancel] [전체/매수/매도] 필터
┌──────────────────────────────────────────────────┐
│ 시간     마켓      방향  상태  유형  가격     수량 │
│ 03/24   KRW-BTC   매수  done  limit  92,000,000  0.0001 │
└──────────────────────────────────────────────────┘
```

### 5-6. 설정 페이지 (`/settings`)

| 항목 | 설명 |
|------|------|
| 업비트 API 키 | Access Key / Secret Key 입력 |
| Groq API 키 | `gsk_...` 형태 키 입력 (console.groq.com) |

### 5-7. 토스트 알림

거래 이벤트 발생 시 화면 우하단에 5초 알림 표시:

| 알림 색상 | 이벤트 |
|-----------|--------|
| 초록 | 주문 체결, 익절(TP) 실행 |
| 파랑 | 주문 접수 |
| 노랑 | 손절(SL) 실행 |
| 빨강 | 리스크 거절 |

---

## 6. 자동매매 동작 방식

> **경고**: 실제 자산이 거래됩니다. 반드시 소액으로 테스트 후 사용하세요.

### 전체 흐름

```
[Market Data Service]
  └─ Upbit WebSocket에서 실시간 시세 수신 → DB(candles_1m) 저장

[Strategy Service] — 60초마다
  ├─ 24h 거래량 상위 20개 코인만 처리
  ├─ 최근 200개 1분봉 조회
  ├─ RSI / MACD / Bollinger Bands / EMA 계산 → TA Score
  ├─ Groq AI 감성 분석 (30분 캐시, llama-3.1-8b-instant)
  │   └─ 실패 시 TA-only 모드 폴백
  ├─ 신호 융합: final_score = 0.6×TA + 0.4×감성
  │   ├─ final_score > +0.25  → BUY 신호
  │   ├─ final_score < −0.25  → SELL 신호
  │   └─ 그 외                → HOLD (저장 생략)
  └─ DB 저장 + Redis "upbit:signal" 브로드캐스트

[Execution Service] — 5초마다 폴링
  ├─ 자동매매 ON 여부 확인 (Redis "auto_trade:enabled")
  │   └─ OFF 시 신호 처리 중단 (SL/TP 청산은 계속 동작)
  ├─ 새 BUY/SELL 신호 감지 → 현재가 조회
  ├─ [Risk Guard 검증]
  │   ├─ 시장 경보 코인 → 거부
  │   ├─ 일일 손실 한도 초과(기본 3%) → 거부
  │   ├─ 연속 손실 5회 이상 → 거부
  │   ├─ 동시 보유 5종목 초과 → 거부
  │   └─ 단건 거래 한도 초과 → 수량 자동 축소 후 승인
  ├─ 통과 → Upbit 시장가 주문 실행
  └─ Redis "upbit:trade_event" 브로드캐스트 → 프론트 토스트 알림

[SL/TP Monitor] — 10초마다 (자동매매 OFF 상태에서도 동작)
  ├─ 모든 오픈 포지션 현재가 조회
  ├─ 미실현 손익 갱신 → Redis "upbit:position_update" 브로드캐스트
  ├─ 현재가 ≤ SL(손절가) → 시장가 매도 실행
  └─ 현재가 ≥ TP(익절가) → 시장가 매도 실행

[Order Sync] — 10초마다
  └─ 미체결 주문 상태 동기화 → 포지션 업데이트
```

### 자동매매 전제 조건

- [ ] `backend/.env`에 업비트 API 키 설정 (주문하기 권한)
- [ ] 업비트에 현재 서버 IP 허용 등록
- [ ] `backend/.env`에 Groq API 키 설정 (없으면 TA-only 모드로 동작)
- [ ] 대시보드에서 **자동매매 ON** 활성화
- [ ] AI 신호가 대시보드에 표시되고 있는지 확인 (기동 후 약 50분)

### SL/TP 기본값

| 항목 | 기본값 | 설명 |
|------|--------|------|
| 손절(SL) | 진입가 × 0.97 | 3% 하락 시 자동 청산 |
| 익절(TP) | 진입가 × 1.06 | 6% 상승 시 자동 청산 |

> SL/TP는 자동매매 OFF 상태에서도 항상 동작합니다 (손실 방지 목적).

---

## 7. 위험관리 설정

`backend/.env`에서 조정:

```dotenv
RISK_MAX_DAILY_LOSS_PCT=0.03    # 일일 최대 손실 3% (초과 시 당일 매수 거부)
RISK_MAX_POSITION_PCT=0.10      # 종목당 최대 비중 10%
RISK_MAX_SINGLE_TRADE_PCT=0.01  # 단건 최대 거래 1%
```

### Risk Guard 동작 규칙

| 조건 | 동작 |
|------|------|
| 시장 경보(CAUTION/WARNING) 코인 | 거래 거부 |
| 일일 손익이 −3% 이하 | 당일 전체 매수 거부 |
| 연속 손실 5회 | 거래 거부 |
| 동시 보유 5종목 초과 | 신규 매수 거부 |
| 단건 거래금액 > 총자산 1% | 수량 자동 축소 후 실행 |
| 포지션 비중 > 10% | 수량 자동 축소 후 실행 |

변경 후 적용:

```bash
docker compose restart execution
```

---

## 8. 백테스트 실행

`/backtest` 페이지에서 과거 데이터로 전략을 검증합니다.

| 입력 항목 | 설명 | 예시 |
|-----------|------|------|
| 마켓 | 백테스트 종목 | KRW-BTC |
| 시작일 | 백테스트 기간 시작 | 2026-01-01 |
| 종료일 | 백테스트 기간 종료 | 2026-03-01 |
| 초기 자본 | 시뮬레이션 시작 금액 (KRW) | 1,000,000 |

> ⚠️ 백테스트 서비스는 현재 stub 상태입니다. 수집된 캔들 데이터 기반으로 향후 구현 예정.

---

## 9. 트러블슈팅

### Docker Desktop이 실행 중이지 않을 때

```
Cannot connect to the Docker daemon
```
→ Docker Desktop 앱을 먼저 실행하세요.

---

### AI 신호가 표시되지 않을 때

1. 서비스 최초 기동 후 **최소 50분** 경과 필요
2. 현재 캔들 수 확인:

```bash
docker compose exec postgres psql -U trader -d upbit_trader \
  -c "SELECT MIN(cnt), MAX(cnt), AVG(cnt)::int
      FROM (SELECT coin_id, COUNT(*) as cnt FROM candles_1m GROUP BY coin_id) t;"
```

MAX가 50 이상이면 곧 신호 생성 시작.

3. strategy 로그 확인:

```bash
docker compose logs strategy --tail=30 | grep -E "Signal|ERROR|Groq"
```

`ta_only=True` 이면 Groq 키 미설정 — `.env`에 `GROQ_API_KEY` 확인.

---

### 주문이 실행되지 않을 때

1. 대시보드 헤더에서 **자동매매 ON** 상태 확인
2. 업비트 API 키 및 IP 허용 확인
3. execution 로그 확인:

```bash
docker compose logs execution --tail=30 | grep -E "Order|rejected|ERROR"
```

4. 신호 상태 확인:

```bash
docker compose exec postgres psql -U trader -d upbit_trader \
  -c "SELECT side, status, rejection_reason FROM signals ORDER BY ts DESC LIMIT 10;"
```

| status | 의미 |
|--------|------|
| `new` | 처리 대기 중 (자동매매 OFF 상태이면 계속 new) |
| `executed` | 주문 전송 완료 |
| `rejected` | Risk Guard 또는 오류로 거부 |

---

### Risk Guard가 모든 주문을 거부할 때

```bash
docker compose logs execution | grep "Signal rejected"
```

| rejection_reason | 원인 및 해결 |
|-----------------|-------------|
| `Daily loss limit reached` | 당일 손실 3% 초과 — 내일 자동 해제 또는 `RISK_MAX_DAILY_LOSS_PCT` 조정 |
| `Max open positions reached` | 5종목 동시 보유 — 일부 매도 후 재시도 |
| `Market warning active` | 업비트 경보 종목 — 다른 마켓에서 시도 |
| `Insufficient qty` | 잔고 부족 |
| `Ticker fetch error` | Upbit API 일시 오류 — 잠시 후 자동 재시도 |

---

### Groq API 오류

```bash
docker compose logs strategy | grep "Groq"
```

- `401`: API 키 오류 → `.env`의 `GROQ_API_KEY` 확인
- `429`: 일일 한도 소진 (14,400건) → 다음날 자동 초기화
- 오류 시 TA-only 모드로 자동 폴백 → 정상 신호 생성 유지

---

### 업비트 API 오류

| 에러 코드 | 원인 | 해결 |
|-----------|------|------|
| `401 Unauthorized` | API 키 오류 또는 IP 미허용 | 키 확인, 업비트 IP 화이트리스트 등록 |
| `429 Too Many Requests` | 요청 빈도 초과 | 자동 대기 후 재시도 |
| WS 연결 끊김 | 네트워크 불안정 | 자동 재연결 (별도 조치 불필요) |

---

### 설정 저장 500 에러

게이트웨이 로그에서 `ENCRYPTION_KEY` 오류 확인:

```bash
docker compose logs gateway --tail=10
```

유효한 키 재생성:

```bash
docker compose exec gateway python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

출력된 키를 `backend/.env`의 `ENCRYPTION_KEY=`에 입력 후 재시작.

---

### 포트 충돌

```bash
lsof -i :3000    # 프론트엔드
lsof -i :8000    # 게이트웨이
```

---

### 전체 초기화 (데이터 삭제 포함)

```bash
docker compose down -v --rmi local
docker compose up -d --build
```

---

## 10. API 레퍼런스

전체 엔드포인트: http://localhost:8000/docs (Swagger UI)

### REST API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 |
| GET | `/api/v1/markets` | KRW 전체 마켓 목록 |
| GET | `/api/v1/markets/{market}/candles` | 캔들 데이터 (`?interval=1m&limit=200`) |
| GET | `/api/v1/signals` | AI 신호 목록 (`?market=KRW-BTC&limit=20`) |
| GET | `/api/v1/orders` | 주문 내역 (`?state=done`) |
| GET | `/api/v1/positions` | 포지션 현황 |
| GET | `/api/v1/portfolio/equity-curve` | 수익 곡선 |
| POST | `/api/v1/backtests/runs` | 백테스트 실행 |
| POST | `/api/v1/secrets/upbit-keys` | 업비트 키 임시 저장 |
| POST | `/api/v1/secrets/groq-key` | Groq 키 임시 저장 |
| GET | `/api/v1/settings/auto-trade` | 자동매매 상태 조회 |
| PATCH | `/api/v1/settings/auto-trade` | 자동매매 ON/OFF 설정 |

### WebSocket

| 경로 | 설명 | 파라미터 |
|------|------|----------|
| `ws://localhost:8000/ws/market` | 실시간 시세 | `?codes=KRW-BTC,KRW-ETH` |
| `ws://localhost:8000/ws/signals` | 실시간 AI 신호 | — |
| `ws://localhost:8000/ws/orders` | 실시간 주문 업데이트 | — |
| `ws://localhost:8000/ws/trade-events` | 거래 이벤트 (주문/체결/SL/TP/거절) | — |
| `ws://localhost:8000/ws/portfolio` | 포지션 실시간 업데이트 | — |
