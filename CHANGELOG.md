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