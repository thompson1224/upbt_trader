# Upbit AI Trader 운영 런북

최종 업데이트: 2026-03-25

## 목적

실거래 전후 운영자가 바로 실행할 수 있는 점검, 재시작, 설정 변경, 장애 대응 절차를 정리한다.

## 기본 원칙

- 자동매매 기본값은 `OFF`로 유지한다.
- 외부 보유분 자동 손절 기본값도 `OFF`로 유지한다.
- 실거래 전에는 반드시 스모크체크를 먼저 수행한다.
- `risk`, `backtest` 서비스는 현재 기본 기동 대상이 아닌 stub 프로필이다.

## 기본 기동

```bash
docker compose up -d --build postgres redis gateway market_data strategy execution frontend
```

확인:

```bash
docker compose ps
```

정상 기본 서비스:

- `postgres`
- `redis`
- `gateway`
- `market_data`
- `strategy`
- `execution`
- `frontend`

## 스모크체크

로컬에서 실행:

```bash
./scripts/ops_smoke_check.sh
```

수동 점검:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/api/v1/settings/auto-trade
curl -sS http://localhost:8000/api/v1/settings/external-position-stop-loss
curl -sS http://localhost:8000/api/v1/positions
curl -sS http://localhost:8000/api/v1/audit-events?limit=10
```

## 실거래 시작 전 체크리스트

1. `docker compose ps`에서 기본 서비스가 모두 정상인지 확인
2. `GET /api/v1/settings/auto-trade`가 `false`인지 확인
3. `GET /api/v1/settings/external-position-stop-loss`가 의도한 값인지 확인
4. `GET /api/v1/positions`에서 외부 보유분/전략 포지션 source를 확인
5. `GET /api/v1/audit-events?limit=20`에서 최근 오류/거절 이벤트를 확인
6. 업비트 계좌 보유 자산과 시스템 포지션이 일치하는지 확인
7. 필요한 경우에만 자동매매를 `ON`

## 자동매매 ON/OFF

자동매매 상태 확인:

```bash
curl -sS http://localhost:8000/api/v1/settings/auto-trade
```

자동매매 OFF:

```bash
curl -sS -X PATCH http://localhost:8000/api/v1/settings/auto-trade \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

자동매매 ON:

```bash
curl -sS -X PATCH http://localhost:8000/api/v1/settings/auto-trade \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true}'
```

## 외부 보유분 자동 손절 ON/OFF

기본값은 `OFF`다.

상태 확인:

```bash
curl -sS http://localhost:8000/api/v1/settings/external-position-stop-loss
```

OFF:

```bash
curl -sS -X PATCH http://localhost:8000/api/v1/settings/external-position-stop-loss \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'
```

ON:

```bash
curl -sS -X PATCH http://localhost:8000/api/v1/settings/external-position-stop-loss \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true}'
```

주의:

- 외부 보유분에는 자동 익절을 적용하지 않는다.
- 외부 보유분 손절은 명시적으로 켠 경우에만 동작한다.

## 재시작 절차

전체 기본 서비스 재시작:

```bash
docker compose restart gateway market_data strategy execution frontend
```

실행 서비스만 재시작:

```bash
docker compose restart execution
```

재시작 후 확인:

```bash
curl -sS http://localhost:8000/health
curl -sS http://localhost:8000/api/v1/settings/auto-trade
curl -sS http://localhost:8000/api/v1/audit-events?limit=10
```

## 마이그레이션 절차

신규 배포 후 DB 마이그레이션:

```bash
docker compose exec -T gateway sh -lc 'cd /app && alembic upgrade head'
```

현재 버전 확인:

```bash
docker compose exec -T gateway python - <<'PY'
import asyncio
from sqlalchemy import text
from libs.db.session import get_session_factory

async def main():
    async with get_session_factory()() as db:
        print((await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one())

asyncio.run(main())
PY
```

## 키 교체 절차

업비트 키 교체 후:

1. 설정 화면 또는 API로 업비트 키 저장
2. `GET /api/v1/audit-events?limit=10`에서 `upbit_keys_updated` 확인
3. `execution` 로그에서 업비트 `401`이 없는지 확인

Groq 키 교체 후:

1. 설정 화면 또는 API로 Groq 키 저장
2. `strategy` 서비스 재시작

```bash
docker compose restart strategy
```

## 사고 대응

### 자동매매 이상 주문 발생 시

1. 즉시 자동매매 OFF
2. 필요 시 외부 보유분 자동 손절 OFF
3. `execution` 로그 확인
4. `GET /api/v1/audit-events?limit=50` 확인
5. `GET /api/v1/orders?state=wait` 및 최근 주문 내역 확인

### Redis 상태 유실 의심 시

1. `execution` 재시작
2. `runtime_state` 복구가 수행되었는지 로그와 상태 확인
3. `GET /api/v1/audit-events?limit=20` 확인

### Upbit 429 증가 시

1. `execution` 로그에서 429 빈도 확인
2. 필요 시 `execution`만 재시작
3. 시장 수/모니터 빈도 조정 검토

## 참고

- 감사 로그 조회: `GET /api/v1/audit-events`
- 포지션 조회: `GET /api/v1/positions`
- 자산곡선 조회: `GET /api/v1/portfolio/equity-curve`
- 스텁 서비스 기동: `docker compose --profile stub up -d`
