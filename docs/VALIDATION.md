# 실행한 검증과 남은 제품 인수

2026-10-08 · 계약 0.1.0. **소스 기반 공통 준비 PASS, 제품 준비 false, Cloud 게시 미실행.** 준비 검사는 아래 실제 소스와 같은 fixture를 사용했다. mock/fixture와 제품 빌드·기기 검증을 구별한다.

## 환경과 실행 결과

macOS arm64, Python 3.14.7, Node 24.19.0, Swift 6.3.3 Command Line Tools. 원래 manifests를 변경하지 않고 임시 Python 환경과 웹의 기존 lockfile로 의존성을 준비했다. 실제 검사 환경의 package 버전은 checks/audit-environment.txt다. 제품 dependency 설계가 아니라 이 실행의 재현 기록이며 UNIT-06이 실제 WSL2 환경을 검증한다. `pip check`도 PASS.

| 검사 | 실제 결과 / 범위 |
|---|---|
| `python checks/validate_contracts.py --require-ready` | PASS: OpenAPI operation 30, schema 4, schema instance 80, 거부 사례 19, sync 10단계, geometry 4, 소유 경로와 upstream provenance/source gate. 28 HTTP extension은 planned, health/ready 두 개만 observed; 모두 구현됐다는 뜻이 아님. |
| `python checks/sync_contracts.py --check` | PASS: 두 source의 계약 복사본 각각 10파일, 같은 manifest와 전체 바이트. |
| `python checks/source_adapters.py` | PASS: 실제 ReadingStore ingest/search/verify_quote, PyMuPDF 영문·한글 페이지/text/geometry, 엄격한 version/quote/page/rect 거부, native Pydantic command 5개, native WS frames와 capability 매핑 5개, 영문 문서 언어 en과 응답 언어 ko의 분리. 실제 SQLiteSessionStore의 native turn ID 생성, 동일 seq 중복 append, 저장소 재생성 후 after_seq=6 replay 검증. 원본 full SHA 보존. 전체 block만 geometry 검증, partial selection/OCR 미검증. |
| Node 24 `checks/web-consumer.mjs` | PASS: source-owned TS WS adapter, Unicode scalar, 두 실제 PDF.js page의 CropBox/Rotate/viewport forward·inverse, semantic subset/terminal/replay/quiz/learning 관계. 실제 browser DOM/UI 인수는 별도. 웹 npm ci 필요. |
| `swiftc` + `checks/ipad-consumer.swift` | PASS: 실제 PageGeometry/MnemosyneGeometry/ReaderFacade와 UNIT-04 native frame decoder를 같이 컴파일. 같은 fixture Codable와 app dependency seam typecheck, 네 회전/crop/userUnit 변환, native frame seq와 semantic subset, turn ID 문자열, 종료/재전송/annotation proposal/퀴즈 상태. 실제 PDFKit/Pencil 화면은 실행하지 않음. |
| Pumice `swift build --package-path Packages/PumiceCore` | PASS: 새 geometry/facade를 포함한 Core 라이브러리 host 컴파일. iPad 앱 빌드가 아님. |
| Pumice `swift test --package-path Packages/PumiceCore` | **FAIL**: 공식 test target이 `Testing` 모듈을 찾지 못함. 이 Mac의 CLT 한계. package에 macOS platform을 추가하거나 테스트를 삭제하지 않음. |
| DeepTutor `tests/core/test_stream_bus.py`, `tests/api/test_unified_ws_protocol.py`, `tests/reading/test_engine.py`, `tests/reading/test_grounding.py` | **95 passed**, 6.45초. 원래 conftest를 적용하고 source Reading/stream/protocol을 검사. |
| DeepTutor `tests/api/test_unified_ws_turn_runtime.py` | **20 passed**, 4 warnings, 4.39초. native turn lifecycle/replay/cancel/input. 실제 LLM 호출 테스트가 아님. |
| DeepTutor `tests/app/test_startup_data_migrations.py` | **1 passed**, 2.04초. 원래 startup migration 경계 검사. 전체 FastAPI lifespan/서버 부팅 검증은 별도. |
| DeepTutor `python scripts/check_architecture.py` | PASS: 원래 architecture boundary 규칙. |
| DeepTutor `ruff check deeptutor/mnemosyne`, `ruff format --check deeptutor/mnemosyne` | PASS: 신규 adapter 5파일, 원래 Python 규칙. |
| web `npm ci --ignore-scripts --no-audit --no-fund`, `npm run contracts:check`, `npm run typecheck` | PASS: 원래 lockfile/contract codegen과 신규 source TS adapter. |
| web `npm run build` | **최종 PASS**: Next 16.2.3 webpack compile, TypeScript, prerender. 최초 sandbox 실행은 Google Fonts DNS 차단으로 FAIL. 네트워크 허용 후 같은 명령이 통과. 기존 웹 화면의 빌드이며 Mnemosyne UI 구현 완료가 아님. |
| `docker compose -f docker-compose.yml config --quiet` | PASS: 원래 Docker compose 구조. Docker image build/run, WSL2 deployment/백업 인수가 아님. compose.yaml은 별도 Podman용이므로 파일을 명시. |
| PDF 확인 | 원본 SHA/페이지 수/PageLabels/CropBox/Rotate/text 확인, 두 페이지 Poppler PNG 시각 확인. 첫 fontconfig cache 오류는 임시 cache로 해결. 실제 학습 인용의 LLM 생성 검증은 아님. |
| Git / whitespace | 작업 branch `codex/mnemosyne-bootstrap`; authored 변경 whitespace 검사. original snapshot의 임의 재format 없음. 원래 파일 변경은 main.py 공통 등록 호출 한 곳이며 provenance에 기록. |

## 공통 검사 재실행

Python 3.14 가상 환경에서 `pip install -r checks/audit-environment.txt`, Node 24에서 `npm ci --ignore-scripts`를 upstreams/DeepTutor/web/에서 실행한다. 기본 제품 설치는 원래 DeepTutor pyproject/requirements를 따르며 이 임시 환경 기록으로 대체하지 않는다.

루트에서 다음을 실행한다.

```sh
python checks/validate_contracts.py --require-ready
python checks/sync_contracts.py --check
python checks/source_adapters.py
node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON checks/web-consumer.mjs
swiftc -module-cache-path /tmp/mnemosyne-swift-cache -parse-as-library \
  upstreams/Pumice/Packages/PumiceCore/Sources/PumiceCore/Coordinates/PageGeometry.swift \
  upstreams/Pumice/Packages/PumiceCore/Sources/PumiceCore/Coordinates/MnemosyneGeometry.swift \
  upstreams/Pumice/Packages/PumiceCore/Sources/PumiceCore/Mnemosyne/ReaderFacade.swift \
  upstreams/Pumice/Sources/Network/MnemosyneTurnWire.swift \
  checks/ipad-consumer.swift -o /tmp/mnemosyne-ipad-probe
/tmp/mnemosyne-ipad-probe "$PWD"
```

Linux Cloud에서는 Swift/UIKit/Pencil 인수를 PASS로 위장하지 않고 macOS/full Xcode 또는 실제 iPad job으로 분리한다. 기기 테스트를 fixture만으로 통과시키지 않는다.

## 아직 미검증이거나 구현이 필요한 항목

- 전체 DeepTutor backend test suite, 전체 FastAPI lifespan 부팅, 무거운 RAG/vector/parser/OCR 설치와 실제 LLM 호출·품질. 선택 dependency를 제거해 필수 학습 capability를 없애지 않는다.
- Pumice 전체 iPad 앱 빌드·Simulator·실제 Pencil, PDFKit ↔ canonical 화면 위치, 오프라인 입력/앱 종료 후 durable 복구, 실제 두 기기의 sync/충돌/cursor expiry/원본 불변/파생 export.
- 새 한국어 제품 UI, 모든 필수 학습 상태 transaction/재시작, partial span citation, native auth query token 제거/header·Origin 보호, 공개 signup/다중 사용자 기능 제외, uploads/path/settings 보호. 현재 최소 ports의 빈 구현을 제품 완료로 보고하지 않는다.
- Windows WSL2 Docker image 설치/실행·재시작·backup/restore·Tailscale/HTTPS의 실제 PC 인수.
- GitHub push/온라인 PR/여섯 Cloud 작업의 checkout 가능성. 이 준비 저장소에 remote가 없다. 시작 tag/SHA는 로컬에서 확정하며 PR 본문은 docs/REVIEW.md에 준비했다.
