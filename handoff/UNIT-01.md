# UNIT-01 인수 경계

담당: Library·파싱/색인·검색/인용·sidecar sync·서버 DB/migration. 공통 시작 tag `mnemosyne-bootstrap-v0.1.0`, 계약 `0.1.0`.

실제 등록 경로: `upstreams/DeepTutor/deeptutor/mnemosyne/library.py` · `register_library`. docs/INTEGRATION.md의 signature와 callers를 읽는다.

UUID document↔native material/revision 매핑과 full SHA 원본 version; partial span/quad 검증; immutable original; mutation/receipt/log/cursor를 같은 transaction으로; 기존 learning/session storage도 이 유닛이 migration. 기존 hard delete JSON을 sync 구현으로 보고하지 않는다.

현재 common seam/fixture가 있다는 것은 제품 구현 완료가 아니다. 빈 port를 success/no-op으로 채우지 않는다. 필수 기능은 모두 이번 범위다.

정확한 수정 가능 파일 329개는 integration/ownership.json의 owners.UNIT-01 배열이다. 주요 directory는 OWNERSHIP.md 참조. 다른 소유자의 공통 startup/계약/DB/manifest 파일을 편집하지 않는다.

새 계약 변경은 소비자 영향·version·fixture·검증 변경을 포함해 통합 담당에게 제안한다. DB 요구는 schema/migration/transaction/검증 명세로 01에 전달한다. 사용자 지시 없이 다른 채팅에 메시지를 보내지 않는다.

인수 결과는 실행한 명령·실제 source/service/build/device 종류·실패/차단을 구별하고 기록한다. 공통 fixture PASS를 제품 오프라인/LLM/기기 검증으로 대체하지 않는다. 원본 hash, 잘못된 인용 거부, replay/cancel/error와 재시작 저장을 실제 경계에서 확인한다.

## 2026-10-09 구현 인수 및 통합 요청

### Unit 01 서비스 구현

- `library.py`는 `ReadingStore`와 PyMuPDF를 통해 PDF를 ingest하고, Mnemosyne 전용 SQLite에 UUID↔DeepTutor material ID, 전체 SHA-256 version, parser page/geometry, 추출 이미지, annotation snapshot/log, 멱등 receipt, cursor, citation verification, export 상태를 보관한다. 원본은 별도 content-addressed 경로에 읽기 전용 권한으로 저장하고 다운로드 때마다 전체 hash를 확인한다.
- 업로드 시 DeepTutor의 16자리 material ID가 전체 원본 SHA-256과 일치하는지 확인한다. partial parse/media 실패에서는 실패 페이지·asset을 지우고 원본과 failed 상태는 유지한다. parser 실패 뒤 부분 page를 반환하지 않는다.
- annotation sync는 SQLite write transaction에서 conflict, tombstone, mutation-ID 재사용, idempotency receipt와 server revision을 처리한다. `1`과 `1.0`처럼 수학적으로 같은 유한 JSON 수치는 replay에서 같은 payload로 취급한다. PDF export는 별도 파생 파일을 생성하고 원본을 유지한다.
- `DocumentRepositoryAdapter`는 UNIT-02 ports의 document/page/asset 메서드를 제공한다. `build_library_router(library)`에는 문서·과목·원본 다운로드·page/search/citation·annotation sync·export 및 `GET/PUT /v1/settings`를 둔다. Router를 shared `main.py`에 직접 연결하지 않았다.
- provider 설정은 공개 adapter/base URL/model/응답 언어와 credential 존재 여부만 DB에 저장한다. API key는 쓰기 시 주입된 secret writer로 전달하고 SQLite 응답·행에 기록하지 않는다. 기본 provider 값과 secret 저장소는 통합에서 주입해야 한다.

### 통합 담당이 연결할 항목

1. `register_mnemosyne`/container 조립에서 `register_library`에 `rag_indexer`, `rag_search`, `settings_defaults_provider`, `settings_secret_writer`, `settings_credential_reader`를 전달한다. 현재 bootstrap caller는 `store`와 `annotation_sync`만 넘기므로 Tutor RAG와 설정 callback이 아직 제품 실행 경로에 연결되지 않았다. 안전한 callback 소유자는 UNIT-02/통합 담당이 정하고 API key는 UNIT-02의 서버 secret 저장소에 둔다.
2. `app.include_router(build_library_router(services.library))`로 router를 등록하되 pairing bearer 인증, Origin 검사, request ID 정책, rate/size 보호 뒤에 둔다. 이 router 자체는 인증 middleware를 설치하지 않으므로 단독 배포 경계가 아니다.
3. Unit 01 테스트 변경 중 `upstreams/DeepTutor/tests/reading/test_ingestion.py`는 upstream snapshot의 원래 tracked 파일이다. 통합 담당이 `integration/upstreams.json`의 SHA/수정 예외를 갱신하고 provenance 검사를 확인해야 한다. Unit 01은 통합 소유 파일을 편집하지 않았다.

### 계약 `0.1.0`으로 표현할 수 없는 범위

- `Annotation.kind`에는 `ai_annotation`이 없어 AI annotation을 현재 wire shape로 저장하지 않는다. 다음 계약 버전에서 kind 및 payload(`verified TextAnchor`, 생성 문장, provider/model provenance)를 정의하고 annotation fixture, Pumice/웹 소비자와 검증기를 함께 갱신해야 한다.
- `Document.page_count`는 최소 1이지만 parser가 페이지 수를 구하지 못한 failed 업로드는 DB 값이 0이다. 사실을 꾸며내지 않으려면 다음 계약에서 실패 상태의 `page_count: null` 또는 동등한 명시적 unknown 표현을 허용하고 consumers/fixtures를 수정해야 한다.
- 외부 `DocumentRepositoryAdapter.get_asset`는 내부 호출용이고 OpenAPI에는 image asset 다운로드 경로가 없다. 웹/외부 client가 그림을 직접 읽어야 한다면 문서-version 검증, MIME/hash 응답을 포함한 asset route를 계약에 추가해야 한다.
- 폴더는 현재 DeepTutor `ReadingCatalogStore` workspace를 재사용하지만 Mnemosyne OpenAPI에는 folder endpoint가 없다. 현재 외부 API가 보장하는 Library 분류는 과목이다.

계약 변경 제안은 통합 담당이 version `0.2.0`과 소비자 영향/fixture/검증을 함께 처리한다. `contracts/`와 upstream의 `MnemosyneContracts` 생성 복사본은 Unit 01이 수정하지 않았다.

### 검증

- 실행: `PYTHONPATH=/private/tmp/mnemosyne-unit01-deps:. /opt/homebrew/opt/python@3.14/bin/python3.14 -m pytest --confcutdir=tests/reading -q tests/reading/test_ingestion.py::test_mnemosyne_pdf_upload_annotation_sync_restart_and_export tests/reading/test_ingestion.py::test_library_http_router_settings_and_pdf_round_trip` (`upstreams/DeepTutor` 기준): **2 passed, 6 warnings**. 경고는 PyMuPDF SWIG 타입의 `__module__` deprecation 경고다. 중간 실행은 FastAPI가 lazy `Request` annotation을 query parameter로 오인해 실패했으며, router factory의 runtime annotation binding 후 통과했다.
- fixture는 지정 `contracts/fixtures/bilingual-geometry.pdf`다. 이는 Mac host의 로컬 PDF/SQLite/API TestClient 검증이며 Docker/server process, 실제 LLM/RAG provider, iPad/Mac 브라우저 제품 UI, offline device flow 검증이 아니다.
- 임시 테스트 의존성은 `/private/tmp/mnemosyne-unit01-deps`에 설치했다. 저장소의 backend/web 의존성 파일은 수정하지 않았다.
