# DS218+ NAS 운영 메모

최종 업데이트: 2026-03-25

## 결론

- Synology `DS218+`에서 이 프로젝트를 Docker로 운영하는 것은 가능하다.
- 현재 메모리 `10GB` 업그레이드 상태면 메모리 측면은 충분한 편이다.
- 다만 이 장비는 `개발 + 빌드 + 운영`을 동시에 하기보다는 `운영 전용`으로 쓰는 것이 맞다.

## 가능한 이유

- AI 추론을 NAS에서 직접 하지 않는다.
- 이 프로젝트의 AI 호출은 `Groq API` 외부 서비스로 나가므로, NAS는 주로 다음 역할만 수행한다.
  - `frontend`
  - `gateway`
  - `market_data`
  - `strategy`
  - `execution`
  - `postgres`
  - `redis`

즉 CPU가 아주 강하지 않아도 `실행` 자체는 가능하다.

## 권장 운영 방식

### 1. NAS는 운영 전용으로 사용

- 코드 수정, 테스트, 이미지 빌드는 맥에서 수행
- NAS는 최종 반영된 코드/이미지 실행만 담당

### 2. 기본 서비스만 실행

권장 서비스:

- `postgres`
- `redis`
- `gateway`
- `market_data`
- `strategy`
- `execution`
- `frontend`

권장하지 않는 것:

- NAS에서 잦은 `docker compose build`
- 무거운 백테스트 반복 실행
- 개발용 디버깅 세션 장시간 유지

### 3. 배포 방식

가장 현실적인 방식:

1. 맥에서 코드 수정
2. 맥에서 테스트 및 빌드 검증
3. Git 반영
4. NAS에서 최신 코드 pull
5. NAS에서 필요한 서비스만 재기동

기본 예시:

```bash
docker compose up -d postgres redis gateway market_data strategy execution frontend
```

코드 변경 반영 시:

```bash
docker compose up -d --build gateway strategy execution frontend
```

## DS218+에서 주의할 점

### CPU

- DS218+는 고성능 서버가 아니다.
- Next.js 빌드, Python 패키지 설치, Docker 이미지 재빌드는 느릴 수 있다.
- 따라서 빌드는 가능하면 NAS에서 자주 하지 않는 편이 좋다.

### DSM 작업과 충돌

- Synology Drive 인덱싱
- Hyper Backup
- 미디어 썸네일 생성
- 대용량 파일 복사

이런 작업이 겹치면 자동매매 컨테이너 응답성이 떨어질 수 있다.

### 디스크/로그 관리

- 로그가 너무 많이 쌓이지 않도록 관리 필요
- DB/Redis 볼륨 백업 정책 필요
- `docker compose down -v`는 운영 중 사용 금지

## 운영 전 체크

- Docker/Container Manager 정상 동작
- NAS 시간 동기화 정상
- 외부 인터넷 연결 안정적
- 업비트 API 키 IP 허용 정책 확인
- DSM 재부팅 후 컨테이너 자동 재시작 정책 확인
- `auto-trade` 상태와 감사로그 확인

## 권장 판단

- `소액 자동매매 운영`: 가능
- `개인용 24/7 봇 운영`: 가능
- `개발/빌드/운영 올인원`: 비추천
- `더 높은 안정성/속도 필요`: 미니PC나 별도 저전력 서버가 더 적합

## 한 줄 판단

`DS218+ 10GB 업그레이드 상태면 운영은 가능하지만, 개발 서버가 아니라 운영 전용 노드로 쓰는 게 맞다.`
