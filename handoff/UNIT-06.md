# UNIT-06 인수 경계

현재 제품 소유 경로: 없음 (backend/deploy audit 대기). 현재 준비 소유: 이 문서와 `checks/requirements.txt`, `checks/validate_contracts.py`, `checks/ipad-consumer.swift`.

담당: WSL2/Docker 설치·실행/Compose, CI, 통합 검증, backend 공통 manifest/lockfile. 계약과 다른 유닛 제품 구현은 통합 담당/해당 유닛 소유다. 준비 검사 의존성은 제품 backend 요구사항이 아니다.

실제 소스 확인 전 Docker image/service/port/build 명령을 추정해 고정하지 않는다. 현재는 Python JSON Schema/OpenAPI 검증, Node/Swift fixture 소비, source gate만 실행한다. backend manifest 이름/경로는 registry에 실제 값으로 배정해야 한다.

인수: 실제 build/test, WSL2 PC 시작/재시작, private/Tailscale/HTTPS 연결, readiness/secret/log, DB+original+annotation+learning backup/restore, 각 port의 실제 통합 검사. 통과한 fixture 수와 실제 제품/기기 미검증을 따로 보고한다.
