# Upbit AI Trader 남은 체크리스트

최종 업데이트: 2026-03-28

## 현재 상태

- [x] 기본 서비스 기동 및 스모크체크 완료
- [x] DB 마이그레이션 `004` 적용 완료
- [x] 자동매매 `ON`
- [x] 외부 보유분 자동 손절 `OFF`
- [x] 수동 테스트 모드 `OFF`
- [x] 실계좌 잔고 동기화 확인 완료
- [x] 수동 테스트 경로 `buy -> fill -> position -> sell -> fill` 검증 완료
- [x] 현재 포지션 상태 확인
  - `KRW-DOGE`
  - `source=strategy`
  - 사용자가 명시적으로 auto-trade 관리 대상으로 포함시켰고, 기본 `stop_loss=135.8`, `take_profit=148.4` 적용 완료
  - `KRW-BARD`
  - `source=strategy`
  - 자동매매 `ON` 이후 실제 전략 `buy` 1건이 체결되어 생성된 포지션

## 자동매매 ON 전 남은 필수

- [x] `GET /api/v1/audit-events?limit=20`에서 원인 미확인 `error`, `warning`, `risk_rejected` 없음 확인
- [x] `execution` 로그에서 `401`, 반복 `429`, 연속 예외 없음 확인
- [x] 업비트 계좌 잔고와 `/api/v1/positions`가 의도대로 일치하는지 확인
  - 현재 실잔고는 전략 관리 포지션 기준 `DOGE + BARD`가 반영되는 상태
  - 로컬 포지션도 `KRW-DOGE`, `KRW-BARD` 모두 `source=strategy`로 유지됨
- [x] 자동매매를 실제로 켜기 전 stale `buy` 신호 33건을 `expired` 처리
- [x] 자동매매 `ON`

## 자동매매 ON 직전 권장

- [x] `manual-test-mode`가 `false`인지 재확인
- [x] `external-position-stop-loss`가 의도한 값인지 재확인
- [x] `/api/v1/orders?limit=10`에서 로컬 기준 예상치 못한 미체결 주문 없음 확인
- [ ] 필요하면 `docker compose restart execution` 후 `/health`, `/api/v1/audit-events` 재확인

## 자동매매 ON 후 첫 관찰

- [x] `/api/v1/settings/auto-trade`가 `true`인지 확인
- [x] `/api/v1/audit-events?limit=10`에서 `auto_trade_toggled` 기록 확인
- [x] 5~10분 동안 `execution` 로그에서 연속 오류가 없는지 확인
- [x] `/api/v1/orders`, `/api/v1/positions`, `/api/v1/audit-events`에서 이상 주문/체결이 없는지 확인
  - stale `buy` 신호 33건은 `expired` 처리됨
  - 이후 실제 전략 `buy` 1건 발생:
    - `KRW-BARD`
    - 로컬 주문 ID `7`
    - 주문 상태 `cancel`이지만 체결분 반영 완료
    - 현재 `source=strategy` 포지션 생성 및 기본 `stop_loss`/`take_profit` 적용 확인
  - 이후 `KRW-DOGE`도 사용자 요청으로 `source=strategy` 전환 및 auto-trade 포함 완료

## 운영 전 마지막 권장

- [x] 소액 자동매매 실거래 1회 관찰
- [x] 자동매매 `ON` 상태에서 실제 전략 주문 1건 확인
- [x] `insufficient_funds_bid` 보수 후 실제 전략 매수 1건 정상 처리 확인
- [ ] 하루 정도 주문/체결/감사로그 모니터링
- [ ] 문제 없으면 그때부터 24/7 운영 판단

## 사실상 남은 일

- [x] 자동매매 ON
- [x] ON 직후 5~10분 관찰 마무리
- [x] 소액 자동매매 1회 결과 확인
- [x] 자동매매 `ON` 상태 첫 실제 전략 주문 확인
- [x] KRW clamp 보수 후 새 실제 전략 매수 1건 확인
- [ ] 하루 관찰 후 24/7 운영 여부 결정

## 바로 쓸 명령

주의:

- 프런트의 `자동매매 확인 중` 표시는 게이트웨이 상태를 아직 읽지 못했다는 뜻입니다.
- 조회 실패 시에도 UI가 즉시 `OFF`로 바뀌지 않으므로, 최종 상태 판단은 아래 API 응답으로 확인하는 편이 맞습니다.

자동매매 상태 확인:

```bash
curl -sS "${GATEWAY_BASE_URL:-http://localhost:${GATEWAY_HOST_PORT:-8001}}/api/v1/settings/auto-trade"
```

자동매매 ON:

```bash
curl -sS -X PATCH "${GATEWAY_BASE_URL:-http://localhost:${GATEWAY_HOST_PORT:-8001}}/api/v1/settings/auto-trade" \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true}'
```

자동매매 OFF:

```bash
curl -sS -X PATCH "${GATEWAY_BASE_URL:-http://localhost:${GATEWAY_HOST_PORT:-8001}}/api/v1/settings/auto-trade" \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

감사 로그 확인:

```bash
curl -sS "${GATEWAY_BASE_URL:-http://localhost:${GATEWAY_HOST_PORT:-8001}}/api/v1/audit-events?limit=20"
```

## 참고 문서

- [OPERATIONS_RUNBOOK.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/OPERATIONS_RUNBOOK.md)
- [OPERATIONS_APPROVAL_2026-03-25.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/OPERATIONS_APPROVAL_2026-03-25.md)
- [WORKLOG_2026-03-24.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/WORKLOG_2026-03-24.md)
- [WORKLOG_2026-03-28.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/WORKLOG_2026-03-28.md)
- [USER_MANUAL.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/USER_MANUAL.md)
