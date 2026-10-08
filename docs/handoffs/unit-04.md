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
- Tutor panel은 연결된 Reader context로 typed `start_turn` command를 만들고 취소·재시작 후 저장된 sequence로 재개할 수 있어야 합니다. 서버 문서 UUID/version을 native internal material ID로 resolve하는 계약 제안과 함께 연결해 주세요.

UNIT-04 코드는 `PumiceApp.swift`, `MnemosyneAppDependencies.swift`, `LaunchView.swift`, `MnemosyneTurnWire.swift`, `PumiceUITests.swift`처럼 `integration/ownership.json`에 이미 할당된 경로에만 두었습니다. 이 요청 메모 `docs/handoffs/unit-04.md`는 사용자가 요청한 별도 handoff 경로이나 아직 ownership registry에 없습니다. 공통 검증을 통과시키려면 integrator가 이 경로를 소유자 할당에 등록해야 하며 UNIT-04가 `integration/ownership.json`을 직접 수정하지 않습니다.

## 통합 담당 / UNIT-02 Tutor 시작 요청

현재 계약 `contracts/openapi.yaml`에는 `GET /v1/tutor/turns/{turn_id}`만 있고 turn 생성 route는 없습니다. 외부 스트림은 `docs/INTEGRATION.md` 결정대로 native `/ws` protocol 2.0이어야 합니다. 그러나 native `start_turn.reading_material_id`는 DeepTutor 내부 opaque material ID이며, 서버가 소유한 document UUID/full SHA-256 매핑은 클라이언트 `Document` DTO에 공개되지 않습니다. UNIT-02 `native_turn_request`도 해당 내부 ID/revision을 인자로 요구합니다. 따라서 iPad가 계약만으로 `start_turn`의 실제 문서 문맥을 만들 방법이 없습니다.

새 SSE/HTTP turn 생성 API를 추가하지 않고, `/ws` `start_turn.selection_tutor_context`에 전달할 typed Mnemosyne context를 정해 주세요. 제안 payload는 다음 필드입니다.

```json
{
  "contract_version": "0.1.0",
  "document_id": "<UUID>",
  "version_id": "sha256:<64 lowercase hex>",
  "page_index": 0,
  "viewport_rect": [0, 0, 1, 1],
  "selection": null,
  "content_language": "und",
  "response_language": "ko"
}
```

서버가 document UUID/version을 internal material ID/revision으로 resolve하고, `reading_context`/citation을 검증한 뒤 existing native turn service로 넘겨야 합니다. iPad는 응답의 quote·좌표를 자체 생성하지 않습니다. UNIT-02 capability mapping은 이미 `chat→chat`, `reading→immersive_reading`, `quiz→deep_question`, `mastery→mastery_path`, `solve→deep_solve`로 문서화돼 있습니다. `assessment`, `memory`, `progress`, `review`는 기존 `/v1` 상태 route를 사용하고 fabricated native capability로 시작하지 않습니다.

요청 소비자는 iPad transport와 web consumer입니다. 계약 편집자는 integrator만이며, context schema/fixture를 추가한다면 영향 받는 iPad·web·server consumer, 계약 버전, 양쪽 `MnemosyneContracts` 복사본, fixture 검사 및 manifest digest를 함께 갱신해 주세요. 현재 native-turn schema는 upstream byte-identical copy이므로 UNIT-04에서 직접 수정하지 않습니다.

## API 준비/실제 연결 구분

`/health`와 `/ready`만 감사에서 observed upstream입니다. `/v1/*` Library, pairing, file, annotation, learning, settings route는 contracts에 정의된 planned-unit-extension입니다. UNIT-04 client는 이 wire 계약 소비 코드이며 해당 handler가 통합 브랜치에 연결되기 전까지 서버 제품 연결 성공으로 표시하지 않습니다.
