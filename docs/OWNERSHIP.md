# 단독 수정 담당

계약 0.2.0. **integration/ownership.json의 정확한 파일 경로 목록**이 기계 판정 기준이다. 상위 디렉터리를 수정 가능 경로로 해석해 다른 소유 파일까지 편집하지 않는다. 모든 파일은 한 소유자다. 신규 파일도 통합 담당이 먼저 배정한다. `integration_exceptions`는 원소유자를 유지하면서 통합 연결에 필요한 범위만 명시한다. upstream LICENSE/NOTICE/개발 문서·정적 참고 자료는 보존한다.

| 담당 | 실제 주요 경로 / 경계 | 정확한 배정 수 |
|---|---|---|
| UNIT-01 | upstreams/DeepTutor/deeptutor/mnemosyne/library.py, reading/{store,extract,models,service,search,references,...}.py, knowledge/, services/{parsing,rag,storage}/; 서버 Library/기존 DeepTutor storage·DB·migration 파일 | 330 |
| UNIT-02 | upstreams/DeepTutor/deeptutor/mnemosyne/tutor.py; runtime/, agents/, capabilities/, services/llm/, learning/서비스, practice/서비스, api/routers/ (DB·공유 계약·main 제외) | 1739 |
| UNIT-03 | upstreams/Pumice/Sources/Reader/, Packages/PumiceCore/Sources/와 Tests/, Tests/PumiceTests/; geometry/Reader facade/local sidecar-outbox | 42 |
| UNIT-04 | upstreams/Pumice/App/, Sources/{Browser,Vault,Onboarding,Markdown,Extraction,Network}/; Config/, project.yml, Core Package.swift/Package.resolved, UI tests; screens/network/sync/Xcode | 83 |
| UNIT-05 | upstreams/DeepTutor/web/** 전체 (MnemosyneContracts 복사본은 제외); 웹 manifest/lockfile, app/features/components 및 checks/web-consumer.mjs | 1408 |
| UNIT-06 | checks/{validate_contracts,source_adapters}.py, ipad-consumer.swift, requirements.txt; DeepTutor scripts/, Docker/Compose/.github/, backend requirements/pyproject와 packaging; Pumice 자동화 scripts/fastlane | 77 |
| INTEGRATOR | 루트 docs/contracts/integration/AGENTS; deeptutor/api/main.py, app/container.py, api/contracts/, mnemosyne/{bootstrap,ports,__init__}.py; 동일 계약 생성 복사본과 checks/sync_contracts.py; 보존 reference/license/docs | 316 |

상세 DB/migration 목록은 ownership.json의 server_db_and_migration_files다. 예: learning/storage.py·migration.py, services/session/sqlite_store.py·legacy_migration.py, services/practice/storage.py, reading/store.py·catalog_store.py, services/workspace/data_migration.py. 원래 한 파일에 DB와 runtime이 섞인 경우에도 소유자는 01 한 명이다. 02는 서비스 요구 명세를 넘기고 그 파일을 직접 고치지 않는다. Shared container는 저장소를 조립하지만 schema를 정의하지 않으므로 통합 담당이다.

공통 startup/DTO/라우터 조립은 통합 담당, 각 unit의 register/facade 구현은 해당 unit이다. 통합 담당 소유의 `mnemosyne/learning_store.py`는 기존 Library 스토리지와 같은 개인 workspace 아래에 둔 Mnemosyne 퀴즈·평가·mastery·memory·progress DB 예외이며, 자체 SQLite schema version과 transaction을 가진다. UNIT-01의 ReadingStore/Library DB 소유 파일은 편집하지 않는다. `mnemosyne/quiz_generation.py`는 검증된 문서 페이지를 사용해 public Quiz와 private grading input을 분리 생성한다. `contracts/fixtures/{progress-mutation,quiz-generation-request}.json`은 공유 mutation/request 예시다. 두 fixture의 DeepTutor/Pumice 복사본도 원본과 함께 INTEGRATOR가 소유하며, contracts 복사본은 generator로만 갱신한다. 소유 목록에 없는 파일이나 다른 소유자의 manifest/DB/Xcode 파일은 먼저 명세를 전달한다.
