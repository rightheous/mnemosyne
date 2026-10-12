# UNIT-04 연결 요청

작성 기준: `mnemosyne-bootstrap-v0.1.0` (`5715a32927e3a73dc28782d306880e3dd1f62441`), 계약 `0.1.0`. 이 문서는 구현 담당에게 보낼 요청이며 공통 계약이나 다른 담당 파일을 수정하지 않는다.

## UNIT-03 Reader facade 요청

현재 `MnemosyneReaderFacade`에는 앱이 PDF 화면을 표시할 수 있는 durable 원본 URL/presentation API가 없다. `openCached(documentID:versionID:)`는 `Void`를 반환하고 `installDownloadedOriginal`도 설치 위치를 반환하지 않는다. UNIT-04가 기존 `PDFReaderView`에 전달할 검증된 로컬 파일 URL을 얻을 수 없다. Pumice의 현 `PDFReaderViewController`는 PDF 입력 파일을 직접 다시 쓰므로 UNIT-03의 immutable-original 수정 전에는 화면에 연결하면 안 된다.

`openCached` 반환 URL은 아래 cache API와 동일한 verified durable original이어야 합니다. UNIT-04는 반환 URL만 `PDFReaderView`에 전달하고 page callback/context 저장은 facade API를 통합니다. 원본에 Pencil/주석을 쓰지 않고 sidecar에 저장해야 합니다.

sync worker에는 아래 read/apply 경계가 추가로 필요합니다.

- 오프라인 Library에는 서버 목록이 없으므로 `cachedDocuments() throws -> [Data]`를 제공해 주세요. 각 Data는 계약 `Document` DTO 또는 document/version/title/page_count/source_sha256가 포함된 동일 계약 envelope여야 합니다. `cached` 레코드는 durable PDF의 전체 원본 SHA-256 검증이 끝난 문서만 반환하고 hash가 맞지 않는 항목은 cached로 노출하지 않습니다.
- `openCached(documentID:versionID:)`가 현재 PDF에 연결되는 URL을 반환하도록 바꾸거나 별도 `cachedOriginalURL(documentID:versionID:) throws -> URL?`을 추가해 주세요. 화면 재표시/회전에도 같은 version과 page context를 유지해야 합니다.
- `syncCursor(documentID:versionID:) throws -> String?`: 현재 version의 opaque 서버 cursor를 읽습니다.
- `applyRemoteSnapshot(_ snapshot: Data) throws`: 최초 snapshot의 annotations와 cursor를 pending outbox를 보존하며 원자 적용합니다.
- 기존 `applyRemotePage(_:)`는 changes와 다음 cursor를 같은 로컬 transaction에 적용합니다.
- 기존 `pendingMutations(limit:)` 각 Data에는 document/version 및 안정된 `client_mutation_id`가 있어야 합니다. `applySyncReceipts(_:)` 성공 receipt만 해당 pending mutation을 해소합니다.

Tutor reconnect에는 native frame sequence의 durable checkpoint가 필요합니다.

- `lastTutorSequence(turnID:) throws -> Int`와 `commitTutorFrame(_ nativeFrame: Data) throws`를 제공해 주세요.
- `commitTutorFrame`은 native frame의 turn ID/seq를 중복 검증하고 semantic event ID를 보관해야 합니다. 확장 없는 native progress frame도 checkpoint합니다.
- `applyReaderEvent(_:)`는 event ID에 대해 멱등이어야 합니다. `reader.annotate`는 사용자 승인 뒤에만 outbox에 한 번 기록되어야 합니다.

소비자는 UNIT-04 API client, sync worker, Tutor transport이며, fixture 기대값/재시작·중복·취소 검증은 현재 UNIT-04 소유 테스트 파일 `Tests/PumiceUITests/PumiceUITests.swift`에 추가했습니다. Reader DB 구현은 UNIT-03 소유이므로 UNIT-04가 그 파일이나 저장소를 직접 편집하지 않습니다.

## UNIT-03 App 등록 및 PDF 화면 연결 요청

현재 앱 모델은 `attachReader(_:syncWorker:)`를 제공하지만 `PumiceApp`에서 호출하는 실제 facade/localStore factory가 없습니다. 따라서 PDF 열기, offline cache 목록, sidecar 필기, cursor 기반 동기화와 Tutor 시작은 UI에서 성공한 것처럼 보이지 않도록 대기 상태로 남겨 두었습니다.

- PumiceCore가 실제 `MnemosyneLocalStore`와 `MnemosyneReaderFacade` 구현을 제공하고 App에서 호출 가능한 factory를 노출해 주세요. `PumiceApp` 시작 시 이를 조립하고 앱 모델에 주입하는 정확한 signature도 합의해야 합니다.
- `openCached`가 현재 검증된 durable original URL을 반환하거나 `cachedOriginalURL(documentID:versionID:)`을 제공해 주세요. App은 그 URL만 기존 `PDFReaderView`에 전달하고 현재 page/selection callback은 facade의 `readerContext()`에 저장합니다.
- Reader 이벤트가 현재 페이지를 이동시키면 facade가 직전 `ReaderContext`를 보존하고 `restoreReaderContext(_:)` 또는 동등한 back-navigation API로 복원할 수 있게 해 주세요. App은 임의의 synthetic Reader event를 만들지 않습니다.
- Tutor panel은 연결된 Reader context로 typed `start_turn` command를 만들고 취소·재시작 후 저장된 sequence로 재개할 수 있어야 합니다. 서버 문서 UUID/version을 native internal material ID로 resolve하는 계약 제안과 함께 연결해 주세요.

UNIT-04 코드는 `PumiceApp.swift`, `MnemosyneAppDependencies.swift`, `LaunchView.swift`, `MnemosyneTurnWire.swift`, `PumiceUITests.swift`처럼 `integration/ownership.json`에 이미 할당된 경로에만 두었습니다. 이 요청 메모 `docs/handoffs/unit-04.md`는 사용자가 요청한 별도 handoff 경로이나 아직 ownership registry에 없습니다. 공통 검증을 통과시키려면 integrator가 이 경로를 소유자 할당에 등록해야 하며 UNIT-04가 `integration/ownership.json`을 직접 수정하지 않습니다.

## 통합 담당 / UNIT-02 Tutor 시작 요청

현재 계약 `contracts/openapi.yaml`에는 `GET /v1/tutor/turns/{turn_id}`만 있고 turn 생성 route는 없습니다. 외부 스트림은 `docs/INTEGRATION.md` 결정대로 native `/ws` protocol 2.0이어야 합니다. native `start_turn.reading_material_id`는 DeepTutor 내부 opaque material ID이고, UNIT-02 `native_turn_request`는 `reading` 요청 때 서버가 해석한 material ID와 revision을 인자로 요구합니다. 이 값은 서버 소유이며 클라이언트 `Document` DTO에 공개되지 않습니다.

현재 contract `TurnRequest`는 `reader_context`를 포함하지만 그 request를 받는 OpenAPI operation은 없습니다. contract의 다음 버전에서 인증된 `POST /v1/tutor/turns` (`TurnRequest` → `TurnReceipt`)를 정의하고, server handler가 `DocumentRepositoryAdapter`로 document UUID/version을 확인해 material ID/revision으로 해석한 뒤 UNIT-02 `TutorAdapter.start_turn`에 전달해 주세요. receipt를 받은 iPad는 native `/ws`의 `resume_from(turn_id, seq)`를 사용해 저장된 sequence 이후까지 구독합니다.

요청 body는 기존 `TurnRequest`/`ReaderContext` schema를 따릅니다.

```json
{
  "client_mutation_id": "<UUID>",
  "capability": "reading",
  "message": "이 페이지의 핵심 내용을 설명해 주세요.",
  "reader_context": {
    "document_id": "<UUID>",
    "version_id": "sha256:<64 lowercase hex>",
    "page_index": 0,
    "viewport_rect": [0, 0, 1, 1],
    "selection": null,
    "content_language": "und",
    "response_language": "ko"
  },
  "response_language": "ko"
}
```

`selection_tutor_context`는 UNIT-02 소스의 기존 선택 텍스트 대화 기능(parent session/message ID)이며 Mnemosyne `ReaderContext`가 아닙니다. 두 context를 혼용하지 마세요. 서버는 현재 페이지/선택 anchor를 document version 및 citation service로 검증하고, 화면에 근거를 생성해 넣지 않습니다. UNIT-02 capability mapping은 `chat→chat`, `reading→immersive_reading`, `quiz→deep_question`, `mastery→mastery_path`, `solve→deep_solve`입니다. `assessment`, `memory`, `progress`, `review`는 learning service route를 사용하며 fabricated native capability로 시작하지 않습니다.

같은 contract 변경에서 Quiz question hint operation도 정의해 주세요. 현재 `Question` schema에는 hint 필드/route가 없어 UI가 정답을 가리지 않는 서버 hint를 요청할 수 없습니다. 제안 operation은 `POST /v1/quizzes/{quiz_id}/questions/{question_id}/hint`; response는 `contract_version`, `quiz_id`, `question_id`, `document_id`, `version_id`, `hint_ko`, verified `citations`를 포함하고 정답/비공개 채점 기준은 내보내지 않아야 합니다.

계약 편집자는 integrator만입니다. `TurnRequest` operation과 Hint response를 추가한다면 계약 버전(제안 `0.2.0`), iPad/web/server 소비자, 양쪽 `MnemosyneContracts` 생성 복사본, fixture, 검증기 및 manifest digest를 함께 갱신해 주세요. native-turn schema는 upstream byte-identical copy이므로 UNIT-04에서 직접 수정하지 않습니다.

## 현재 보이는 server commit과 실제 연결 상태

- `a0aad86676cac74fa13530f3b1aed33cc10ad354` (`codex/unit-01-library-sync`)에는 `build_library_router`와 문서·원본·annotation handler가 있습니다. 이 router는 `api/main.py`에 mount되지 않았고 auth/Origin guard도 router 자체에 없습니다.
- `17d6e6b5245758aa824589327d6b92b5bfa62035` (`codex/unit-06-cloud-runtime`)에는 UNIT-02 `TutorAdapter`/native mapping이 있습니다. `reader_context`를 처리하고 server-resolved material ID/revision을 요구하지만 authenticated iPad turn-creation HTTP route는 없습니다. `selection_tutor_context`는 다른 용도입니다.
- 현재 각각의 worktree는 이 SHA 이후 `library.py`/Tutor/WebSocket 및 ReaderFacade/PDFReader 파일이 수정된 dirty 상태입니다. `codex/unit-06-cloud-runtime`에는 UNIT-03 Reader 구현 작업본이 보이지만, 아직 전달된 clean commit/PR가 아니므로 UNIT-04 branch에 포함하거나 제품 연결 근거로 사용하지 않았습니다.
- 현재 보이는 UNIT-03 작업본에는 local-store `cachedOriginalURL`, `receivedCursor`, reader context 저장 API가 있지만 facade URL 전달, 오프라인 `cachedDocuments`, `syncCursor`/`applyRemoteSnapshot`, native frame `lastTutorSequence`/`commitTutorFrame`, page-restore 경계는 확인되지 않았습니다. 해당 작업의 공식 commit/PR가 제공되면 실제 signature를 다시 대조합니다.
- 이 commits/작업본은 UNIT-04 branch에 통합되지 않았고 통합 server process도 없어 Library→PDF→Tutor→Reader 이동은 확인할 수 없습니다. 별도 worktree의 fixture report를 제품/API 통합 검증으로 세지 않습니다.

## API 준비/실제 연결 구분

`/health`와 `/ready`만 감사에서 observed upstream입니다. contract의 `/v1/*` operation은 계획된 wire 계약이고, 별도 branch에 있는 Library router factory도 mounted API가 아닙니다. UNIT-04 client는 wire 계약 소비 코드이며 handler가 통합 server에 연결되기 전까지 제품 서버 연결 성공으로 표시하지 않습니다.

## UNIT-04 implementation checkpoint — 2026-10-09

이 checkpoint가 위의 이전 Reader 작업본/연결 상태를 갱신한다.

- UNIT-04 앱 composition은 `FileMnemosyneLocalStore`, `PersistentMnemosyneReaderFacade`, `PumiceReaderEngine`, `PDFReaderController`를 `makeIPadApp()`에서 실제 조립한다. Library workspace는 verified durable PDF URL을 `PDFReaderView`에 표시하고, Reader lifecycle에서 context를 저장한다. Pencil/annotation sidecar 저장은 UNIT-03 facade/engine 경계를 사용한다. Tutor `reader.annotate`는 facade의 `approveAnnotationSuggestion`을 거친 사용자 승인만 outbox에 저장한다.
- Sync worker는 pairing 뒤 시작하고 facade의 pending mutations, receipts, change pages와 cursor를 사용한다. Snapshot adapter는 snapshot을 Reader facade의 atomic change-page 입력으로 바꾸고, 사라진 server annotation에는 snapshot watermark tombstone을 만들어 pending local mutation을 보호한다. 이 adapter는 fixture/device runtime에서 아직 검증되지 않았다.
- Native turn checkpoint는 raw Tutor frame/text 대신 turn ID와 sequence만 저장한다. Semantic event를 처리한 뒤 sequence를 commit해 처리 실패 때 서버 replay를 받을 수 있게 했다.
- 의존 구현의 확인된 clean commit은 UNIT-03 `3a98ac43474722c98eded510ec6428f8329cd3d2` (offline Reader facade/Pencil), UNIT-01 `51d75c1` (Library/sync hardening), UNIT-02 `17d6e6b` (Tutor runtime)이다. 합쳐서 확인한 통합 복제본은 임시 경로 `/tmp/mnemosyne-unit04-integration-check`이다.

### 실제 검사 결과

- Swift 구문 파싱: UNIT-04 App/Network/UI test와 통합 복제본의 Reader/Core 소스에 대해 통과. `git diff --check` 통과.
- `checks/sync_contracts.py --check`: 계약 `0.1.0`, 두 생성 복사본, bundle 10개 통과.
- UNIT-01 최신 library fixture 5개 통과, 6개 PyMuPDF SWIG deprecation warnings.
- UNIT-02 mock provider fixture 110개 통과, 4 warnings.
- 통합 `checks/validate_contracts.py --require-ready`는 `docs/handoffs/unit-01.md`, `docs/handoffs/unit-04.md`가 `integration/ownership.json`에 미등록이라 실패했다. 두 문서는 요청된 handoff 산출물이지만 소유권 registry는 통합 담당이 갱신해야 한다. UNIT-04는 해당 registry를 수정하지 않았다.
- `xcodebuild -version`은 활성 개발자 디렉터리가 Command Line Tools라며 실패했다. Xcode 제품 빌드, UI XCTest, iPad simulator/Pencil/오프라인 기기 검증은 실행하지 않았다.

### 제품 통합 차단

- 병합된 clean server 소스에서도 `api/main.py`에는 `register_mnemosyne` state 등록만 보이고 `build_library_router` mount가 없다. `/v1/tutor/turns` 생성 operation도 없다. 그러므로 iPad의 planned `/v1/*` 호출, pairing 이후 library/sync, Tutor 생성→native `/ws` streaming은 실행 가능한 제품 API로 입증되지 않았다.
- 계약은 `0.1.0`, registry는 `product_ready: false`, `cloud_repository_access: local_only_no_origin`이다. authenticated tutor-turn create, quiz hint, API router mounting/auth/Origin, LearningStateStore 조립은 통합 담당/계약 담당의 후속 변경이 필요하다.
- Cloud 게시와 PR은 생성하지 않았다. 현재 결과는 UNIT-04 코드와 source/fixture 수준의 검증이며 전체 제품 완료가 아니다.
