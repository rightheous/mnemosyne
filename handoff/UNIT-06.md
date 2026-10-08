# UNIT-06 인수 경계

담당: 환경·backend manifest/lockfile·Docker/Compose·CI·통합검사. 공통 시작 tag `mnemosyne-bootstrap-v0.1.0`, 계약 `0.1.0`.

실제 등록 경로: `checks/source_adapters.py` · `run_integration_checks`. docs/INTEGRATION.md의 signature와 callers를 읽는다.

기존 pyproject/requirements/CI/Docker 배치를 유지하면서 WSL2 개인 프로필 구현. single-user auth, private/Tailscale/HTTPS, server-only provider credentials, OpenAI-compatible 교체. 백업/복구/health/start/restart. 주어진 required capabilities를 경량화라는 이유로 제거하지 않음. 웹 manifest는 05, Xcode는 04, DB는 01, 계약은 통합 담당.

현재 common seam/fixture가 있다는 것은 제품 구현 완료가 아니다. 빈 port를 success/no-op으로 채우지 않는다. 필수 기능은 모두 이번 범위다.

정확한 수정 가능 파일 77개는 integration/ownership.json의 owners.UNIT-06 배열이다. 주요 directory는 OWNERSHIP.md 참조. 다른 소유자의 공통 startup/계약/DB/manifest 파일을 편집하지 않는다.

새 계약 변경은 소비자 영향·version·fixture·검증 변경을 포함해 통합 담당에게 제안한다. DB 요구는 schema/migration/transaction/검증 명세로 01에 전달한다. 사용자 지시 없이 다른 채팅에 메시지를 보내지 않는다.

인수 결과는 실행한 명령·실제 source/service/build/device 종류·실패/차단을 구별하고 기록한다. 공통 fixture PASS를 제품 오프라인/LLM/기기 검증으로 대체하지 않는다. 원본 hash, 잘못된 인용 거부, replay/cancel/error와 재시작 저장을 실제 경계에서 확인한다.
