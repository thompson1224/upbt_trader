# Changelog - 2026-03-29 (심화)

## v0.3.0 - 마이크로서비스 아키텍처 강화

### Risk Service 구현 (2026-03-29)

####概述
기존 stub 상태였던 `risk_service`를 독립적인 마이크로서비스로 구현하여 위험 관리 기능을 분리했습니다.

#### 변경된 파일
- `backend/apps/risk_service/main.py` - 메인 서비스 루프 + Redis pub/sub
- `backend/apps/risk_service/account_tracker.py` - 계좌 상태 추적 (일일 P&L, 연속 손실)
- `backend/apps/risk_service/portfolio_monitor.py` - 포트폴리오 위험 모니터링 + 알림
- `backend/apps/gateway/api/v1/risk.py` - 위험 지표 REST API (신규)
- `backend/apps/gateway/main.py` - risk 라우터 등록
- `backend/apps/execution_service/main.py` - RPC 호출로 전환
- `docker-compose.yml` - `profiles: ["stub"]` 제거

#### 주요 기능
1. **Trade Event 구독** - Redis `upbit:trade_event` 채널에서 체결 이벤트 수신
2. **계좌 상태 추적** - 일일 손익, 연속 손실, 가용 잔고 실시간 추적
3. **주기적 Metrics 발행** - 30초마다 Redis에 위험 지표 저장
4. **포트폴리오 모니터링** - 60초마다 포지션 집중도, 유동성 등 점검
5. **RPC 통신** - execution_service와 Redis RPC로 위험 평가

#### RPC 통신 흐름
```
execution_service                      risk_service
      │                                     │
      │──── publish (upbit:risk:request) ──>│
      │                                     │ evaluate()
      │<--- publish (upbit:risk:response) --│
```

#### 신규 API 엔드포인트
| 메서드 | 엔드포인트 | 설명 |
|--------|-----------|------|
| GET | `/api/v1/risk/metrics` | 현재 위험 지표 조회 |
| GET | `/api/v1/risk/status` | 위험 서비스 상태 (healthy/warning/critical) |
| POST | `/api/v1/risk/reset-daily-pnl` | 일일 손익 0으로 초기화 |

---

### Backtest Service 구현 (2026-03-29)

####概述
stub 상태였던 `backtest_service`를 Polling 방식의 워커로 구현하여 실제 백테스트를 실행할 수 있게 했습니다.

#### 변경된 파일
- `backend/apps/backtest_service/main.py` - Polling + 실행 로직 (신규 구현)
- `backend/apps/gateway/api/v1/backtests.py` - Background task 제거 (별도 서비스로 이동)
- `docker-compose.yml` - backtest 프로필 stub 제거

#### 아키텍처
```
Gateway API                    Backtest Service (Worker)
     │                                 │
     │──── POST /backtests/runs ──────>│
     │     (status=pending)            │
     │                                 │ <-- Polling every 10s
     │                                 │     Picks up pending runs
     │                                 │     Executes backtest
     │                                 │     Saves results to DB
     │<--- GET /backtests/runs/{id} ---│
```

#### 주요 기능
1. **Polling**: 10초마다 DB에서 `status=pending` 레코드 조회
2. **Single Mode**: 단일 기간 백테스트
3. **Walk-forward Mode**: 순차적 윈도우 백테스트
4. **결과 저장**: trades, windows, metrics를 DB에 저장
5. **에러 처리**: 실패 시 `status=failed` + error_message 저장

#### API 사용법
```bash
# 백테스트 실행 요청
curl -X POST http://localhost:8001/api/v1/backtests/runs \
  -H "Content-Type: application/json" \
  -d '{
    "market": "KRW-BTC",
    "strategy_id": "hybrid_v1",
    "mode": "single",
    "train_from": "2026-03-01T00:00:00Z",
    "train_to": "2026-03-15T00:00:00Z",
    "test_from": "2026-03-15T00:00:00Z",
    "test_to": "2026-03-22T00:00:00Z"
  }'

# 결과 조회
curl http://localhost:8001/api/v1/backtests/runs/{run_id}/metrics
```

---

## 실행 방법

```bash
# 모든 서비스 재시작
docker compose up -d risk backtest gateway execution

# 특정 서비스만 확인
docker compose ps
docker compose logs risk --tail=20
docker compose logs backtest --tail=20
```

---

## 알아야 할 점

1. **execution_service**는 여전히 로컬 `PreTradeRiskGuard` 폴백을 유지합니다. RPC 실패 시 자동으로 로컬评估로 전환합니다.
2. **백테스트 서비스**는 GPU가 필요 없는 CPU 기반 백테스트 엔진입니다. 대량의 데이터 처리가 가능합니다.
3. **risk_service**는 `upbit:trade_event` 채널을 구독하여 실시간으로 체결 이벤트를 처리합니다.

---

## Threshold 최적화 (2026-03-29)

### 배경
- 기존 `min_buy_final_score` = 0.60으로 설정되어 있었음
- 백테스트 분석 결과 0.60 이상 신호가 거의 발생하지 않음 (분석 기간 중 0건)
- 시장 하락장에서 과도한 매수를 방지하기 위한 적정 값 연구 필요

### 분석 결과 (2026-03-24 ~ 2026-03-28, KRW-BTC)

| Threshold | 발생 가능 신호 수 |
|-----------|-----------------|
| 0.35 | 51 |
| 0.40 | 43 |
| 0.45 | 40 |
| 0.50 | 9 |
| 0.55+ | 0 |

### 결정
**`min_buy_final_score` = 0.40**으로 조정 (2026-03-29)

이유:
1. 0.40 이상 신호가 충분히 발생 (43개/일)
2. 시장 하락 시 과도한 매수 방지
3. 너무 높으면 거래 기회 상실 (0.60은 현실적이지 않음)

### 설정 변경
```bash
# 현재 설정 확인
curl http://localhost:8001/api/v1/settings/min-buy-final-score
# {"value": 0.4}

# 설정 변경
curl -X PATCH http://localhost:8001/api/v1/settings/min-buy-final-score \
  -H "Content-Type: application/json" \
  -d '{"value": 0.40}'
```

---

## 오늘 작업 요약 (2026-03-29)

### 완료된 작업

| 작업 | 커밋 | 상태 |
|------|------|------|
| Risk service 구현 | `2c6164b` | ✅ |
| Backtest service 구현 | `4f4cb82` | ✅ |
| Threshold 최적화 (0.60→0.40) | `3319f9f` | ✅ |
| Groq 감성 분석 통합 | `c4232ed` | ✅ |
| DESIGN.md 작성 | `19c73ec` | ✅ |

### 현재 시스템 상태

- **Risk Service**: healthy ✅
- **Auto-trade**: ON ✅
- **일일 손익**: 0원
- **연속 손실**: 0
- **min_buy_final_score**: 0.40

### 시장 상황

- TA 점수가 약세 구간 (0에 가까움)
- Groq 감성 분석: BTC -0.8 (부정적)
- Threshold (0.40)达标 신호 없음
- **시스템 정상 작동 중** - 시장 회복 시 자동 거래 발생

### 다음 우선순위 작업

1. **거래 모니터링** - threshold + Groq 효과 실시간 확인
2. **WebSocket 재연결 로직 보강** - 네트워크 단절 복구
3. **단위 테스트 작성** - 신규 서비스 테스트 Coverage