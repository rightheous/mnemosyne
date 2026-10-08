# 단독 수정 담당

각 tracked 파일은 정확히 한 소유자를 갖는다. 기계 판정은 `integration/ownership.json`의 **정확한 파일 경로 목록**을 사용한다. 알 수 없는 파일은 검사를 실패시킨다. glob의 겹침이나 공동 소유는 허용하지 않는다.

## 현재 실제 준비 파일의 소유권

| 담당 | 현재 저장소에서 단독 수정할 실제 경로 | 호출/전달 경계 |
|---|---|---|
| UNIT-01 | `handoff/UNIT-01.md` | 문서 검색·인용 검증·원본/주석 동기화·공통 migration; UNIT-02의 persistence 요구를 받는다. |
| UNIT-02 | `handoff/UNIT-02.md` | Tutor runtime/API, 한국어 prompt, 모든 필수 capability와 학습 상태 서비스; DB 변경 명세를 UNIT-01에 전달한다. |
| UNIT-03 | `handoff/UNIT-03.md` | ReaderFacade·geometry·Pencil·로컬 저장/outbox 원자성; UNIT-04가 facade만 호출한다. |
| UNIT-04 | `handoff/UNIT-04.md` | iPad 화면·네트워크·동기화 worker·앱 진입점·Xcode 설정; 내부 Reader를 수정하지 않는다. |
| UNIT-05 | `handoff/UNIT-05.md`, `checks/web-consumer.mjs` | Mac 웹 전체·웹 manifest/lockfile·PDF/필기 표시와 Tutor 소비 검증. |
| UNIT-06 | `handoff/UNIT-06.md`, `checks/requirements.txt`, `checks/validate_contracts.py`, `checks/ipad-consumer.swift` | 환경·CI·통합 검사·backend manifest/lockfile. Swift 파일은 제품 Reader가 아닌 공유 fixture 통합 검사다. |
| 통합 담당 | `AGENTS.md`, `README.md`, `.gitignore`, `.gitattributes`, `docs/*.md`, `contracts/**`, `integration/**`의 정확한 파일 목록 | 계약과 fixture, 공통 서버 assembly/등록, 부트스트랩 이후 지침과 최종 통합 브랜치. |

`integration/ownership.json`이 위 문서보다 세밀한 현재 판정 기준이다. 스크립트/문서의 신규 파일은 통합 담당이 먼저 배정한다.

## 아직 배정할 수 없는 실제 제품 경로

Pumice/DeepTutor 파일이 없으므로 제품 경로를 꾸며 넣지 않았다. 여섯 `handoff/UNIT-XX.md`는 실제로 존재하는 준비 문서이며 제품 구현 디렉터리가 아니다. 여섯 유닛의 **제품 수정 가능 경로는 현재 모두 빈 목록**이다. 제품 작업을 시작하면 안 된다.

소스 연결 후 통합 담당은 아래 경계에 실제 파일을 1:1 배정하고 registry의 `source_paths`를 갱신한다. source path에 디렉터리를 쓰더라도 상위 wildcard가 다른 유닛을 덮지 않아야 한다. `OWNERSHIP.md` 표도 실제 파일 경로로 교체한다.

- UNIT-01: ingest/library/search/citation verification, blob/DB repository, migration 파일 전부.
- UNIT-02: Tutor/learning capability/runtime/router 서비스 파일. 공통 assembly는 제외.
- UNIT-03: PDF/Pencil/geometry/Reader facade/local persistence 파일. 네트워크·app root·Xcode 파일 제외.
- UNIT-04: iPad screens/network/sync coordinator/app root/Xcode 프로젝트 파일.
- UNIT-05: 실제 web root 및 web manifest/lockfile 전부. web runtime 등록도 이 유닛.
- UNIT-06: scripts/deployment/Docker/Compose/CI/backend manifest/lockfile. 제품 router나 계약 파일 제외.
- 통합 담당: 실제 server assembly, service container와 router 연결, 계약 bundle, 공통 AGENTS.

한 파일에 경계가 섞인 경우 기존 구조를 이해한 뒤 최소 adapter 파일을 추가하고 원래 파일의 소유자는 하나만 둔다. 공통 migration, app 진입점, manifest 등을 여러 유닛에 동시에 맡기지 않는다.
