# Upbit AI Trader — 사용자 매뉴얼

> 업비트 기반 AI 자동매매 웹앱 · Docker 실행 가이드

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [최초 설치 및 실행](#2-최초-설치-및-실행)
3. [API 키 설정](#3-api-키-설정)
4. [서버 관리](#4-서버-관리)
5. [화면 구성 및 사용법](#5-화면-구성-및-사용법)
6. [자동매매 활성화](#6-자동매매-활성화)
7. [백테스트 실행](#7-백테스트-실행)
8. [트러블슈팅](#8-트러블슈팅)
9. [API 레퍼런스](#9-api-레퍼런스)

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
git clone <repo-url>
cd upbit-ai-trader
```

### 2-2. 환경변수 파일 확인

`backend/.env` 파일이 있는지 확인합니다. 없으면 생성:

```bash
cp backend/.env.example backend/.env
```

### 2-3. 전체 서비스 빌드 및 실행

```bash
docker-compose up -d --build
```

최초 실행 시 Docker 이미지 빌드(Python 패키지 설치 포함)로 **5~10분** 소요됩니다.

### 2-4. 실행 확인

```bash
docker-compose ps
```

모든 서비스가 `Up` 상태인지 확인:

```
NAME                          STATUS
upbit-ai-trader-postgres-1    Up (healthy)
upbit-ai-trader-redis-1       Up (healthy)
upbit-ai-trader-gateway-1     Up
upbit-ai-trader-market_data-1 Up
upbit-ai-trader-strategy-1    Up
upbit-ai-trader-execution-1   Up
upbit-ai-trader-risk-1        Up
upbit-ai-trader-backtest-1    Up
upbit-ai-trader-frontend-1    Up
```

### 2-5. 접속

| URL | 설명 |
|-----|------|
| http://localhost:3000 | 웹 앱 |
| http://localhost:8000/docs | API 문서 (Swagger) |
| http://localhost:8000/health | 게이트웨이 상태 확인 |

---

## 3. API 키 설정

API 키는 두 가지 방법으로 설정할 수 있습니다.

### 방법 A — 웹 UI (권장)

1. http://localhost:3000/settings 접속
2. **업비트 API 키** 입력 (Access Key, Secret Key)
3. **Claude API 키** 입력 (`sk-ant-...`)
4. **저장** 버튼 클릭 → "저장됨" 표시 확인

### 방법 B — .env 파일 직접 편집

`backend/.env` 파일을 열어 아래 항목을 수정 후 서비스 재시작:

```dotenv
# 업비트 API 키 (https://upbit.com/mypage/open_api_management)
UPBIT_ACCESS_KEY=여기에_액세스키_입력
UPBIT_SECRET_KEY=여기에_시크릿키_입력

# Claude API 키 (https://console.anthropic.com)
CLAUDE_API_KEY=sk-ant-...
```

```bash
docker-compose restart gateway strategy execution
```

### 업비트 API 키 발급 방법

1. [업비트](https://upbit.com) 로그인
2. 마이페이지 → Open API 관리
3. **주문하기** 권한 체크
4. 현재 IP 주소를 허용 IP에 추가
5. Access Key / Secret Key 복사

> **주의**: IP 허용 설정 없이는 주문 API 호출 시 `401 Unauthorized` 오류가 발생합니다.

---

## 4. 서버 관리

### 시작

```bash
docker-compose up -d
```

### 중지

```bash
docker-compose stop
```

### 재시작

```bash
docker-compose restart
```

### 특정 서비스만 재시작

```bash
docker-compose restart gateway
docker-compose restart strategy
```

### 완전 삭제 (데이터 포함)

```bash
# 컨테이너 + 볼륨(DB 데이터) 모두 삭제
docker-compose down -v
```

### 로그 확인

```bash
# 전체 로그
docker-compose logs -f

# 특정 서비스 로그
docker-compose logs -f gateway
docker-compose logs -f strategy
docker-compose logs -f market_data
```

---

## 5. 화면 구성 및 사용법

### 메인 대시보드 (`/`)

```
┌─────────────────────────────────────────────────┐
│  헤더: 잔고 | 오늘 손익 | 연결 상태              │
├──────────┬──────────────────────┬────────────────┤
│          │   캔들 차트           │  AI 신호 패널  │
│ 사이드바  │   (TradingView)       │                │
│          │                      │                │
│ - 대시보드│──────────────────────│                │
│ - 마켓   │  마켓 워치리스트       │  포지션 현황   │
│ - 백테스트│                      │                │
│ - 설정   │                      │                │
└──────────┴──────────────────────┴────────────────┘
```

| 패널 | 설명 |
|------|------|
| **캔들 차트** | 선택된 마켓의 1분봉 차트 (Lightweight Charts) |
| **마켓 워치리스트** | 주요 8개 마켓 실시간 시세 및 등락률 |
| **AI 신호 패널** | 최신 매수/매도 신호, 신뢰도, TA/감성 점수 |
| **포지션 현황** | 현재 보유 종목, 평균단가, 평가손익 |

### AI 신호 패널 읽는 법

| 필드 | 의미 |
|------|------|
| `BUY` (초록) | 매수 신호 |
| `SELL` (빨강) | 매도 신호 |
| `HOLD` (회색) | 관망 |
| **AI 점수** | final_score (-100 ~ +100) |
| **TA** | 기술적 지표 점수 |
| **감성** | Claude AI 감성 점수 |
| **신뢰도** | 신호 확신도 (%) |

> AI 신호는 서비스 최초 기동 후 **약 50분** 뒤부터 표시됩니다 (1분봉 데이터 50개 이상 누적 필요).

### 마켓 페이지 (`/market`)

전체 KRW 마켓 목록과 실시간 시세를 그리드로 표시합니다. 마켓 클릭 시 대시보드 차트에 반영됩니다.

### 설정 페이지 (`/settings`)

업비트 / Claude API 키를 입력하고 저장합니다. 저장된 키는 암호화되어 적용됩니다.

### 백테스트 페이지 (`/backtest`)

과거 데이터로 전략 성능을 시뮬레이션합니다.

---

## 6. 자동매매 활성화

> **경고**: 실제 자산이 거래됩니다. 반드시 소액으로 테스트 후 사용하세요.

### 전제 조건

- [ ] 업비트 API 키 설정 완료 (주문하기 권한 포함)
- [ ] IP 허용 등록 완료
- [ ] AI 신호가 대시보드에 표시되고 있는지 확인

### 신호 → 주문 흐름

```
[Strategy Service] 60초마다
  ├─ final_score > +0.2  → BUY 신호
  └─ final_score < -0.2  → SELL 신호
         │
         ▼
[Risk Guard 검증]
  ├─ 일일 손실 한도 초과? → 거부
  ├─ 포지션 한도 초과?   → 거부
  └─ 통과 → Upbit API 주문 전송
         │
         ▼
[Execution Service]
  └─ 10초마다 체결 동기화
```

### 위험관리 파라미터 (`.env`)

```dotenv
RISK_MAX_DAILY_LOSS_PCT=0.03    # 일일 최대 손실 3% (초과 시 당일 거래 중단)
RISK_MAX_POSITION_PCT=0.10      # 종목당 최대 비중 10%
RISK_MAX_SINGLE_TRADE_PCT=0.01  # 단건 최대 거래 1%
```

변경 후 적용:

```bash
docker-compose restart execution risk
```

---

## 7. 백테스트 실행

`/backtest` 페이지에서 과거 데이터로 전략을 검증합니다.

| 입력 항목 | 설명 | 예시 |
|-----------|------|------|
| 마켓 | 백테스트 종목 | KRW-BTC |
| 시작일 | 백테스트 기간 시작 | 2026-01-01 |
| 종료일 | 백테스트 기간 종료 | 2026-03-01 |
| 초기 자본 | 시뮬레이션 시작 금액 (KRW) | 1,000,000 |

결과 지표:

| 지표 | 설명 |
|------|------|
| 총 수익률 | 기간 전체 수익률 |
| MDD | 최대 낙폭 (Max Drawdown) |
| 샤프 비율 | 위험 대비 수익률 |
| 승률 | 수익 거래 / 전체 거래 비율 |
| 총 거래 횟수 | 매수 + 매도 횟수 |

> 백테스트는 실시간 수집된 1분봉 데이터를 사용합니다. 충분한 데이터 누적 전에는 결과가 제한적일 수 있습니다.

---

## 8. 트러블슈팅

### Docker Desktop이 실행 중이지 않을 때

```
Cannot connect to the Docker daemon
```

→ Docker Desktop 앱을 먼저 실행하세요.

---

### 특정 서비스가 `Restarting` 상태일 때

```bash
# 에러 확인
docker-compose logs <서비스명> --tail=20

# 예시
docker-compose logs gateway --tail=20
docker-compose logs strategy --tail=20
```

---

### 설정 저장이 실패할 때

게이트웨이 로그에서 500 에러 확인:

```bash
docker-compose logs gateway --tail=10
```

`ENCRYPTION_KEY` 관련 오류라면:

```bash
# 유효한 Fernet 키 생성
docker-compose exec gateway python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

출력된 키를 `backend/.env`의 `ENCRYPTION_KEY=` 값으로 교체 후:

```bash
docker-compose restart gateway
```

---

### 데이터가 로딩중으로만 표시될 때

1. 게이트웨이와 market_data 서비스 상태 확인:

```bash
docker-compose ps
docker-compose logs market_data --tail=20
```

2. Redis에 데이터가 흐르는지 확인:

```bash
docker-compose exec redis redis-cli subscribe "upbit:ticker"
# 실시간 ticker 메시지가 출력되면 정상
# Ctrl+C로 종료
```

3. 이상 없으면 브라우저 새로고침 (F5)

---

### AI 신호가 표시되지 않을 때

신호 생성 전제 조건 확인:

1. 서비스 최초 기동 후 **최소 50분** 경과 필요 (1분봉 50개 이상 누적)
2. 현재 캔들 수 확인:

```bash
docker-compose exec postgres psql -U trader -d upbit_trader \
  -c "SELECT c.market, COUNT(*) as candles FROM candles_1m cc \
      JOIN coins c ON c.id = cc.coin_id GROUP BY c.market \
      ORDER BY candles DESC LIMIT 5;"
```

3. strategy 서비스 로그 확인:

```bash
docker-compose logs strategy --tail=30
```

`Signal generated` 로그가 보이면 정상 작동 중입니다.

---

### 업비트 API 오류

| 에러 코드 | 원인 | 해결 |
|-----------|------|------|
| `401 Unauthorized` | API 키 오류 또는 IP 미허용 | 키 확인, 업비트 IP 화이트리스트 등록 |
| `429 Too Many Requests` | 요청 빈도 초과 | strategy 루프 간격 조정 (`STRATEGY_INTERVAL_SEC`) |
| WS 연결 끊김 | 네트워크 불안정 | 자동 재연결 (최대 30초) — 별도 조치 불필요 |

---

### 포트 충돌

```bash
# 포트 점유 프로세스 확인
lsof -i :3000
lsof -i :8000

# 충돌 서비스 종료 후 재시작
docker-compose up -d
```

---

### 전체 초기화 (데이터 삭제 포함)

```bash
# 모든 컨테이너, 이미지, 볼륨 삭제
docker-compose down -v --rmi local

# 처음부터 다시 빌드
docker-compose up -d --build
```

---

## 9. API 레퍼런스

브라우저에서 http://localhost:8000/docs 접속 시 Swagger UI로 모든 엔드포인트 확인 및 테스트 가능합니다.

### REST API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 |
| GET | `/api/v1/markets` | KRW 전체 마켓 목록 |
| GET | `/api/v1/markets/{market}/candles` | 캔들 데이터 (`?interval=1m&limit=200`) |
| GET | `/api/v1/signals` | AI 신호 목록 (`?market=KRW-BTC&limit=20`) |
| GET | `/api/v1/orders` | 주문 내역 |
| GET | `/api/v1/positions` | 포지션 현황 |
| GET | `/api/v1/portfolio/equity-curve` | 수익 곡선 |
| POST | `/api/v1/backtests/runs` | 백테스트 실행 |
| GET | `/api/v1/backtests/runs/{id}` | 백테스트 상태 |
| GET | `/api/v1/backtests/runs/{id}/metrics` | 백테스트 결과 지표 |
| POST | `/api/v1/secrets/upbit-keys` | 업비트 키 저장 |
| POST | `/api/v1/secrets/claude-key` | Claude 키 저장 |

### WebSocket

| 경로 | 설명 | 파라미터 |
|------|------|----------|
| `ws://localhost:8000/ws/market` | 실시간 시세 | `?codes=KRW-BTC,KRW-ETH` |
| `ws://localhost:8000/ws/signals` | 실시간 AI 신호 | — |
| `ws://localhost:8000/ws/orders` | 실시간 주문 업데이트 | — |
