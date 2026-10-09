# UNIT-03 인수: iPad PDF·Pencil·로컬 Reader

이 파일은 integration/ownership.json에서 UNIT-03에 배정된 canonical handoff 경로다. docs/handoffs/unit-03.md는 소유권에 배정되지 않아 만들지 않았고, 사용자는 현재 소유 경로를 유지하기로 했다.

담당 범위는 `integration/ownership.json`의 `owners.UNIT-03`에 맞춘다. 계약은 `0.1.0`이며 계약 원본/복사본, `Package.swift`, Xcode 설정은 수정하지 않았다. 기존 Pumice 소스 파일만 확장했으므로 새 XcodeGen 등록은 없다. `makeReaderFacade(factory, localStore)` 등록 경로와 빈 no-op 대체 금지 원칙을 유지한다.

## 구현

- `FileMnemosyneLocalStore`는 원본 PDF를 `sha256:<64자리>` 전체 해시로 확인한 뒤 주소화된 파일로 설치하고, 읽기 때도 해시를 다시 확인한다. 원본은 변경하지 않는다. context, annotation projection, mutation outbox, 승인 이벤트 ID, sync receipt, cursor는 하나의 원자 교체 JSON 상태 파일에 보관한다. 편집/outbox와 remote change/cursor가 각각 같은 저장 transaction에 들어간다.
- 같은 annotation에 대한 outbox 변경은 FIFO로 처리한다. `pendingMutations`는 annotation마다 head 하나만 반환하고, failed head는 뒤 변경을 대기시킨다. head의 applied receipt가 반영되면 다음 미전송 mutation의 `base_revision`을 적용된 annotation revision으로 갱신한다. `conflict` head는 같은 mutation ID 재시도를 막고 `mutationFailureReason(_:)`과 `resolveMutationConflict(_:resolution:)`으로 사용자 선택을 제공한다. `.keepLocal(replacementMutationID:)`는 체인의 최신 로컬 편집을 새 mutation ID와 최신 remote revision으로 재구성한다. 서버 tombstone이 최신 상태면 새 annotation ID와 base revision 0을 사용한다. `.acceptRemote`는 대기 체인을 제거하고 remote projection을 표시한다. failed head 뒤의 pending 초안은 cursor 변경을 막지 않아 최신 서버 revision으로 해결할 수 있다.
- `PersistentMnemosyneReaderFacade`는 실제 `MnemosyneReaderEngine`을 주입받는다. 다운로드한 파일 설치, cached open, 읽기 위치, 검색, 목차, 페이지 이동, 임시 reader event, annotation 편집/삭제, pending/failed/retry, receipt/remote merge, 파생 PDF export를 연결한다. 네트워크 요청이나 성공 no-op은 넣지 않았다.
- `reader.annotate`는 `approveAnnotationSuggestion(_:)`가 명시적으로 불릴 때만 승인된다. `suggested_mutation_id`를 mutation ID로 사용하고 native `event_id`와 mutation outbox를 원자 저장한다. 동일 이벤트 재생은 저장된 mutation을 반환하고 내용이 바뀌면 거부한다.
- annotation draft의 문서/version/page, 색상·Ink geometry·TextAnchor 필드를 계약 구조에 맞춰 확인한다. highlight anchor는 `parse_revision`, 소문자 SHA-256, scalar 범위, quote, rect 배열과 문서/version/page 일치를 요구한다. 실제 인용 문자열이 PDF의 parser 텍스트와 일치하는지는 서버 UNIT-01의 검증 결과가 권위 경계다. PDFKit에서 검증할 수 없는 `text_sha256`을 만들어내지 않는다.
- Pumice Pencil 입력은 안정된 stroke ID, coalesced sample 위치, pressure, 경과 ms를 수집한다. canonical 좌표는 회전 전 raw PDF CropBox 좌표이며 CropBox 밖 획은 잘라 분할한다. `width_pt`는 화면 zoom과 독립된 physical point로 변환한다. Ink upsert/delete는 Core facade callback을 통해 로컬 outbox에 들어가며, 여러 획을 가진 annotation에서 일부 획만 지울 때 남은 획을 다시 저장한다.
- `PDFReaderViewController.saveIfNeeded()`는 원본 PDF에 쓰지 않고 SHA-256별 Application Support sidecar에 ink, 로컬 전용 PDFKit highlight, 마지막 page를 원자 저장한다. 평소에는 저장을 debounce하되 view가 사라지거나 앱이 `UIApplication.willResignActiveNotification`을 받으면 대기 중인 sidecar 저장을 flush한다. 재시작 시 복구한다. 원본 하이라이트/PDF 데이터는 직접 수정하지 않는다. export 전에 pending sidecar 저장 오류를 확인하고, 동기화 가능한 annotation과 sidecar-only highlight를 원본 SHA가 일치할 때 파생 PDF에 함께 쓴다. 목적지가 원본과 다름을 확인한 뒤 임시 파일을 옮긴다.
- Reader는 sidecar 저장 실패와 annotation outbox 저장 실패를 구분해 `PDFReaderController.localSaveError`로 노출한다. sidecar 오류는 파일별, outbox 오류는 문서/version/annotation별로 추적하므로 다른 문서의 편집이 오류를 지우거나 잘못 표시하지 않는다. UNIT-04 UI는 이 로컬 저장 오류를 네트워크 sync 오류와 별도로 표시한다.
- PDFKit 검색, outline 목차, 페이지 이동과 context 저장을 연결했다. 저장한 `viewport_rect`는 PDFView layout 이후 대상 페이지의 중심과 zoom 복구에 사용한다. 복원 scale은 회전, CropBox, UserUnit을 반영하며 잘못된 rect이면 페이지 위치만 복구한다.
- Core annotation projection는 note를 free-text PDFAnnotation으로, bookmark를 CropBox 안의 PDF page marker로 복원하며 파생 export에도 포함한다. facade.selectedText()는 PDFKit raw selection을 반환하고 이전 anchor를 비운다. PDFKit selection-change 알림도 anchor를 자동으로 무효화한다. UNIT-04는 새 선택을 서버에서 검증하고 결과 TextAnchor만 facade.setVerifiedSelectionAnchor(_:)로 전달한다. Core는 문서/version/page와 구조를 확인하되 parser hash를 다시 만들지 않는다. 기본은 `selection: null`이다. 한국어 응답 언어는 `ko`다. verified TextAnchor가 없는 사용자의 Pumice highlighter 결과는 로컬 sidecar에만 남고 서버 annotation sync로 보내지 않는다.
- 로컬 annotation을 Reader UI로 복원하고, server `reader.goto`, `reader.flash`, `reader.highlight` event를 대상 문서/version/page와 CropBox 범위로 확인한다. `reader.annotate` suggestion은 callback으로 전달하며 승인 UI는 UNIT-04에서 연결한다.

## UNIT-04 연결

`PDFReaderView`에 facade와 같은 `PumiceReaderEngine` 인스턴스를 넘긴다. `PersistentMnemosyneReaderFacade`를 만든 뒤 실제 cached URL로 Reader를 열고, Reader 생명주기에서 `readerContext()`를 저장한다. 애플리케이션은 `engine.onAnnotationSuggestion`을 사용자 확인 UI에 연결하고 확인 후 `facade.approveAnnotationSuggestion(event)`을 호출한다. UNIT-04 sync worker는 `pendingMutations`, `applySyncReceipts`, `applyRemotePage`, `failedMutations`, `retryMutation`을 사용한다. 실패 UI는 `mutationFailureReason(_:)`으로 코드를 표시한다. `PDFReaderController.localSaveError`는 sidecar 또는 로컬 outbox 저장 실패 상태이며 sync 실패 상태와 별도로 표시한다. `conflict`이면 사용자에게 최신 원격본 또는 로컬 편집 유지 선택을 보여주고, 로컬 편집을 유지할 때 `resolveMutationConflict(_:resolution: .keepLocal(replacementMutationID: UUID()))`가 돌려준 새 payload를 전송 대기열에 둔다. 원격본을 선택하면 `.acceptRemote`를 호출하고 다시 전송하지 않는다.

```swift
let localStore = try FileMnemosyneLocalStore.applicationSupportStore()
let engine = PumiceReaderEngine()
let facade = try makeReaderFacade(
    factory: { store in PersistentMnemosyneReaderFacade(localStore: store, engine: engine) },
    localStore: localStore
)
// PDFReaderView(..., mnemosyneEngine: engine)
// Reader가 연결된 뒤: try await facade.openCached(documentID: id, versionID: version)
// 선택 변경 후: let text = try facade.selectedText()
// 서버 검증 후: try facade.setVerifiedSelectionAnchor(anchorData)
// 승인 UI에서: try facade.approveAnnotationSuggestion(event)
// 충돌 UI에서: try facade.resolveMutationConflict(id, resolution: .keepLocal(replacementMutationID: UUID()))
```

## Mac/Xcode 및 iPad 수동 검증 절차

2026-10-09 재확인: 현재 로컬 검증 환경은 XcodeGen/full Xcode/iOS SDK를 제공하지 않는다. xcode-select -p는 /Library/Developer/CommandLineTools를 반환한다. xcodebuild -version은 active developer directory가 Command Line Tools라 Xcode가 필요하다고 실패했고, xcrun --sdk iphonesimulator --show-sdk-path는 SDK를 찾지 못했다. `/Applications/Xcode*.app`와 Spotlight 검색에서 Xcode bundle을 찾지 못했고, `xcodegen` 명령도 설치되어 있지 않다.

Cloud Apple SDK 확인 결과도 미확인이다. 2026-10-09 현재 도구 목록에는 Cloud Xcode/SDK probe나 원격 Mac build 실행기가 없고, project 목록에는 local projects와 ChatGPT projects만 있어 Cloud Mac project를 찾지 못했다. registry의 cloud_repository_access는 local_only_no_origin이다. 이는 이 환경에서 확인할 수 없다는 뜻이며 Cloud에 SDK가 없다는 증거는 아니다. Cloud runner에 접근할 수 있으면 아래도 기록한다.

    xcodebuild -version
    xcodebuild -showsdks
    xcrun --sdk iphoneos --show-sdk-path
    xcrun --sdk iphonesimulator --show-sdk-path

Full Xcode와 XcodeGen이 설치된 Mac에서 upstreams/Pumice 디렉터리로 이동해 실행한다. project.yml의 Pumice scheme은 PumiceTests를, PumiceUITests scheme은 UI test target을 실행한다. 사용 가능한 iPad Simulator UDID는 먼저 확인한다.

    cd upstreams/Pumice
    xcodegen generate
    swift test --package-path Packages/PumiceCore
    xcodebuild -project Pumice.xcodeproj -scheme Pumice -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
    xcrun simctl list devices available
    xcodebuild test -project Pumice.xcodeproj -scheme Pumice -destination 'platform=iOS Simulator,id=<iPad Simulator UDID>' CODE_SIGNING_ALLOWED=NO
    xcodebuild test -project Pumice.xcodeproj -scheme PumiceUITests -destination 'platform=iOS Simulator,id=<iPad Simulator UDID>' CODE_SIGNING_ALLOWED=NO

실제 iPad에서는 로컬 Xcode signing team을 설정한 뒤 Pumice scheme을 연결 기기로 빌드/실행한다. signing 설정과 비밀값은 commit하지 않는다. 새 Swift source file은 추가하지 않았고 기존 project.yml이 App/Sources 디렉터리를 포함하므로 XcodeGen source 등록 변경은 없다.

그다음 iPad Simulator와 실제 iPad에서 아래를 확인한다.

1. PDF를 한 번 내려받아 캐시에 둔 뒤 네트워크를 끄고 다시 연다. 캐시된 원본이 열리고 검색, 목차, 페이지 이동이 동작하는지 본다.
2. Apple Pencil로 여러 획을 쓰고 저장한 뒤 앱을 강제 종료하고 재실행한다. 획의 위치·색·두께가 복구되는지 본다.
3. 페이지 zoom과 기기 화면 방향을 바꾸며 획이 PDF의 같은 위치와 physical width를 유지하는지, CropBox 밖으로 저장되는 획이 없는지 확인한다.
4. undo/redo와 eraser로 한 획 및 여러 획 annotation의 일부를 지운 뒤 sidecar와 sync outbox가 같은 상태인지 확인한다.
5. Text Note와 Bookmark를 만들고 검색 결과, outline 이동, 현재 페이지 context를 확인한다. 서버 검증 TextAnchor가 주어지지 않은 selection은 null로 유지되는지 본다.
6. 서버 동기화 가능한 주석과 verified TextAnchor가 없는 sidecar-only 하이라이트가 모두 포함된 annotated copy를 export한다. 원본 PDF의 SHA-256을 실행 전후 비교하고, 파생 PDF가 열리는지 확인한다.
7. UNIT-04 sync 연결 후 네트워크를 복구해 mutation receipt/cursor를 적용하고 앱을 재실행한다. 중복 mutation이 생기지 않고 실패 항목을 retry할 수 있는지 본다.
8. 실제 iPad에서 Pencil 입력 지연, 손바닥 거부, 장시간 필기 중 메모리 사용을 기록한다. Simulator 결과는 이 기기 항목의 대체가 아니다.

## 통합 담당 후속 사항

docs/INTEGRATION.md의 UNIT-03 등록 표에는 아직 concrete Reader facade 구현이 없다고 적혀 있다. 현재 구현과 충돌하므로 통합 담당이 연결 시 해당 표와 구현 상태를 갱신해야 한다. UNIT-03은 통합 소유 문서를 직접 수정하지 않았다.

`integration/upstreams.json`은 INTEGRATOR 소유라 UNIT-03에서 수정하지 않았다. manifest와 현재 트리를 비교하면 UNIT-03 소유 원본 파일 8개가 pinned snapshot과 다르다. 아래 표는 통합 담당이 `modified_originals`에 등록할 수 있도록 `reason` 값과 현재 SHA를 제안하고, 각 수정의 소비자 영향 및 실제 검증 상태를 함께 기록한다. 등록 뒤 통합 담당이 `checks/validate_contracts.py --require-ready`를 다시 실행해야 한다.

| Original path | Pinned SHA-256 | Proposed current SHA-256 | Proposed `reason` | 소비자 영향 및 검증 상태 |
|---|---|---|---|---|
| `upstreams/Pumice/Packages/PumiceCore/Tests/PumiceCoreTests/PageGeometryTests.swift` | `15b3e7eb94398bd558ec454ea793c1bc965676d5e9a9c6812518972118a2f639` | `fadd833c581e946f2ace3774ebfa99a4d33e153c27ddea68f8e6a8a660a591d2` | Add UNIT-03 regression coverage for canonical geometry, viewport restoration, persistence, selection invalidation, mutation outbox, and explicit conflict resolution; fix ambiguous `CGFloat.nan` typing and the initial `base_revision` fixture. | 생산 코드 API는 바꾸지 않는다. Core geometry/facade 회귀를 검사한다. 공식 Core 테스트 소스 88개/16개 suite가 임시 SwiftPM wrapper에서 통과했다. 이는 macOS Core 검사이며 iPad 앱/Simulator 테스트가 아니다. |
| `upstreams/Pumice/Sources/Reader/PDFReaderController.swift` | `c8c8d5c774a14e962d934380b3308474e095138c3a756a6cfd58885f735c0f92` | `7050060e398ca9c5ff56d7947d3e27cba994969b68e2173c3378ac6188f0c43a` | Add the `PumiceReaderEngine` adapter that connects the existing PDFKit Reader to the UNIT-03 facade for opening, context, search, outline, page navigation, reader events, annotations, undo/redo, and export; expose local sidecar/outbox save failures to UNIT-04. | UNIT-04 must pass the same engine instance to `PDFReaderView` and the facade, then open the cached document after attachment. `localSaveError` separates persistence failures from sync failures; Swift syntax parsing passed, while iPad app build remains unverified. |
| `upstreams/Pumice/Sources/Reader/PDFReaderView.swift` | `21cca91197d5d94bf2de844e4cc2ffe6379906c0479267f1eceb36b5fa72ee16` | `e75208d987e2d291084cd37ffcb254195722505b5f113a9ea02b6d122a1764d0` | Add optional engine injection and attach/load it from the SwiftUI view lifecycle. | UNIT-04 supplies the shared engine at the Reader construction site. The parameter remains optional for existing call sites. Swift syntax parsing passed; view lifecycle was not checked in Simulator. |
| `upstreams/Pumice/Sources/Reader/PDFReaderViewController.swift` | `9e2cebc73da85dc5999d7d9827491d7dde8fa23dc2292fd14ca249c097983f64` | `7f267b15f2deaf49e0cc9d5a393701224ac1da75d3a502d007562642f1638d3c` | Integrate the concrete Reader with the facade; persist local ink/highlights and viewport in a hash-keyed sidecar; add search, outline, context, annotation/outbox callbacks, viewport restore, and derived-PDF export while keeping the source PDF unchanged; export sidecar-only local highlights and constrain note bounds to small CropBoxes; flush pending sidecar saves when the app resigns active; track outbox persistence errors by document/version/annotation. | UNIT-04 uses the shared engine for app wiring and annotation approval. `PDFReaderController.localSaveError` exposes local persistence failures independently of sync failures. App build, PDFKit export, sidecar protection, and Simulator/device behavior remain unverified. |
| `upstreams/Pumice/Sources/Reader/PenSettings.swift` | `fb7849e6e6476e4c17a8a3cff997200c528b44b168b5fe3338c97c39a384e688` | `30e164a738f99c718c817c53743b2cf642cc7fcab76fbc14a9d74dcad5f5d8e0` | Extend stroke records with stable identity, optional annotation linkage, and Pencil sample location, pressure, and elapsed time. | Canvas/controller consumers use these values to rebuild strokes and form geometry-backed mutations. Core serialization tests passed; persistence/render compatibility on iPad remains unverified. |
| `upstreams/Pumice/Sources/Reader/PumiceCanvasView.swift` | `bf0cc84cdddfde4449e3d13574fafaebe4687a7bc9a4baa014b3e997ef263faf` | `35dacbceb7b9a9d4df2d8021cb291f2d6634eee85dffa9d72eab155fec2c6edf` | Report canvas bounds changes and forward collected Pencil samples to the Reader controller for canonical-coordinate conversion and viewport updates. | `PDFReaderViewController` consumes the callbacks; UNIT-04 has no new API to implement. Zoom/rotation behavior is covered by Core harnesses but not by PDFKit Simulator or device validation. |
| `upstreams/Pumice/Sources/Reader/PumicePencilGestureRecognizer.swift` | `63b48c0da96504f9b1d49f790ba7c24b1e77b1c6be36bc10f27f61c3ba3be7a0` | `68efa71533b9e2933a35089111683839bd26883caab2a16ff0b33f0d73048f56` | Collect coalesced Pencil touch positions, pressure, and timestamps; accept allowed Pencil touches even when `UIEvent.allTouches` also includes a concurrent finger/palm touch. | Canvas/controller consumes the sample stream while finger inputs remain available to PDFView. Swift syntax parsing passed; actual finger-scroll coexistence, Pencil latency, and palm rejection require iPad validation and remain unverified. |
| `upstreams/Pumice/Tests/PumiceTests/RoundTripTests.swift` | `65b75c6d9166bede45a09552f3f4ce3963bd1784d4d375971841b2e055ca66c2` | `c340a4352e95697ed586e49ac95ca1798ba6d145104a5173a5de862f6ae376aa` | Add an iOS PDFKit regression test that exports a sidecar-only highlight and verifies the source PDF bytes remain unchanged. | The test uses a temporary PDF and the app's hash-keyed sidecar location. It requires the Pumice iOS Simulator target and has not been run because full Xcode/iOS SDK is unavailable locally. |

These are proposals only: do not copy them into `integration/upstreams.json` without an integrator-owned change. The contract stays at `0.1.0`; no contract or fixture payload changed.

`checks/validate_contracts.py --require-ready`는 첫 번째 경로에서 `Upstream snapshot differs`로 실패했다. UNIT-03은 통합 manifest를 수정하지 않았다.

## 검증과 미검증

- 통과: Core `ReaderFacade.swift`와 `MnemosyneGeometry.swift` 직접 Swift 타입검사.
- 통과: 변경된 Pumice Reader 소스와 Core geometry 테스트 파일의 Swift 구문 파싱.
- 통과: viewport scale harness에서 0/90/180/270도, UserUnit, CropBox 외부 rect 거부를 실행했다. PDFKit viewport 복원은 Simulator에서 확인하지 않았다.
- 통과: 임시 실행 harness에서 해시 캐시 설치/읽기 검증, context 재시작 복구, pending/failure/retry, receipt 적용, idempotency, cursor 원자 적용, 승인 이벤트 재생, 0/90/180/270 회전 역변환, CropBox clipping, verified selection 복구와 selection-change 무효화를 실행했다.
- 통과: 임시 SwiftPM wrapper `/private/tmp/mnemosyne-pumicecore-test`에서 현재 worktree의 공식 `PumiceCore/Sources`와 `PumiceCore/Tests`를 symlink해 실행했다. wrapper manifest만 macOS 10.15.4를 추가하고 공식 `swift-testing` 6.3.2의 test-only `_TestingInterop` target을 노출하도록 `/private/tmp` 사본에서 조정했다. 실행 명령은 `swift test --package-path /private/tmp/mnemosyne-pumicecore-test`이며 총 88개 테스트/16개 suite가 통과했다. 여기에는 conflict head 재시도 차단, 최신 로컬 편집을 새 mutation ID/최신 revision으로 유지, tombstone 복구 시 새 annotation ID 생성, remote 선택이 포함된다. 저장소 manifest와 소스는 바꾸지 않았다. macOS Core 검사이며 Pumice iOS/PDFKit UI는 포함하지 않는다.
- 미실행: `RoundTripTests.sidecarHighlightExport` iOS/PDFKit 회귀 테스트를 추가했다. sidecar-only highlight가 파생 PDF로 들어가고 원본 bytes가 유지되는지 확인하도록 작성했지만, iOS Simulator SDK/full Xcode가 없어 이 회귀 테스트는 실행하지 못했다.
- 통과: command-line macOS 10.15.4 target override로 SwiftPM PumiceCore production target을 빌드했다. 이는 macOS Core 빌드이며 iPad 앱/Simulator 빌드가 아니다.
- 통과: `checks/validate_contracts.py`가 OpenAPI operation 30개, schema instance 80건, negative case 19건, sync step 10건, geometry case 4건과 전체 ownership check를 통과했다. 이 실행은 `source_gate_checked=false`다.
- 실패: `checks/validate_contracts.py --require-ready`는 `Upstream snapshot differs: upstreams/Pumice/Packages/PumiceCore/Tests/PumiceCoreTests/PageGeometryTests.swift`로 중단됐다. 위 통합 담당 후속 manifest 예외를 기록하고 다시 확인해야 한다.
- 통과: UNIT-03 변경 경로의 `git diff --check`.
- 차단: 원래 package 경로로 SwiftPM 테스트를 시작하면 CLT의 `Testing` module 부재로 실패한다. 단, 위의 임시 wrapper에서 동일한 Core 테스트 소스를 별도 실행했다. package 기본 macOS target의 CryptoKit/FileHandle 제약 때문에 검사 명령에만 target override를 썼다. 로컬 developer directory는 full Xcode가 아닌 Command Line Tools이며 xcodebuild와 iOS Simulator SDK를 사용할 수 없어 iPad 앱 빌드와 Simulator 검증은 하지 못했다.
- 미검증: 실제 iPad Pencil, 화면 회전/zoom, 앱 강제 종료 후 복구, export PDF 렌더, 기기에서의 sidecar 보호 권한. Cloud 실행 환경의 Apple SDK 상태도 이 로컬 세션에서는 확인되지 않았다.
- Cloud Apple SDK 점검: 이 세션에서 사용할 수 있는 Cloud Xcode 실행/SDK 점검 도구가 없어 상태는 미확인이다. SDK가 없다고 단정하지 않는다.
- `git remote -v`는 비어 있다. GitHub 연결 계정에서 `Mnemosyne`를 검색한 결과 `rightheous/mnemosyne`가 보였지만, 저장소 크기는 0이고 `main`/`codex/unit-03-reader` branch 검색과 PR 검색 모두 비어 있었다. 이 저장소가 이 workspace의 승인된 원격인지 확인되지 않았고 PR base도 없어 push, 저장소 초기화, PR 생성을 하지 않았다. 사용할 원격과 기존 base branch를 확인한 뒤 연결한다. 공통 registry의 `product_ready=false`를 유지하며 제품 완료로 보고하지 않는다.

UNIT-03 변경은 `codex/unit-03-reader` 격리 브랜치에 고정한다. 정확한 commit SHA는 작업 종료 보고에 기록한다.
