# UNIT-03 인수: iPad PDF·Pencil·로컬 Reader

이 파일이 소유권 manifest의 canonical handoff 경로다. 요청에 적힌 docs/handoffs/unit-03.md는 현재 UNIT-03 소유 경로에 없어 여기에서 만들거나 수정하지 않았다.

담당 범위는 `integration/ownership.json`의 `owners.UNIT-03`에 맞춘다. 계약은 `0.1.0`이며 계약 원본/복사본, `Package.swift`, Xcode 설정은 수정하지 않았다. 기존 Pumice 소스 파일만 확장했으므로 새 XcodeGen 등록은 없다. `makeReaderFacade(factory, localStore)` 등록 경로와 빈 no-op 대체 금지 원칙을 유지한다.

## 구현

- `FileMnemosyneLocalStore`는 원본 PDF를 `sha256:<64자리>` 전체 해시로 확인한 뒤 주소화된 파일로 설치하고, 읽기 때도 해시를 다시 확인한다. 원본은 변경하지 않는다. context, annotation projection, mutation outbox, 승인 이벤트 ID, sync receipt, cursor는 하나의 원자 교체 JSON 상태 파일에 보관한다. 편집/outbox와 remote change/cursor가 각각 같은 저장 transaction에 들어간다.
- `PersistentMnemosyneReaderFacade`는 실제 `MnemosyneReaderEngine`을 주입받는다. 다운로드한 파일 설치, cached open, 읽기 위치, 검색, 목차, 페이지 이동, 임시 reader event, annotation 편집/삭제, pending/failed/retry, receipt/remote merge, 파생 PDF export를 연결한다. 네트워크 요청이나 성공 no-op은 넣지 않았다.
- `reader.annotate`는 `approveAnnotationSuggestion(_:)`가 명시적으로 불릴 때만 승인된다. `suggested_mutation_id`를 mutation ID로 사용하고 native `event_id`와 mutation outbox를 원자 저장한다. 동일 이벤트 재생은 저장된 mutation을 반환하고 내용이 바뀌면 거부한다.
- annotation draft의 문서/version/page, 색상·Ink geometry·TextAnchor 필드를 계약 구조에 맞춰 확인한다. highlight anchor는 `parse_revision`, 소문자 SHA-256, scalar 범위, quote, rect 배열과 문서/version/page 일치를 요구한다. 실제 인용 문자열이 PDF의 parser 텍스트와 일치하는지는 서버 UNIT-01의 검증 결과가 권위 경계다. PDFKit에서 검증할 수 없는 `text_sha256`을 만들어내지 않는다.
- Pumice Pencil 입력은 안정된 stroke ID, coalesced sample 위치, pressure, 경과 ms를 수집한다. canonical 좌표는 회전 전 raw PDF CropBox 좌표이며 CropBox 밖 획은 잘라 분할한다. `width_pt`는 화면 zoom과 독립된 physical point로 변환한다. Ink upsert/delete는 Core facade callback을 통해 로컬 outbox에 들어가며, 여러 획을 가진 annotation에서 일부 획만 지울 때 남은 획을 다시 저장한다.
- `PDFReaderViewController.saveIfNeeded()`는 원본 PDF에 쓰지 않고 SHA-256별 Application Support sidecar에 ink, 로컬 전용 PDFKit highlight, 마지막 page를 원자 저장한다. 재시작 시 복구한다. 원본 하이라이트/PDF 데이터는 직접 수정하지 않는다. export는 목적지와 원본 경로가 다름을 확인하고 임시 파생 PDF를 만든 뒤 목적지로 옮긴다.
- PDFKit 검색, outline 목차, 페이지 이동과 context 저장을 연결했다. PDFKit selection은 서버 검증 anchor로 가장하지 않아 `selection: null`이다. 한국어 응답 언어는 `ko`다. verified TextAnchor가 없는 사용자의 Pumice highlighter 결과는 로컬 sidecar에만 남고 서버 annotation sync로 보내지 않는다.
- 로컬 annotation을 Reader UI로 복원하고, server `reader.goto`, `reader.flash`, `reader.highlight` event를 대상 문서/version/page와 CropBox 범위로 확인한다. `reader.annotate` suggestion은 callback으로 전달하며 승인 UI는 UNIT-04에서 연결한다.

## UNIT-04 연결

`PDFReaderView`에 facade와 같은 `PumiceReaderEngine` 인스턴스를 넘긴다. `PersistentMnemosyneReaderFacade`를 만든 뒤 실제 cached URL로 Reader를 열고, Reader 생명주기에서 `readerContext()`를 저장한다. 애플리케이션은 `engine.onAnnotationSuggestion`을 사용자 확인 UI에 연결하고 확인 후 `facade.approveAnnotationSuggestion(event)`을 호출한다. UNIT-04 sync worker는 facade의 `pendingMutations`, `applySyncReceipts`, `applyRemotePage`, `failedMutations`, `retryMutation`만 사용한다.

```swift
let localStore = try FileMnemosyneLocalStore.applicationSupportStore()
let engine = PumiceReaderEngine()
let facade = try makeReaderFacade(
    factory: { store in PersistentMnemosyneReaderFacade(localStore: store, engine: engine) },
    localStore: localStore
)
// PDFReaderView(..., mnemosyneEngine: engine)
// Reader가 연결된 뒤: try await facade.openCached(documentID: id, versionID: version)
// 승인 UI에서: try facade.approveAnnotationSuggestion(event)
```

## Mac/Xcode 및 iPad 수동 검증 절차

Pumice 디렉터리에서 Xcode가 설치된 Mac에 아래 명령을 실행한다.

    xcodegen generate
    xcodebuild -project Pumice.xcodeproj -scheme Pumice -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
    swift test --package-path Packages/PumiceCore

그다음 Xcode에서 Pumice.xcodeproj의 Pumice scheme을 iPad Simulator와 실제 iPad에 실행하고 아래를 확인한다.

1. PDF를 한 번 내려받아 캐시에 둔 뒤 네트워크를 끄고 다시 연다. 캐시된 원본이 열리고 검색, 목차, 페이지 이동이 동작하는지 본다.
2. Apple Pencil로 여러 획을 쓰고 저장한 뒤 앱을 강제 종료하고 재실행한다. 획의 위치·색·두께가 복구되는지 본다.
3. 페이지 zoom과 기기 화면 방향을 바꾸며 획이 PDF의 같은 위치와 physical width를 유지하는지, CropBox 밖으로 저장되는 획이 없는지 확인한다.
4. undo/redo와 eraser로 한 획 및 여러 획 annotation의 일부를 지운 뒤 sidecar와 sync outbox가 같은 상태인지 확인한다.
5. Text Note와 Bookmark를 만들고 검색 결과, outline 이동, 현재 페이지 context를 확인한다. 서버 검증 TextAnchor가 주어지지 않은 selection은 null로 유지되는지 본다.
6. 원본 PDF의 SHA-256을 실행 전후 비교한다. 별도 목적지로 annotated copy를 export한 뒤 원본 해시가 그대로인지, export가 열리는지 확인한다.
7. UNIT-04 sync 연결 후 네트워크를 복구해 mutation receipt/cursor를 적용하고 앱을 재실행한다. 중복 mutation이 생기지 않고 실패 항목을 retry할 수 있는지 본다.
8. 실제 iPad에서 Pencil 입력 지연, 손바닥 거부, 장시간 필기 중 메모리 사용을 기록한다. Simulator 결과는 이 기기 항목의 대체가 아니다.

## 통합 담당 후속 사항

docs/INTEGRATION.md의 UNIT-03 등록 표에는 아직 concrete Reader facade 구현이 없다고 적혀 있다. 현재 구현과 충돌하므로 통합 담당이 연결 시 해당 표와 구현 상태를 갱신해야 한다. UNIT-03은 통합 소유 문서를 직접 수정하지 않았다.

## 검증과 미검증

- 통과: Core `ReaderFacade.swift`와 `MnemosyneGeometry.swift` 직접 Swift 타입검사.
- 통과: 변경된 Pumice Reader 소스와 Core geometry 테스트 파일의 Swift 구문 파싱.
- 통과: 임시 실행 harness에서 해시 캐시 설치/읽기 검증, context 재시작 복구, pending/failure/retry, receipt 적용, idempotency, cursor 원자 적용, 승인 이벤트 재생, 0/90/180/270 회전 역변환, CropBox clipping을 실행했다.
- 통과: UNIT-03 변경 경로의 `git diff --check`.
- 차단: SwiftPM 전체 테스트와 iPad 제품 빌드. 로컬은 full Xcode가 아닌 Command Line Tools만 선택되어 있고 `xcodebuild`/iOS Simulator SDK를 사용할 수 없다. 사용 가능한 Swift 6.3.3 compiler와 Command Line Tools SDK(6.3.2 build)의 차이 및 기본 SwiftPM cache 쓰기 제한 때문에 SwiftPM이 테스트 target까지 실행되지 않았다. 파일 단위 직접 타입검사/harness는 Package 테스트를 대체하지 않는다.
- 미검증: 실제 iPad Pencil, 화면 회전/zoom, 앱 강제 종료 후 복구, export PDF 렌더, 기기에서의 sidecar 보호 권한. Cloud 실행 환경의 Apple SDK 상태도 이 로컬 세션에서는 확인되지 않았다.
- Cloud Apple SDK 점검: 이 세션에서 사용할 수 있는 Cloud Xcode 실행/SDK 점검 도구가 없어 상태는 미확인이다. SDK가 없다고 단정하지 않는다.
- remote 목록은 비어 있다. 따라서 Cloud dispatch/PR 게시 여부는 미확인이다. 공통 registry의 `product_ready=false`를 유지하며 제품 완료로 보고하지 않는다.

UNIT-03 변경은 `codex/unit-03-reader` 격리 브랜치에 고정한다. 정확한 commit SHA는 작업 종료 보고에 기록한다.
