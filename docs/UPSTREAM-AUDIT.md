# Upstream 소스 감사

2026-10-08 · 사용자가 지정한 정확한 두 URL의 main을 읽고 아래 SHA에 고정했다. `upstreams/`는 Git archive로 가져온 **원래 tracked 파일 snapshot**이다. 각 내부 경로·언어·프레임워크·라이선스를 보존했고 embedded `.git`, 로컬 사용자 데이터, 자격증명은 가져오지 않았다. Git subtree history라는 주장은 아니다. 독립 GitHub 저장소를 재배치한 것이 아니라 빈 준비 저장소에 두 원래 트리를 그대로 담아 Cloud 작업이 같은 commit에서 출발할 수 있게 했다.

| 소스 | 지정 URL / ref | 고정 commit | 라이선스 / 기존 지침 |
|---|---|---|---|
| Pumice | https://github.com/theagitist/Pumice · main | `a688aae2e6bce069ee256063c2a53afdcfe7de21` | MIT, LICENSE 보존. CLAUDE.md: iPadOS 전용, Swift 6, XcodeGen, 서명값 제외, Conventional Commits. 원래 private PRD는 접근 불가하며 복제하지 않음. 이번 사용자 명세를 적용. |
| DeepTutor | https://github.com/HKUDS/DeepTutor · main | `6cf793bd868ba5ecbe64722936d4be8fab5a01df` | Apache-2.0, LICENSE와 THIRD_PARTY_NOTICES.md 및 원래 third-party 라이선스 보존. 기존 AGENTS.md 읽음. |

`integration/upstreams.json`은 모든 원래 파일의 Git blob ID와 SHA-256, 변경 예외를 기록한다. 원래 파일 수정은 DeepTutor `deeptutor/api/main.py`에 공통 등록 호출 4줄 추가한 한 건이다. 신규 adapter와 계약 복사본은 별도로 표시한다. 제품 기능 구현 완료를 뜻하지 않는다.

## Pumice: 관찰한 실제 구현

| 실제 경로 / 심볼 | 재사용 | Mnemosyne 필수 변경 / 담당 |
|---|---|---|
| Sources/Reader/PDFReaderViewController.swift, PDFReaderView.swift, PDFReaderController.swift | UIKit/PDFKit PDF, 선택, page 이동과 0 기반 restorePageIndex, Pencil 펜·형광펜·전체 획 지우개·undo/redo, custom canvas/ink rendering | 03: facade 연결, 텍스트 검색/목차·노트·학습 북마크, 회전/CropBox 좌표. PDFKit 기능이 있다는 것과 앱 UI가 구현됐다는 것은 구별. |
| PDFReaderViewController.saveIfNeeded | Ink를 PDFAnnotation으로 만들고 NSFileCoordinator/document.write로 **입력 PDF를 덮어씀**, 2초 debounce | 03: 원본 쓰기를 제거하고 sidecar+outbox transaction으로 전환. export만 파생 PDF. 현재 앱을 Mnemosyne 불변 원본/오프라인 요구 충족으로 보고하면 안 됨. |
| Packages/PumiceCore/Sources/PumiceCore/Coordinates/PageGeometry.swift | Canvas↔MediaBox 변환, physical stroke/HighlightSerialization | 회전/CropBox 계약은 신규 MnemosyneGeometry가 검사되었지만 기존 Reader에는 아직 연결 전. PDFKit 좌표 변환을 두 번 적용하지 말 것. |
| Sources/Browser/VaultBrowserView.swift, Sources/Vault/VaultStore.swift | 기존 vault 탐색, security bookmark, 읽던 위치 | 04: 과목/Library/Tutor/다운로드·동기화 UI. 파일 bookmark는 학습 bookmark가 아님. |
| App/PumiceApp.swift, App/LaunchView.swift, project.yml, Config/ | SwiftUI 진입점, iPadOS 18+, Swift 6, XcodeGen | 04: 전용 한국어 화면과 dependency injection. iOS-only와 Catalyst NO 유지. |

확인 명령: `xcodegen generate`; `xcodebuild -project Pumice.xcodeproj -scheme Pumice -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`; `swift test --package-path Packages/PumiceCore`. 이 Mac은 full Xcode/XcodeGen이 없어 iPad 제품 빌드 미실행. Swift Core module은 컴파일됐으나 공식 테스트는 CLT의 `Testing` 모듈 부재로 컴파일 실패했다. 캐시를 임시 경로에 둔 별도 Swift fixture/실제 신규 geometry probe와 제품 빌드를 혼동하지 않는다. 결과는 VALIDATION 참조.

## DeepTutor: 관찰한 실제 구현

| 실제 경로 / 심볼 | 재사용 / 의미 | 필요한 연결 / 담당 |
|---|---|---|
| deeptutor/api/main.py · lifespan; app/container.py · ApplicationContainer | FastAPI, 한 process-level container; `.turns`가 API/WS 공통 runtime | 통합 담당만 register_mnemosyne를 호출. 유닛은 main/container를 함께 편집하지 않음. |
| api/routers/unified_ws.py · `/ws`; api/contracts/turn_protocol.py | 외부 WebSocket protocol 2.0. start_turn/subscribe_turn(after_seq)/resume_from(seq)/cancel_turn(command_id). native opaque turn_... ID, StreamEvent.seq와 persisted replay | **외부 WebSocket 하나 확정**. 기존 로그에 metadata.mnemosyne 확장을 저장하고 원래 seq를 유지. 새 SSE 경로 없음. |
| services/session/sqlite_store.py, session/turns/, session/legacy_migration.py | 기본 SQLite chat_history.db, 선택 PocketBase, turn event/command persistence | 모든 DB/migration은 01. 실행 서비스는 02. 세부 파일 소유 manifest를 따름. |
| reading/store.py · ReadingStore; reading/extract.py · extract_material | 원본 raw/units/media/render/revisions + manifest/annotations JSON. PDF 물리 순서 보존, locator **1 기반**, SHA-256 **16글자 content key** | 01: 외부 UUID document↔material 매핑 DB, full 원본 SHA version, immutable parser revision, sidecar revision/tombstone/cursor/멱등 transaction. 기존 annotation hard delete/JSON rewrite가 새 sync 계약 구현은 아님. |
| reading/service.py · verify_quote; reading/references.py | 실제 문서 text quote grounding, revision-bound references 재검증 | 01: 엄격한 offset/hash/geometry 검증 추가. native moved quote도 올바른 page로 명시 교정해야 함. 새 adapter는 fixture의 전체 block만 검증, 부분 span/OCR은 필수 구현 범위. |
| reading/models.py · Rect; web/components/reading/PdfDocumentView.tsx | top-left 0..1 rect; 실제 PDF rendered page bounds의 selection | 01/05: raw PDF CropBox/Rotate canonical 좌표로 변환. 새 adapter와 실제 parser fixture에서 왕복 검증. |
| services/parsing/, services/rag/, knowledge/ | 기존 parser IR/assets/cache와 RAG/search pipeline | 01: 그대로 연결. 모든 parser가 page geometry를 준다고 가정하지 않음. LLM/vector 품질·무거운 parser 설치는 미검증. |
| runtime/bootstrap/builtin_capabilities.py | chat, immersive_reading, deep_question, mastery_path, deep_solve가 실제 built-in 이름 | 02: 외부 chat/reading/quiz/mastery/solve adapter. assessment/memory/progress/review는 services와 persisted 상태이며 가상 built-in 이름으로 등록하지 않음. 전부 이번 범위. |
| learning/, services/practice/, api/routers/memory.py, learning_journal.py | 기존 mastery/문제·답안/복습/학습 기록 자원 | 02 서비스; learning/storage.py·migration.py·practice/storage.py 등 DB는 01. ko prompt/통합 학습 state 계약은 추가해야 함. |
| core/turn_request.py, core/response_languages.py | reply_language_override=ko 지원, language 별도 | 02: 문서 언어와 응답 언어를 분리. quote/math/code 보존. |
| services/llm/, data/user/settings runtime profile | 기존 provider/client adapter와 OpenAI-compatible 설정 | 02 runtime, 06 환경. 서버 자격증명만; 실제 LLM 호출 미검증. |
| api/routers/auth.py · ws_require_auth | auth 기본 disabled; WS는 현재 query token 또는 cookie, signup/admin 기능 포함 | 02: 개인 프로필에서 auth 강제, 공개 가입/다중 사용자 흐름 제외, native Bearer header·웹 보호 cookie+Origin, query secret 금지, 안전한 오류. 현재 상태는 안전한 배포 완료가 아님. |
| web/ · React 19, Next 16.2.3, PDF.js; Dockerfile · Node 22/Python 3.11 | 기존 웹·renderer·contract codegen·Docker 배치 | 05 한국어 UI와 전체 학습화면; 06 WSL2/개인 서버 배치·백업/복구. Rust는 일부 Python dependency 빌드 도구일 뿐 제품 재작성 없음. |

실제 manifest/lockfile/CI 명령: Python `pip install -e '.[dev]'`, `pytest`; web `npm ci`, `npm run contracts:check`, `npm run typecheck`, `npm run build`; Docker `python scripts/docker_compose.py config`, `docker build -t deeptutor:local .`. 실행한 subset과 실패는 VALIDATION에 기록. Windows WSL2/Pencil 실기기/실제 provider 호출/전체 product 빌드 성공은 주장하지 않는다.
