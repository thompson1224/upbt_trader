# Upbit AI Trader 운영 승인 메모

최종 업데이트: 2026-03-25

## 운영 판정

- 현재 판정: `소액 실거래 운영 가능`
- 현재 자동매매 상태: `ON`
- 현재 수동 테스트 모드: `OFF`
- 현재 외부 보유분 자동 손절: `OFF`

## 승인 근거

- 기본 서비스 기동, API, WebSocket, 프론트 접근이 정상 동작한다.
- 실계좌 잔고 동기화와 포지션 반영이 정상 동작한다.
- 수동 테스트 경로 `buy -> fill -> sell -> fill` 실거래 검증이 완료됐다.
- 실제 전략 주문 `KRW-BARD`, `KRW-SOL`이 생성되고 체결 반영까지 확인됐다.
- 실제 전략 주문 `KRW-BARD`, `KRW-SOL`, `KRW-ONT`가 생성되고 체결 반영까지 확인됐다.
- 주문 실패 원인 가시화가 완료되어 `order_failed`가 감사로그에 남는다.
- `insufficient_funds_bid` 이슈는 가용 KRW와 수수료 버퍼 clamp 보수 이후 새 전략 매수 `KRW-SOL` 1건이 정상 체결되어 재발하지 않았다.
- `KRW-BARD`는 실제 `SL` 발동으로 자동 매도 완료되어 매도 경로도 검증됐다.
- `loss_streak reset` 이후 신규 매수 `KRW-ONT`가 다시 체결되어 운영 복구 경로도 확인됐다.
- 최근 운영 관찰 구간에서 `401`, 반복 `429`, `Traceback`은 확인되지 않았다.

## 현재 확인된 전략 포지션

- `KRW-DOGE`
  - `source=strategy`
  - `stop_loss=135.8`
  - `take_profit=148.4`
- `KRW-BARD`
  - 실제 `SL` 청산 완료
- `KRW-SOL`
  - `source=strategy`
  - `stop_loss=131726.0`
  - `take_profit=143948.0`
- `KRW-ONT`
  - `source=strategy`
  - `stop_loss=95.836`
  - `take_profit=104.728`

## 아직 남은 운영 조건

- 하루 이상 추가 관찰
- 열린 포지션 중 추가 `SL` 또는 `TP` 집행 확인
- 새 주문 실패가 발생해도 모두 감사로그와 원인 메시지로 식별 가능한지 확인

## 최종 결론

- 현재 상태는 `프로토타입` 단계는 지났다.
- 현재 상태는 `소액 실거래 가능`으로 판단한다.
- 다만 `24/7 완전 무인운영 확정`은 하루 추가 관찰 후 최종 승인하는 것이 맞다.

## 관련 문서

- [FINAL_CHECKLIST.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/FINAL_CHECKLIST.md)
- [OPERATIONS_RUNBOOK.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/OPERATIONS_RUNBOOK.md)
- [WORKLOG_2026-03-24.md](/Users/ljmac/CC%20Projects/upbit-ai-trader/WORKLOG_2026-03-24.md)
