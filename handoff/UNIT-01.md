# UNIT-01 인수 경계

담당: Library·파싱/색인·검색/인용·sidecar sync·서버 DB/migration. 공통 시작 tag `mnemosyne-bootstrap-v0.1.0`, 계약 `0.1.0`. 이 handoff는 유닛 결과와 통합 차단 항목을 구분한다. 제품 전체 준비 완료를 뜻하지 않는다.

이 handoff는 소유권 표준 경로 `handoff/UNIT-01.md`와 목표가 지정한 `docs/handoffs/unit-01.md`에 같은 내용으로 보관한다.

실제 등록 함수: `upstreams/DeepTutor/deeptutor/mnemosyne/library.py`의 `register_library`. 공유 조립 함수 `register_mnemosyne`, container, API main, ports, contracts, checks, dependency 파일은 통합/다른 유닛 소유이며 Unit01이 수정하지 않았다.

## 구현된 Unit01 경계

- `LibraryAdapter`는 지정 DeepTutor `ReadingStore`/`ReadingCatalogStore`와 PyMuPDF를 재사용한다. UUID document와 material ID, 전체 SHA-256 version, 페이지 text/geometry, 추출 image bytes/hash, 과목, workspace 기반 folder 관계, metadata revision, parse/index 상태를 유지한다. PDF 원본은 content-addressed 파일로 별도 보관하고 읽기 전용으로 만든다. DB, WAL/SHM은 `0600`, 전용 asset/export 디렉터리는 `0700` 권한을 적용한다. DB schema migration은 version 3이며 기존 version 2에 `index_started_at`을 추가한다.
- 업로드는 PDF magic/크기/파일명/언어/과목을 검증하고 DeepTutor의 content ID와 원본 전체 hash를 대조한다. 원본 경로 밖의 쓰기는 허용하지 않는다. `upload_pdf`는 로컬 parse 경계이고 성공한 뒤 index 상태를 `pending`으로 남긴다. HTTP 업로드는 `upload_pdf_async`로 parse 후 `prepare_index`를 시도한다. callback이 주어지면 주입된 RAG indexer를 사용하고, 없으면 지정 DeepTutor의 knowledge-base initializer를 호출한다. 미설정 provider와 실패/취소/30분 이상 응답 없는 index run은 성공으로 가장하지 않고 오류 상태로 남긴다.
- 문서 목록·조회·수정·확인 헤더를 요구하는 삭제, 과목 CRUD, 페이지/search/citation 검증, 원본 다운로드/hash 재검증, annotation snapshot/change/mutation/cursor, highlight/note/bookmark/ink export, provider 설정 기반을 제공한다. annotation 입력은 page/anchor/geometry와 숫자 유효성을 확인하며 JSON 모양이 잘못된 mutation은 `invalid_request`로 거절한다. 원본 수정 내보내기와 별개다.
- `DocumentRepositoryAdapter`는 `get_document`, `get_page`, `get_page_assets`, `get_asset`을 제공한다. 이미지 인덱스는 페이지별 asset ID/MIME/hash를 돌려주고 byte 접근 때 hash를 재검증한다. 기존 `ports.py`에는 `get_page_assets` 선언이 없어 Protocol 추가가 필요하다.
- `LibraryAdapter.create_folder/list_folders/assign_folder/remove_from_folder`는 지정 DeepTutor `ReadingCatalogStore` workspace 저장소를 재사용한다. 이름/설명 입력을 검증하고 500개 단위로 페이지를 순회해 폴더 목록을 반환한다. 현재 계약의 HTTP/OpenAPI에는 folder API가 없으므로 이 기능을 Mac/iPad에서 호출 가능한 제품 API로 보고하지 않는다.
- Settings API는 공개 adapter/base URL/model/언어/credential 존재 여부만 SQLite에 둔다. key는 주입된 secret writer로 보내고 응답/공개 행에 저장하지 않는다. provider URL은 URI 형식 검사 뒤 필수 `settings_base_url_validator` callback이 정확히 `True`를 반환해야 저장된다. allowlist와 서버 console에서 선택 허용한 loopback은 조립 담당이 정해야 한다.
- Citation verification은 10분 TTL을 검사하고 새 검증마다 만료 행을 정리한다. Annotation snapshot은 삭제 확인과 snapshot/cursor 발행을 writer transaction 안에서 수행한다.
- `build_library_router(library)`는 계약 0.1.0 HTTP facade를 만들지만 router를 공통 `main.py`에 직접 등록하거나 pairing bearer/Origin 정책을 설치하지 않는다. 단독 배포 경계가 아니다.

## 통합 담당이 적용할 정확한 변경

1. **서비스 조립과 HTTP 보호** — 통합 소유 `upstreams/DeepTutor/deeptutor/mnemosyne/bootstrap.py::register_mnemosyne`, `deeptutor/app/container.py`, `deeptutor/api/main.py`에서 `register_library`에 다음 선택 인자를 전달한다: `rag_indexer`, `rag_search`, `settings_defaults_provider`, `settings_secret_writer`, `settings_credential_reader`, `settings_base_url_validator`. `settings_base_url_validator(url) -> bool`은 동기 callback이며 allowlist/정책 통과만 `True`여야 한다. 설정/비밀 저장소의 실제 소유자와 안전한 RAG provider 설정을 정한다. `app.include_router(build_library_router(services.library))`는 pairing bearer, 정확한 Origin 검사, request ID, 업로드 용량 보호가 있는 조립 뒤에 등록한다. 현재 bootstrap은 `store`/`annotation_sync`만 전달하고 router를 mount하지 않는다.

2. **DocumentRepository port 확장** — 통합 소유 `upstreams/DeepTutor/deeptutor/mnemosyne/ports.py::DocumentRepository`에 다음 메서드를 추가하고 UNIT-02 Tutor adapter/consumer를 갱신한다. `asset` 목록은 OS 경로 없이 `asset_id`, `page_index`, `mime`, `sha256`만 돌려준다.

   ```python
   async def get_page_assets(
       self, document_id: str, version_id: str, page_index: int
   ) -> list[dict[str, Any]]: ...
   ```

3. **페이지 그림 외부 API** — `contracts/openapi.yaml`은 기존 `GET /v1/documents/{document_id}/pages/{page_index}` 외에 asset 경로를 정의하지 않는다. 계약 `0.2.0` 변경 승인 시 다음 두 동작을 추가한다.

   - `GET /v1/documents/{document_id}/pages/{page_index}/assets?version_id=...`: 해당 page/version에 연결된 `{asset_id,page_index,mime,sha256}` 배열을 반환한다.
   - `GET /v1/documents/{document_id}/assets/{asset_id}?version_id=...`: document/version/asset 관계를 검증하고 bytes를 반환한다. 응답 `Content-Type`은 저장 MIME, `ETag` 또는 명시 응답 메타데이터는 SHA-256을 사용한다. 경로/저장소 경로는 응답하지 않는다.

   같은 version을 대상으로 `DocumentRepositoryAdapter.get_page_assets/get_asset`은 이미 구현돼 있다. HTTP binding과 계약은 통합 담당이 소유한다.

4. **계약 0.2.0 — AI Annotation** — 현재 `contracts/annotations.schema.json`의 enum은 `highlight`, `note`, `bookmark`, `ink` 네 종류다. 다음 payload를 제안한다. 실제 생성 문구, 검증된 source anchor, 비밀이 아닌 provider/model provenance를 저장한다. API key는 기록하지 않는다.

   ```json
   {
     "type": "object",
     "properties": {
       "anchor": {"$ref": "models.schema.json#/$defs/TextAnchor"},
       "body": {"type": "string", "minLength": 1, "maxLength": 20000},
       "provider": {"type": "string", "minLength": 1, "maxLength": 100},
       "model": {"type": "string", "minLength": 1, "maxLength": 200},
       "source_turn_id": {"anyOf": [{"type": "string", "maxLength": 256}, {"type": "null"}]}
     },
     "required": ["anchor", "body", "provider", "model", "source_turn_id"],
     "additionalProperties": false
   }
   ```

   `contracts/annotations.schema.json`에서 `AIAnnotationPayload` 정의를 추가하고 AnnotationDraft 및 live/tombstone AnnotationRecord의 세 kind enum, 각 payload `oneOf`, live record의 kind→payload `allOf` 조건을 함께 확장한다. 서버 `_ANNOTATION_KINDS`와 `_validate_draft`를 같은 payload로 확장한다. `x-contract-version`, OpenAPI 버전/header, `contracts/manifest.json`, `contracts/fixtures/study-session.json`과 fixture README를 0.2.0으로 갱신한다. 생성 복사본은 통합 담당이 동기화한다: `upstreams/Pumice/MnemosyneContracts/`와 `upstreams/DeepTutor/MnemosyneContracts/`. 검증기/소비자도 갱신한다: `checks/validate_contracts.py`, `checks/web-consumer.mjs`, `checks/ipad-consumer.swift`; 해당 유닛 구현 소비자는 각 소유자에게 schema 변경을 전달한다. 확인된 현 fixture consumer는 네 kind를 명시적으로 비교하므로 그대로 두면 새 fixture에서 실패한다.

5. **계약 0.2.0 — parser가 모르는 page_count** — `contracts/models.schema.json`의 `Document.page_count`는 현재 최소 1인 정수지만 실제 parser 실패 시 내부 DB는 0을 저장한다. 숫자를 꾸미지 않는 제안은 non-ready 상태의 wire `page_count: null`, `parse_state: ready`의 wire `page_count >= 1`이다. DB의 내부 0 sentinel은 유지할 수 있고 `get_document` DTO만 비준비 상태를 null로 매핑한다. Document schema에 `anyOf`와 `parse_state` conditional을 넣고 `contracts/fixtures/study-session.json`, OpenAPI, Python/TS/Swift 소비 타입/negative checks를 같이 갱신한다. `checks/ipad-consumer.swift::Document.page_count`는 현재 non-null `Int`이므로 변경 대상으로 확인됐다.

6. **계약 0.2.0 — 폴더 API** — 현재 내부 구현은 workspace id를 folder id로, workspace `title`을 사용자 표시명으로 대응한다. upstream 응답의 `material_id`를 새 공개 API에 그대로 노출하지 말고 Mnemosyne document UUID로 정규화한다. 제안 DTO는 `Folder {folder_id: uuid, name: string, description: string, document_ids: uuid[]}`이다. `contracts/models.schema.json`에 schema를 추가하고 OpenAPI에 `GET /v1/folders`, `POST /v1/folders` (`{name,description}`), `PUT /v1/folders/{folder_id}/documents/{document_id}?version_id=...`, `DELETE` 동일 경로를 정의한다. 각 관계 변경은 문서/version/folder 존재를 검증하며, Folder/assignment 응답은 workspace tabs를 document UUID로 변환한다. 폴더 자체 delete나 동시 수정 ETag를 원하면 storage revision/transaction 계약도 같은 변경에서 명시한다. fixture와 `checks/validate_contracts.py`, web/iPad 소비자까지 함께 바꾼다.

7. **upstream 출처 예외** — Unit01이 변경한 tracked fixture test `upstreams/DeepTutor/tests/reading/test_ingestion.py`는 `integration/upstreams.json`에 원래 SHA `8878f4000c042d9480289c1a2823d56db09630eb4776d437ed29498d808fad23`, 원래 git blob `b44b1ed3d358e8b44546e728729d282e21e33c17`로 등록돼 있다. 현재 파일 SHA-256은 `b3a909c74be29aa442708ec8636ed24b3270671c9bd8f928ec74a9178beb95d7`다. 통합 담당은 SHA를 갱신하고 원 upstream commit/blob provenance를 유지하면서 Unit01 fixture 변경 예외를 기록한 뒤 source/provenance 검사를 실행한다. `integration/upstreams.json`은 Unit01 수정 권한 밖이라 여기서는 갱신하지 않았다.

### 실제 로컬 통합 브랜치 확인 (2026-10-09)

- `codex/unit-05-api-integration` (`b1a8224c91118b8d11edfdf5b785c8207b902b5f`)에는 `build_library_router` 구현과 router 단독 TestClient 검사가 있지만 `deeptutor/api/main.py`, `mnemosyne/bootstrap.py` 어디에도 mount가 없다.
- `codex/unit-06-cloud-runtime` (`470a01f2e4bcccdbfdb725bea65526dc32731ec2`)도 `build_library_router`를 제품 main에 mount하지 않는다. 이 브랜치의 `register_mnemosyne`는 `register_library`에 store/annotation_sync만 전달하고 `ports.py::DocumentRepository`에는 `get_page_assets`가 없다.
- 현재 Unit06 checkout의 미커밋 `tutor.py`는 학습 상태와 citation DTO를 검증하지만 document search/page/asset/citation verification을 호출하지 않는다. 미커밋 `library.py`와 `test_ingestion.py`도 같은 Unit01 경로를 수정한다. 이 library diff는 Unit01의 DB 권한/schema v3 및 index watchdog, provider URL policy callback, page asset repository adapter, upload indexing wrapper, 폴더 입력 검증/pagination 등 일부 hardening을 제거하므로 통합 시 dirty copy로 파일 전체를 덮어쓰지 말고 항목별로 reconcile한다.
- 두 branch tip 모두 계약 0.1.0과 준비 gate를 바꾸지 않는다. root main checkout의 미커밋 파일은 이 Unit01 작업에 복사하거나 병합하지 않았다. Remote가 없어 PR도 만들지 않았다.

## 검증 결과와 남은 검증

`upstreams/DeepTutor` 기준으로 다음 선택 fixture 검사 7개를 실행했다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/mnemosyne-unit01-deps:. \
  /opt/homebrew/opt/python@3.14/bin/python3.14 -m pytest \
  --confcutdir=tests/reading -q -p no:cacheprovider \
  tests/reading/test_ingestion.py::test_mnemosyne_pdf_upload_annotation_sync_restart_and_export \
  tests/reading/test_ingestion.py::test_library_http_router_settings_and_pdf_round_trip \
  tests/reading/test_ingestion.py::test_library_parser_unavailable_preserves_original_pdf \
  tests/reading/test_ingestion.py::test_library_indexer_requires_explicit_ready_result \
  tests/reading/test_ingestion.py::test_library_pdf_image_assets_are_listable_and_hash_checked \
  tests/reading/test_ingestion.py::test_library_schema_v2_database_migrates_index_run_timestamp \
  tests/reading/test_ingestion.py::test_library_folder_listing_paginates_and_rejects_empty_names
```

결과: **7 passed, 6 warnings**. 경고 6개는 PyMuPDF SWIG 타입의 `__module__` deprecation이다. 검사는 지정 `contracts/fixtures/bilingual-geometry.pdf` 업로드·원본 hash/권한·페이지 회전/CropBox·인용·주석 CRUD/conflict/replay/idempotency mismatch/tombstone/stale edit-delete 충돌/cursor expiry/재시작/export, citation verification 성공과 위조 anchor 거부, HTTP TestClient 설정/PDF 왕복/citation route, parser 불가 때 failed 상태 및 원본 읽기 보존, indexer의 no-op/invalid success 거부, 합성 embedded raster의 페이지 mapping/hash, schema v2 DB migration, 폴더 입력검증과 500개 초과 pagination을 다룬다. positive citation 검사를 처음 추가했을 때 parse_revision 지정 page 조회의 SQL binding 누락이 발견되어 `(document_id, version_id, page_index, parse_revision)` 전체를 바인딩하도록 수정했다. 이후 7개 fixture 테스트가 통과했다. RAG provider 연결 자체는 실패 callback fixture로만 확인했다. `git diff --check`도 통과했다.

아직 실행하지 않은 검증: 전체 DeepTutor suite/build, contract manifest/source check(통합이 upstream SHA 예외를 반영한 뒤 필요), 실제 main/router 조립과 auth/Origin, 실제 RAG/LLM provider·Windows WSL2/Docker 운영, 브라우저 UI, Pumice 빌드 및 실제 iPad/offline/Pencil. registry의 `product_ready=false`, `cloud_repository_access=local_only_no_origin`은 현재도 그대로다. 공통 router/계약/보호/실기기 검증이 끝나기 전 제품 기능 완료로 보고하지 않는다.

### Adapter 소비 및 indexer 응답 계약 확인

- UNIT-06 `tutor.py`는 `library.annotation_sync` readiness만 확인하며 문서 검색/페이지/그림/citation 메서드는 호출하지 않는다. UNIT-02는 `library`를 `DocumentSearch`로, `library.documents`를 `DocumentRepository`로 in-process 소비하도록 연결해야 한다. `ports.py::DocumentRepository`의 `get_page_assets` 선언도 추가 대상이다.
- 주입 `rag_indexer(document, original_path, kb_name)`은 동기/비동기 가능하며 명시적으로 `True` 또는 `{"ready": true, "kb_name": "..."}`를 반환해야 한다. `None`, 빈 object, 거짓 readiness 또는 빈 KB 이름은 ready로 처리하지 않는다. 실제 DeepTutor provider 호출은 미검증이다.
