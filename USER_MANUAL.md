# Upbit AI Trader — 사용자 매뉴얼

> 업비트 기반 AI 자동매매 웹앱 · Docker 실행 가이드
> 버전: v0.2.2 (2026-03-25)

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
11. [아키텍처 개요](#11-아키텍처-개요)

---

## 1. 사전 요구사항

### 필수

- **Docker Desktop** (macOS: [docker.com](https://www.docker.com/products/docker-desktop/))
- **업비트 계정** + API 키 (주문하기 권한)
- **Groq API 키** (무료, [console.groq.com](https://console.groq.com))

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

`backend/.env` 파일을 열어 API 키 3개를 입력합니다:

```dotenv
# ── 반드시 입력해야 할 항목 ──────────────────────────────

# 업비트 API (upbit.com → 마이페이지 → Open API 관리)
UPBIT_ACCESS_KEY=여기에_업비트_액세스키_입력
UPBIT_SECRET_KEY=여기에_업비트_시크릿키_입력

# Groq AI API (console.groq.com → API Keys → Create API Key, 무료)
GROQ_API_KEY=gsk_여기에_Groq_키_입력

# ── 기본값으로 동작하는 항목 (변경 불필요) ──────────────

APP_ENV=local
DATABASE_URL=postgresql+psycopg://trader:trader_secret@postgres:5432/upbit_trader
REDIS_URL=redis://redis:6379/0
JWT_SECRET=9e94348ec885a81c3c6c41bbc501bd9a2ed5b56492acdb7291df2a19f96a73ff
ENCRYPTION_KEY=h-b1lBh5HVD8nKT0S5YkdHdyVSOiPHmU62_xT1T-RXQ=
GROQ_MODEL=llama-3.1-8b-instant
RISK_MAX_DAILY_LOSS_PCT=0.03
RISK_MAX_POSITION_PCT=0.10
RISK_MAX_SINGLE_TRADE_PCT=0.01
```

### 2-3. 전체 서비스 빌드 및 실행

```bash
docker compose up -d --build
```

**최초 실행 시 Docker 이미지 빌드로 5~10분 소요됩니다.**

> ⚠️ **주의**: 코드 변경 후에는 반드시 `--build` 옵션을 붙여야 변경사항이 반영됩니다.
> `docker compose up -d` (빌드 없이 시작)는 이미지를 재사용합니다.

### 2-4. 실행 확인

```bash
docker compose ps
```

기본 서비스가 `Up` 상태인지 확인:

```
NAME                            STATUS
upbit-ai-trader-postgres-1      Up (healthy)
upbit-ai-trader-redis-1         Up (healthy)
upbit-ai-trader-gateway-1       Up
upbit-ai-trader-market_data-1   Up
upbit-ai-trader-strategy-1      Up
upbit-ai-trader-execution-1     Up
upbit-ai-trader-frontend-1      Up
```

> `risk`, `backtest` 서비스는 현재 기본 기동 대상이 아닌 stub 프로필입니다.
> 필요할 때만 `docker compose --profile stub up -d`로 올리세요.

### 2-5. 웹앱 접속

| URL | 설명 |
|-----|------|
| **http://localhost:3000** | 🌐 웹 앱 메인 (여기서 시작) |
| http://localhost:8000/docs | API 문서 (Swagger UI) |
| http://localhost:8000/health | 게이트웨이 상태 확인 |

---

## 3. API 키 설정

### 업비트 API 키 발급

1. [업비트](https://upbit.com) 로그인
2. **마이페이지 → Open API 관리**
3. **권한 선택**: `주문하기` 체크 (필수), `자산조회` 체크
4. **허용 IP 주소**: 현재 서버 IP 추가
   - 로컬 실행의 경우 `127.0.0.1` 또는 공인 IP
   - 공인 IP 확인: `curl ifconfig.me`
5. Access Key / Secret Key 복사 → `backend/.env`에 입력

> ⚠️ **IP 허용 없이는 주문 시 `401 Unauthorized` 오류 발생**

### Groq API 키 발급 (무료, 신용카드 불필요)

1. [console.groq.com](https://console.groq.com) 접속
2. Google 계정으로 로그인
3. 좌측 메뉴 **API Keys** → **Create API Key**
4. `gsk_...` 형태 키 복사 → `backend/.env`에 입력

**무료 한도**: 14,400 요청/일, 6,000 tokens/분
- 본 앱은 상위 10개 마켓만 분석하므로 일반적으로 한도 내 동작

### 방법 A — `.env` 파일 (권장, 재시작 후에도 유지)

```bash
# backend/.env 편집 후
docker compose restart strategy execution gateway
```

### 방법 B — 웹 UI

1. http://localhost:3000/settings 접속
2. API 키 입력 후 **저장** 버튼

주의:

- 업비트 키는 Redis에 암호화 저장되어 기본 컨테이너 재시작 후에도 유지됩니다.
- `docker compose down -v` 또는 Redis 볼륨 삭제 시 초기화됩니다.
- Groq 키는 런타임 반영용이라 재시작 후 다시 넣거나 `.env`에 유지하는 편이 안전합니다.
- 운영 기준으로는 `.env` 또는 별도 시크릿 관리 방식을 권장합니다.

---

## 4. 서버 관리

### 시작 / 중지 / 재시작

```bash
docker compose up -d                    # 시작 (이미지 재빌드 없이)
docker compose up -d --build            # 코드 변경 후 재빌드 + 시작
docker compose stop                     # 중지 (데이터 유지)
docker compose down                     # 중지 + 컨테이너 삭제 (볼륨 유지)
docker compose down -v                  # 중지 + 컨테이너 + DB 볼륨 삭제
docker compose restart                  # 전체 재시작 (이미지 재빌드 없음)
```

### 특정 서비스만 재시작

```bash
docker compose restart gateway          # API 키 설정 변경 후
docker compose restart strategy         # Groq AI 설정 변경 후
docker compose restart execution        # Risk 설정 변경 후
docker compose restart market_data      # 시세 데이터가 업데이트되지 않을 때
```

### 운영 런북

반복 운영 절차는 별도 문서:

```bash
cat OPERATIONS_RUNBOOK.md
./scripts/ops_smoke_check.sh
```

### 로그 확인

```bash
# 실시간 로그
docker compose logs -f strategy             # AI 신호 생성
docker compose logs -f execution            # 주문 실행

# 필터링 로그
docker compose logs strategy --tail=50 | grep "Signal generated"
docker compose logs execution --tail=50 | grep -E "Order|rejected|ERROR"
docker compose logs gateway --tail=20       # Gateway 에러 확인
```

### 서비스 상태 상세 확인

```bash
# 각 서비스 리소스 사용량
docker stats --no-stream

# 특정 서비스 프로세스 확인
docker compose top execution
```

---

## 5. 화면 구성 및 사용법

### 5-1. 사이드바 네비게이션

| 메뉴 | URL | 설명 |
|------|-----|------|
| 대시보드 | `/` | 차트, 시세, 신호, 포지션 |
| 마켓 | `/market` | 전체 KRW 마켓 목록 |
| 주문 내역 | `/orders` | 주문 이력 및 필터 |
| 백테스트 | `/backtest` | 전략 검증 (개발 중) |
| 감사로그 | `/audit` | 설정 변경, 주문 실패, 리스크 거절 확인 |
| 설정 | `/settings` | API 키 및 운영 복구 설정 |

---

### 5-2. 메인 대시보드 (`/`)

**접속:** http://localhost:3000

```
┌─────────────────────────────────────────────────────────────┐
│  헤더: [자동매매 OFF/ON 토글] | 서비스명                       │
├──────────┬───────────────────────────────┬──────────────────┤
│          │   캔들 차트 (1분봉)             │  AI 신호 패널    │
│ 사이드바  │   LightweightCharts           │  [신뢰도 슬라이더]│
│          │   (마켓 클릭으로 전환)          │  신호 목록       │
│ ─ 대시보드│                               │  (최신순)        │
│ ─ 마켓   ├───────────────────────────────┤                  │
│ ─ 주문   │  마켓 워치리스트               │  포지션 현황     │
│ ─ 백테스트│  BTC / ETH / XRP / SOL ...    │  실시간 P&L (%)  │
│ ─ 설정   │  실시간 가격 / 등락률           │  SL / TP 표시    │
└──────────┴───────────────────────────────┴──────────────────┘
                                         [토스트 알림 — 우하단]
```

대시보드 하단 `실거래 성과` 패널에서 다음을 바로 확인할 수 있습니다.

- 순손익, 승률, Profit Factor, 최대 낙폭
- 오늘 운영 요약
  - 오늘 손익
  - 연속 손실
  - 종료 거래 승/패
  - 열린 포지션 수
  - 제외 코인 수
  - 리스크 거절 수
  - 주문 실패 수
  - 가장 약한 열린 포지션 1건
- 최근 운영 이력
  - 최근 5일 손익 비교
  - 열린 포지션 수 비교
  - 리스크 거절 수 비교
  - 주문 실패 수 비교
- 시장별 손익
- 청산 사유별 손익
- 기간 필터 `7D / 30D / ALL`
- Final Score 구간별 손익/승률
- 감성 점수 구간별 손익/승률
- 시간대별 손익/승률 (KST 기준)
- 최근 종료 거래
  - 전략 ID
  - TA / 감성 / final score
  - 진입가 / 청산가
  - 보유 시간

시장별 손익 또는 종료 거래의 시장명을 누르면 코인별 상세 성과 페이지로 이동합니다.

---

### 5-4. 코인별 상세 성과 페이지 (`/performance/market/{market}`)

예:

```text
http://localhost:3000/performance/market/KRW-BTC
```

이 페이지에서는 한 코인에 대해 다음을 한 번에 봅니다.

- 기간 필터: `7D`, `30D`, `ALL`
- 코인별 요약 성과
  - 순손익
  - 승률
  - Profit Factor
  - 최대 낙폭
- 청산 사유별 성과
- 종료 거래 상세
- 현재 열린 포지션 상태
  - 수량
  - 평균단가
  - 미실현손익
  - 실현손익
  - SL / TP
  - `strategy` / `external`
- 기간별 자산곡선
  - 성과 요약과 같은 `7D / 30D / ALL` 기준으로 표시
- 최근 신호
  - 마지막 `buy/sell/hold`
  - TA / 감성 / final score / confidence
  - 최근 5개 신호
  - 현재 포지션과 최근 신호의 방향 해석
- 신호 전환 품질
  - `hold→sell`
  - `hold→hold`
  - `hold` 시작 건수
  - 전체 전환 수
  - 코인 상세 화면은 이 값을 해당 코인 전용 API로 직접 조회합니다
- 제외 상태
  - `excluded` 배지
  - 제외 중이면 현재 제외 사유 메모 표시

즉 이 화면은 `과거 성과`, `현재 포지션`, `최근 신호`를 같이 보는 분석용 페이지입니다.
대시보드의 성과 패널은 여기에 더해 `점수 구간`과 `시간대` 기준으로 손익을 빠르게 훑는 요약 분석 화면입니다.

---

### 5-3. 자동매매 ON/OFF 토글

헤더 우측의 **[자동매매]** 버튼:

| 동작 | 결과 |
|------|------|
| OFF → ON | 확인 다이얼로그 표시 → 승인 시 활성화 |
| ON → OFF | 즉시 비활성화 |

- 상태는 Redis에 저장되어 **서버 재시작 후에도 유지**
- Redis에서 자동매매 상태를 읽지 못하면 기본적으로 `OFF`로 처리됩니다. 운영 안전 기준으로 fail-closed 동작입니다.
- OFF 상태에서도 **SL/TP 청산은 계속 동작** (손실 방지)
- ON 상태이면 AI 신호 발생 즉시 자동 주문 실행

> ⚠️ **실제 자산이 거래됩니다. 처음에는 소액으로 테스트하세요.**

---

### 5-4. AI 신호 패널

**신호 표시 시작 시간**: 최초 기동 후 캔들 50개 이상 수집 시 (~50분)

#### 신뢰도 필터 슬라이더

패널 상단의 슬라이더로 임계값 설정 (기본 50%):
- 슬라이더를 올리면 → 확신도 높은 신호만 표시
- 슬라이더를 낮추면 → 더 많은 신호 표시

#### 신호 항목 읽는 법

| 필드 | 의미 |
|------|------|
| `BUY` (초록) | 매수 신호 (final_score > +0.25) |
| `SELL` (빨강) | 매도 신호 (final_score < −0.25) |
| `HOLD` (회색) | 관망 (−0.25 ≤ score ≤ +0.25) |
| **AI 점수** | final_score (−1.0 ~ +1.0) |
| **TA** | 기술적 지표 점수 (RSI/MACD/BB/EMA, 60% 비중) |
| **감성** | Groq AI 감성 분석 점수 (40% 비중) |
| **신뢰도** | 신호 확신도 (confidence %) |
| `ta_only` | Groq 미사용, TA만으로 신호 생성됨 |

---

### 5-5. 마켓 워치리스트

- 좌측 패널에 주요 8개 마켓 실시간 시세
- 마켓 클릭 시 상단 캔들 차트 전환
- 가격 색상: 초록(상승) / 빨강(하락) / 회색(보합)

---

### 5-6. 포지션 현황 패널

- 현재 보유 종목, 수량, 평균단가 표시
- **실시간 평가손익**: WebSocket 시세 기반 자동 계산 (API 호출 없음)
- SL(손절가) / TP(익절가) 표시
- 상단: 전체 미실현 손익 합계
- 최근 신호(`buy / sell / hold`)와 신호 상태 표시
- 최근 매도 신호가 있으면 별도로 상태/거절 사유 표시
- `SL까지 -x%`, `TP까지 +x%` 형태로 현재가 기준 거리 표시
- `매도 대기 사유`를 서버 판단 기준으로 표시
  - 예: `최근 신호가 hold 라서 매도 조건이 아직 아닙니다`
  - 예: `최근 매도 신호가 거절됐습니다: Max consecutive losses reached: 5`
  - 예: `현재가가 익절가에 도달했습니다. 주문 체결 또는 동기화 상태를 확인하세요`
- 각 포지션 카드에서 바로 이동 가능
  - `매도 주문 보기` → `/orders?market=KRW-XXX&side=sell`
  - `감사로그 보기` → `/audit?source=execution&market=KRW-XXX`

---

### 5-7. 주문 내역 페이지 (`/orders`)

```
[상태 필터: 전체 / done / wait / cancel]  [방향: 전체 / 매수 / 매도]
┌────────────────────────────────────────────────────────────────┐
│ 시간           마켓       방향  상태  유형   가격         수량  │
│ 03/24 09:14   KRW-BTC   매수  done  limit  105,712,000  0.001 │
│ 03/24 08:30   KRW-ETH   매도  done  limit   3,200,000   0.05  │
└────────────────────────────────────────────────────────────────┘
```

- 10초마다 자동 갱신
- 상태: `done`(체결), `wait`(미체결), `cancel`(취소)
- 상단 `최근 실행/거절 사유` 카드에서 `risk_rejected`, `order_failed` 최근 이벤트 확인 가능
- URL 쿼리 필터 지원
  - 예: `/orders?market=KRW-SOL&side=sell`
  - 예: `/orders?market=KRW-BTC&state=done`

### 5-7-1. 감사 로그 페이지 (`/audit`)

- execution / settings 소스별 필터
- info / warning / error 레벨 필터
- payload 펼쳐보기
- URL 쿼리 필터 지원
  - 예: `/audit?source=execution&market=KRW-SOL`
  - 예: `/audit?source=execution&eventType=order_failed`
  - 예: `/audit?source=execution&market=KRW-SOL&eventType=risk_rejected`

---

### 5-8. 설정 페이지 (`/settings`)

| 항목 | 설명 |
|------|------|
| 업비트 Access Key | 업비트 API Access Key |
| 업비트 Secret Key | 업비트 API Secret Key |
| Groq API 키 | `gsk_...` 형태 (console.groq.com) |
| 최소 매수 Final Score | 이 값보다 낮은 `buy` 신호는 주문 전 거절 |
| 외부 보유분 자동 손절 | 외부 보유 코인에 기본 손절만 허용 |
| 장기 Hold 경고 기준 | 연속 hold 경고를 띄울 분 기준 |
| 전환 추천 기준 | 제외 추천 / 복귀 검토 배지 계산 기준 |
| 자동매매 제외 코인 | 신호 생성 자체를 건너뛸 코인 목록 |
| 연속 손실 초기화 | `loss_streak` 즉시 0으로 복구 |

**보기/숨기기 토글**: 키 값 마스킹 ON/OFF

**최소 매수 Final Score**:
- 일반 `buy` 신호에만 적용
- `0.00`이면 비활성
- 추천 시작값은 `0.60`
- `manual-test`와 `sell`에는 적용되지 않음
- 낮은 점수 구간이 실제 손실로 확인될 때 운영자가 바로 필터를 강화하는 용도

**연속 손실 초기화 버튼**:
- 리스크 가드가 `Max consecutive losses reached: 5`로 신규 매수를 막을 때 사용
- KST 날짜가 바뀌면 자동으로 초기화되지만, 운영 중 즉시 복구가 필요하면 설정 화면 버튼으로 직접 초기화 가능
- 성공 시 감사로그에 `loss_streak_reset` 이벤트가 남음

**자동매매 제외 코인**:
- 체크한 코인은 전략 서비스가 신호 생성 대상에서 바로 제외합니다.
- 각 코인마다 `제외 사유 메모`를 같이 저장할 수 있습니다.
- 전환 취약 코인 카드에서 바로 제외한 경우 기본 사유 메모가 자동 입력됩니다.
- 제외 상태와 사유는 마켓 목록, 포지션 카드, 코인 상세 화면에도 같이 표시됩니다.
- 제외/복귀/사유 변경은 감사로그에도 코인 단위로 남습니다.

**전환 추천 기준**:
- `전환 취약 코인` 카드와 코인 상세 화면의 `제외 추천 / 복귀 검토` 배지 계산 기준입니다.
- 설정 가능한 값:
  - 최소 `hold` 시작 건수
  - 제외 추천 최대 `hold→sell` 비율
  - 제외 추천 최소 `hold→hold` 비율
  - 복귀 검토 최소 `hold→sell` 비율
  - 복귀 검토 최대 `hold→hold` 비율
- 추천이 너무 자주 뜨거나 너무 보수적이면 이 값으로 조정합니다.

> ⚠️ 웹 UI 저장은 런타임 임시 저장입니다. `backend/.env` 파일 수정이 영구적입니다.

---

### 5-9. 토스트 알림 (우하단)

거래 이벤트 발생 시 5초간 표시:

| 알림 색상 | 이벤트 | 내용 |
|-----------|--------|------|
| 🟢 초록 | 주문 체결 | `KRW-BTC BUY @105,712,000` |
| 🟢 초록 | 익절(TP) 실행 | `KRW-ETH SELL — take profit` |
| 🔵 파랑 | 주문 접수 | `KRW-SOL BUY @170,000` |
| 🟡 노랑 | 손절(SL) 실행 | `KRW-XRP SELL — stop loss` |
| 🔴 빨강 | 리스크 거절 | `KRW-DOGE — Daily loss limit reached` |

---

### 5-10. 감사로그 페이지 (`/audit`)

- 최근 설정 변경, 주문 접수/체결, 주문 실패, 리스크 거절 이벤트를 시간순으로 조회
- `source`, `level` 필터 가능
- payload JSON 펼침 가능
- 운영 중 이상 징후는 여기서 먼저 확인하는 것이 가장 빠름

대표적으로 보이는 이벤트:
- `order_placed`
- `order_filled`
- `order_failed`
- `sl_triggered`
- `tp_triggered`
- `risk_rejected`
- `loss_streak_reset`
- `excluded_market_added`
- `excluded_market_restored`
- `excluded_market_reason_updated`

## 6. 자동매매 동작 방식

> ⚠️ **경고**: 실제 업비트 계좌에서 자산이 거래됩니다.

### 자동매매 전제 조건 체크리스트

- [ ] `backend/.env`에 업비트 API 키 설정 (주문하기 권한)
- [ ] 업비트에 현재 서버 IP 허용 등록
- [ ] `backend/.env`에 Groq API 키 설정 (없으면 TA-only 모드)
- [ ] 업비트 계좌에 KRW 잔고 존재
- [ ] 대시보드 헤더에서 **자동매매 ON** 활성화
- [ ] AI 신호 패널에 신호가 표시되고 있는지 확인

---

### 전체 데이터 흐름

```
─── 데이터 수집 ──────────────────────────────────────────────────
[Market Data Service]
  ├─ Upbit WebSocket 전체 KRW 마켓 실시간 시세 구독
  ├─ 1분봉 누적 → 60초마다 DB(candles_1m) 배치 저장
  └─ 실시간 ticker → Redis "upbit:ticker" 발행
         ↓
  [Gateway market_ws] → /ws/market → 프론트 마켓 워치리스트

─── AI 분석 (60초마다) ────────────────────────────────────────────
[Strategy Service]
  ├─ 24h 거래량 상위 10개 코인 선별
  ├─ 최근 200개 1분봉 조회
  ├─ 기술 지표 계산
  │     RSI(14) / MACD(12-26-9) / Bollinger Bands(20,2σ) / EMA(20,50)
  │     → TA Score (-1.0 ~ +1.0)
  ├─ Groq AI 감성 분석 (llama-3.1-8b-instant, 30분 캐시)
  │     입력: 종목명, 현재가, 24h 변동률, 거래량, TA 지표
  │     출력: sentiment_score + confidence
  │     실패 시: TA-only 모드 자동 폴백
  ├─ 신호 융합: final_score = 0.6 × TA + 0.4 × sentiment
  │     ├─ +0.25 초과 → BUY 신호
  │     ├─ −0.25 미만 → SELL 신호
  │     └─ 그 외     → HOLD (저장 생략)
  └─ DB 저장 + Redis "upbit:signal" 발행
         ↓
  [Gateway signal_ws] → /ws/signals → 프론트 AI 신호 패널

─── 주문 실행 (5초마다 폴링) ────────────────────────────────────
[Execution Service]
  ├─ Redis "auto_trade:enabled" 확인
  │     OFF 또는 Redis 읽기 실패 → 신호 처리 생략 (SL/TP는 계속 동작)
  ├─ 새 BUY/SELL 신호 조회
  ├─ 같은 신호를 먼저 `approved`로 claim
  │     └─ 이미 다른 워커가 claim 했으면 skip
  ├─ Upbit REST API로 현재가(ticker) 조회
  ├─ 보유 포지션이면 entry 규칙과 별도 exit 규칙 적용
  │     ├─ `ta_score <= -0.15` → 강제 SELL
  │     ├─ `downtrend` + `ta_score <= -0.05` → 보수적 SELL
  │     └─ 그 외 보유 포지션은 HOLD 유지
  ├─ [Risk Guard 검증]
  │     ├─ 시장 경보 코인(CAUTION/WARNING) → REJECT
  │     ├─ 일일 손실 ≥ 3% → REJECT
  │     ├─ 연속 손실 5회 이상 → REJECT
  │     ├─ 동시 보유 5종목 초과 → REJECT
  │     ├─ 단건 금액 > 총자산 1% → 수량 축소 후 APPROVE
  │     └─ 포지션 비중 > 10% → 수량 축소 후 APPROVE
  ├─ 매수 주문 직전 가용 KRW + 수수료 버퍼 기준 주문금액 clamp
  │     └─ 부족 시 거래소 호출 전 `Insufficient KRW after fee buffer`로 REJECT
  ├─ 최소 기대수익 필터는 일반 `buy`에만 적용
  │     └─ `sell`은 이 필터로 막지 않음
  ├─ APPROVE → Upbit 시장가 주문 실행
  └─ Redis "upbit:trade_event" 발행 → 프론트 토스트 알림

─── SL/TP 모니터 (10초마다, 자동매매 OFF도 항상 실행) ────────────
[Execution SL/TP Monitor]
  ├─ 모든 오픈 포지션 현재가 조회
  ├─ Redis "upbit:position_update" 발행 → 프론트 실시간 P&L 갱신
  ├─ 현재가 ≤ SL → 시장가 매도 + trade_event 발행
  └─ 현재가 ≥ TP → 시장가 매도 + trade_event 발행
```

운영 안정성 메모:

- 같은 `new` 신호는 먼저 claim 한 워커만 실행합니다.
- 재시작 후 `approved` 상태인데 실제 주문이 없는 신호는 다시 `new`로 복구합니다.
- `auto-trade` 설정을 읽을 수 없으면 거래를 계속 진행하지 않고 기본적으로 `OFF`로 간주합니다.

---

### SL(손절) / TP(익절) 기본값

| 항목 | 공식 | 예시 (BTC 매수가 100,000,000원) |
|------|------|---------------------------------|
| 손절(SL) | 진입가 × 0.97 | 97,000,000원 (-3%) |
| 익절(TP) | 진입가 × 1.06 | 106,000,000원 (+6%) |

> SL/TP는 DB의 포지션 테이블에 저장되며, **자동매매 OFF 상태에서도 항상 감시**합니다.

---

## 7. 위험관리 설정

### 기본 Risk 파라미터 (`backend/.env`)

```dotenv
RISK_MAX_DAILY_LOSS_PCT=0.03     # 일일 최대 손실률 3%
RISK_MAX_POSITION_PCT=0.10       # 종목당 최대 비중 10%
RISK_MAX_SINGLE_TRADE_PCT=0.01   # 단건 최대 거래 비율 1%
```

변경 후 적용:
```bash
docker compose restart execution
```

### Risk Guard 판정 로직

| 조건 | 결과 | 비고 |
|------|------|------|
| 시장 경보(CAUTION/WARNING) 코인 | 거래 거부 | 업비트 공식 경보 기준 |
| 일일 KST 기준 실현손익 ≤ −3% | 매수 거부 | 다음날 자동 해제 |
| 연속 손실 5회 이상 | 매수 거부 | KST 날짜 변경 시 자동 해제, 설정 화면에서 수동 초기화 가능 |
| 동시 보유 5종목 초과 | 신규 매수 거부 | |
| 단건 금액 > 총자산 × 1% | 수량 축소 후 실행 | 거부 아님, 조정 후 실행 |
| 포지션 비중 > 10% | 수량 축소 후 실행 | 거부 아님, 조정 후 실행 |
| 현재가 조회 실패 | 신호 rejected 처리 | 무한 재시도 방지 |
| 가용 KRW 부족 | 신호 rejected 처리 | 거래소 호출 전 `Insufficient KRW after fee buffer` |

### 현재 Risk 상태 확인

```bash
# 오늘 신호 처리 현황
docker compose exec postgres psql -U trader -d upbit_trader \
  -c "SELECT side, status, rejection_reason, COUNT(*)
      FROM signals
      WHERE ts > NOW() - INTERVAL '24 hours'
      GROUP BY side, status, rejection_reason
      ORDER BY COUNT(*) DESC;"
```

---

## 8. 백테스트 실행

`/backtest` 페이지에서 수집된 과거 캔들 데이터로 전략을 검증합니다.

| 입력 항목 | 설명 | 예시 |
|-----------|------|------|
| 마켓 | 백테스트 대상 종목 | `KRW-BTC` |
| 시작일 | 기간 시작 | `2026-01-01` |
| 종료일 | 기간 종료 | `2026-03-01` |
| 초기 자본 | 시작 금액 (KRW) | `1,000,000` |

> ⚠️ 백테스트 서비스는 현재 **stub 상태**입니다. 수집된 캔들 데이터 기반으로 향후 구현 예정.

---

## 9. 트러블슈팅

### 🔴 시세 데이터가 표시되지 않을 때

**증상**: 마켓 워치리스트에 `--` 표시, 데이터 업데이트 없음

**원인 1**: `market_data` 서비스의 Redis 연결이 오래되어 stale 상태
```bash
docker compose restart market_data
```

**원인 2**: `gateway` 서비스 크래시 (환경변수 오류 등)
```bash
docker compose logs gateway --tail=20
docker compose restart gateway
```

**원인 3**: 브라우저 캐시
→ 브라우저에서 **강력 새로고침** (`Ctrl+Shift+R` / `Cmd+Shift+R`)

**원인 4**: gateway의 Redis 구독이 누적되어 이전 구독이 비어있는 상태
```bash
docker compose restart gateway
```

---

### 🟡 AI 신호가 표시되지 않을 때

**원인 1**: 최초 기동 후 캔들 데이터 부족 (최소 50개 필요)
```bash
# 캔들 수 확인
docker compose exec postgres psql -U trader -d upbit_trader \
  -c "SELECT MIN(cnt), MAX(cnt), AVG(cnt)::int
      FROM (SELECT coin_id, COUNT(*) as cnt FROM candles_1m GROUP BY coin_id) t;"
```
→ MAX가 50 이상이면 곧 신호 생성 시작 (약 50분 대기)

**원인 2**: Groq API 키 미설정 → TA-only 모드로 동작
```bash
docker compose logs strategy --tail=20 | grep -E "Signal|ta_only|Groq"
```
→ `ta_only=True` 이면 정상 (Groq 없이 TA만으로 신호 생성)
→ `ta_only=False` 이면 Groq 포함 정상 신호

**원인 3**: Groq API 429 오류 (TPM 한도 초과)
```bash
docker compose logs strategy | grep "429"
```
→ 자동 폴백으로 계속 신호 생성, 다음 주기에 재시도

---

### 🔴 주문이 실행되지 않을 때

**체크 순서:**

1. **자동매매 토글 확인**: 대시보드 헤더에서 **자동매매 ON** 상태 확인

2. **신호 상태 확인**:
```bash
docker compose exec postgres psql -U trader -d upbit_trader \
  -c "SELECT side, status, rejection_reason, ts
      FROM signals ORDER BY ts DESC LIMIT 10;"
```

| status | 의미 |
|--------|------|
| `new` | 처리 대기 중 (자동매매 OFF면 계속 new) |
| `executed` | 주문 전송 완료 |
| `rejected` | Risk Guard 또는 오류로 거부됨 |

**주의**:
- 현재 버전에서는 보유 포지션에 대해 별도 `exit` 규칙이 동작합니다.
- 따라서 `sell`은 단순히 `final_score <= -0.30`일 때만 나오는 것이 아니라, 보유 포지션의 TA 약세가 강하면 더 일찍 발생할 수 있습니다.

3. **execution 로그 확인**:
```bash
docker compose logs execution --tail=30 | grep -E "Order|rejected|ERROR|auto_trade"
```

4. **업비트 API 키 및 IP 허용 확인**:
```bash
docker compose logs execution | grep "401\|Unauthorized"
```

---

### 🔴 Risk Guard가 모든 주문을 거부할 때

```bash
docker compose logs execution | grep "Signal rejected"
```

| rejection_reason | 원인 | 해결 |
|-----------------|------|------|
| `Daily loss limit reached` | 당일 손실 3% 초과 | 내일 자동 해제 / `RISK_MAX_DAILY_LOSS_PCT` 조정 |
| `Max open positions reached` | 5종목 동시 보유 | 일부 매도 후 재시도 |
| `Market warning active` | 업비트 경보 종목 | 경보 해제 대기 |
| `Insufficient qty` | 잔고 부족 | 업비트 KRW 잔고 확인 |
| `Insufficient KRW after fee buffer` | 가용 KRW 부족 | KRW 잔고 보충 또는 기존 포지션 정리 |
| `Ticker fetch error` | Upbit API 오류 | 잠시 후 자동 재시도 |
| `Max consecutive losses reached` | 연속 손실 5회 도달 | 설정 화면에서 연속 손실 초기화 또는 날짜 변경 대기 |
| `Expected profit ... < threshold ...` | 낮은 기대수익 진입 신호 | 일반 `buy`만 해당, `sell`에는 적용 안 됨 |

---

### 🟡 Groq API 오류

```bash
docker compose logs strategy | grep "Groq"
```

| 에러 | 원인 | 해결 |
|------|------|------|
| `401` | API 키 오류 | `.env`의 `GROQ_API_KEY` 확인 |
| `429 TPM` | 분당 토큰 초과 | 자동 폴백, 다음 주기 자동 재시도 |
| `429 RPD` | 일일 요청 초과(14,400건) | 다음날 자동 초기화 |

> Groq 오류 시 **TA-only 모드로 자동 폴백** → 정상 신호 생성 계속 유지

---

### 🔴 업비트 API 오류

| 에러 | 원인 | 해결 |
|------|------|------|
| `401 Unauthorized` | API 키 오류 또는 IP 미허용 | 키 확인, 업비트 IP 화이트리스트 등록 |
| `429 Too Many Requests` | 요청 빈도 초과 | 자동 대기 후 재시도 |
| `400 Bad Request` | 예전 잔고 부족/주문 규칙 위반 | 감사로그 `order_failed` 확인 |
| WS 연결 끊김 | 네트워크 불안정 | 자동 재연결 (별도 조치 불필요) |

---

### 🟡 설정 저장 500 에러

게이트웨이 로그에서 `ENCRYPTION_KEY` 오류 확인:
```bash
docker compose logs gateway --tail=10
```

유효한 Fernet 키 재생성:
```bash
docker compose exec gateway python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

출력된 키를 `backend/.env`의 `ENCRYPTION_KEY=`에 입력 후:
```bash
docker compose restart gateway
```

---

### 🟡 Gateway 시작 실패 (`ValidationError: Extra inputs are not permitted`)

**원인**: `.env`에 이전 버전의 환경변수(`GEMINI_API_KEY`, `OLLAMA_BASE_URL` 등)가 남아있어 pydantic 검증 실패

**확인**:
```bash
docker compose logs gateway | grep "ValidationError\|extra_forbidden"
```

**해결**: `backend/.env`에서 해당 변수 삭제 후 재시작:
```bash
docker compose restart gateway
```

현재 `.env`에서 허용되는 변수 목록:
`APP_ENV`, `APP_NAME`, `LOG_LEVEL`, `DATABASE_URL`, `REDIS_URL`, `JWT_*`, `UPBIT_*`, `GROQ_*`, `RISK_*`, `WS_*`, `BACKTEST_*`, `ENCRYPTION_KEY`

---

### 🟡 포트 충돌

```bash
lsof -i :3000    # 프론트엔드 포트 확인
lsof -i :8000    # 게이트웨이 포트 확인
lsof -i :5432    # PostgreSQL 포트 확인
lsof -i :6379    # Redis 포트 확인
```

---

### 🔴 전체 초기화 (데이터 삭제 포함)

```bash
docker compose down -v --rmi local   # 컨테이너 + 이미지 + 볼륨 전체 삭제
docker compose up -d --build         # 재빌드 및 시작
```

---

### 서비스 상태 전체 진단

```bash
# 서비스 상태 한눈에 보기
docker compose ps

# Redis 채널 구독 현황 확인
docker exec upbit-ai-trader-redis-1 redis-cli PUBSUB NUMSUB \
  upbit:ticker upbit:signal upbit:trade_event upbit:position_update

# 최근 1시간 신호 통계
docker compose exec postgres psql -U trader -d upbit_trader \
  -c "SELECT side, status, COUNT(*) FROM signals
      WHERE ts > NOW() - INTERVAL '1 hour'
      GROUP BY side, status;"
```

---

## 10. API 레퍼런스

전체 엔드포인트: **http://localhost:8000/docs** (Swagger UI)

### REST API

| 메서드 | 경로 | 설명 | 주요 파라미터 |
|--------|------|------|---------------|
| GET | `/health` | 서버 상태 확인 | — |
| GET | `/api/v1/markets` | KRW 전체 마켓 목록 | — |
| GET | `/api/v1/markets/{market}/candles` | 캔들 데이터 | `interval=1m`, `limit=200` |
| GET | `/api/v1/signals` | AI 신호 목록 | `market=KRW-BTC`, `side=buy`, `limit=20` |
| GET | `/api/v1/orders` | 주문 내역 | `state=done\|wait\|cancel`, `market` |
| GET | `/api/v1/positions` | 포지션 현황 | `latest_signal`, `latest_sell_signal`, `sell_wait_reason`, `SL/TP 거리` 포함 |
| GET | `/api/v1/portfolio/equity-curve` | 수익 곡선 | `limit`, `days` |
| GET | `/api/v1/portfolio/performance` | 실거래 성과 집계 | `limit`, `days`, `market` |
| GET | `/api/v1/portfolio/transition-quality/{market}` | 특정 코인의 신호 전환 품질 | `days` |
| GET | `/api/v1/portfolio/daily-report` | 오늘 운영 요약 | — |
| GET | `/api/v1/portfolio/daily-report/history` | 최근 일일 운영 리포트 이력 | `limit` |
| GET | `/api/v1/audit-events` | 감사로그 조회 | `event_type`, `source`, `market`, `limit` |
| POST | `/api/v1/backtests/runs` | 백테스트 실행 | `market`, `start_dt`, `end_dt`, `initial_capital` |
| POST | `/api/v1/secrets/upbit-keys` | 업비트 키 저장 | `access_key`, `secret_key` |
| POST | `/api/v1/secrets/groq-key` | Groq 키 저장 | `api_key` |
| GET | `/api/v1/settings/auto-trade` | 자동매매 상태 | — |
| PATCH | `/api/v1/settings/auto-trade` | 자동매매 ON/OFF | `enabled: bool` |
| GET | `/api/v1/settings/external-position-stop-loss` | 외부 보유분 손절 상태 | — |
| PATCH | `/api/v1/settings/external-position-stop-loss` | 외부 보유분 손절 ON/OFF | `enabled: bool` |
| GET | `/api/v1/settings/manual-test-mode` | 수동 테스트 모드 상태 | — |
| PATCH | `/api/v1/settings/manual-test-mode` | 수동 테스트 모드 ON/OFF | `enabled: bool` |
| GET | `/api/v1/settings/min-buy-final-score` | 최소 매수 Final Score 조회 | — |
| PATCH | `/api/v1/settings/min-buy-final-score` | 최소 매수 Final Score 설정 | `value: 0.0 ~ 1.0` |
| POST | `/api/v1/settings/risk/reset-loss-streak` | 연속 손실 초기화 | — |

### WebSocket

```
ws://localhost:8000/ws/market?codes=KRW-BTC,KRW-ETH
```

| 경로 | 설명 | 데이터 형식 |
|------|------|-------------|
| `/ws/market?codes=KRW-BTC,...` | 실시간 시세 (Upbit SIMPLE 형식) | `{cd, tp, c, cr, cp, atv24h, ...}` |
| `/ws/signals` | 실시간 AI 신호 | `{market, side, final_score, confidence, ...}` |
| `/ws/orders` | 실시간 주문 업데이트 | `{id, market, side, status, ...}` |
| `/ws/trade-events` | 거래 이벤트 (체결/SL/TP/거절) | `{type, market, side, price, reason}` |
| `/ws/portfolio` | 포지션 실시간 업데이트 | `{market, qty, avg_entry_price, ...}` |

### WebSocket 이벤트 타입 (`/ws/trade-events`)

| type | 설명 |
|------|------|
| `order_placed` | 주문 접수 |
| `order_filled` | 주문 체결 |
| `sl_triggered` | 손절 실행 |
| `tp_triggered` | 익절 실행 |
| `risk_rejected` | Risk Guard 거부 |

---

## 11. 아키텍처 개요

### 서비스 구성 (9개 Docker 컨테이너)

```
┌─────────────────── Docker Compose Network ─────────────────────┐
│                                                                 │
│  [frontend :3000]  ←── HTTP/WS ──→  [gateway :8000]           │
│      Next.js 16                        FastAPI + Uvicorn        │
│      (standalone build)                REST API + WebSocket     │
│                                              │                  │
│  [postgres :5432]  ←────────────────────────┤                  │
│      PostgreSQL 16                           │                  │
│                                              │                  │
│  [redis :6379]  ←── pub/sub ────────────────┤                  │
│      Redis 7           ↑    ↑    ↑           │                  │
│                        │    │    │            │                  │
│  [market_data]  ───────┘    │    │            │                  │
│      Upbit WS 수집           │    │            │                  │
│                             │    │            │                  │
│  [strategy]  ───────────────┘    │            │                  │
│      AI 신호 생성                  │            │                  │
│                                  │            │                  │
│  [execution]  ────────────────────┘           │                  │
│      주문 실행 + SL/TP                         │                  │
│                                              │                  │
│  [risk]  (stub)                              │                  │
│  [backtest]  (stub)                          │                  │
└──────────────────────────────────────────────────────────────── ┘
```

### Redis Pub/Sub 채널

| 채널 | 발행자 | 구독자 | 내용 |
|------|--------|--------|------|
| `upbit:ticker` | market_data | gateway (market_ws) | 실시간 시세 |
| `upbit:signal` | strategy | gateway (signal_ws) | AI 매매 신호 |
| `upbit:trade_event` | execution | gateway (trade_event_ws) | 주문/체결/SL/TP |
| `upbit:position_update` | execution | gateway (trade_event_ws) | 포지션 업데이트 |

### 데이터베이스 테이블

| 테이블 | 내용 |
|--------|------|
| `coins` | KRW 마켓 목록 |
| `candles_1m` | 1분봉 OHLCV |
| `indicator_snapshots` | RSI/MACD/BB/EMA 스냅샷 |
| `sentiment_snapshots` | Groq AI 감성 분석 결과 |
| `signals` | AI 매매 신호 |
| `orders` | 주문 |
| `fills` | 체결 내역 |
| `positions` | 현재 포지션 |
| `backtest_runs` | 백테스트 실행 기록 |
| `backtest_trades` | 백테스트 거래 내역 |
| `backtest_metrics` | 백테스트 성과 지표 |
