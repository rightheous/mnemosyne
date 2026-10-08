# UNIT-05 인수 경계

담당: Mac 웹 전체·manifest/lockfile·PDF와 ink 표시·학습 화면. 공통 시작 tag `mnemosyne-bootstrap-v0.1.0`, 계약 `0.1.0`.

실제 등록 경로: `upstreams/DeepTutor/web/features/mnemosyne/register.ts` · `mountMnemosyneWeb`. docs/INTEGRATION.md의 signature와 callers를 읽는다.

기존 Next/React/PDF.js와 native /ws client 유지. App에서 composition을 연결. 한국어 과목/Library/upload/delete/PDF/annotations/Tutor/Quiz/Assessment/Mastery/Solve/Memory/Progress/Review/settings 전체. iPad ink 조회만. frame 전체 seq checkpoint, semantic subset seq를 renumber하지 않음. same-origin cookie/Origin 보호, schema 소비 검증.

현재 common seam/fixture가 있다는 것은 제품 구현 완료가 아니다. 빈 port를 success/no-op으로 채우지 않는다. 필수 기능은 모두 이번 범위다.

정확한 수정 가능 파일 1408개는 integration/ownership.json의 owners.UNIT-05 배열이다. 주요 directory는 OWNERSHIP.md 참조. 다른 소유자의 공통 startup/계약/DB/manifest 파일을 편집하지 않는다.

새 계약 변경은 소비자 영향·version·fixture·검증 변경을 포함해 통합 담당에게 제안한다. DB 요구는 schema/migration/transaction/검증 명세로 01에 전달한다. 사용자 지시 없이 다른 채팅에 메시지를 보내지 않는다.

인수 결과는 실행한 명령·실제 source/service/build/device 종류·실패/차단을 구별하고 기록한다. 공통 fixture PASS를 제품 오프라인/LLM/기기 검증으로 대체하지 않는다. 원본 hash, 잘못된 인용 거부, replay/cancel/error와 재시작 저장을 실제 경계에서 확인한다.

## UNIT-05 계약/통합 요청 (2026-10-09)

현재 루트 계약 `0.1.0`과 `contracts/openapi.yaml`을 실제 웹 흐름에 대조했다. 아래 항목은 UI가 동작을 꾸며내지 않도록 통합 담당이 계약/서버와 함께 확정해야 한다. UNIT-05는 루트 계약과 snapshot 복사본을 수정하지 않는다.

1. **폴더**: 현재 `Subject`만 있고 별도 folder DTO/경로 및 `Document.folder_id`가 없다. 과목별 폴더 UI가 필요하면 Folder DTO(과목 소속, 이름, 상위 폴더 선택 여부, revision), list/create/rename/delete API, 문서 upload/update의 folder 이동을 추가한다. Web Library는 UNIT-05, durable mapping/API는 UNIT-01/02 소비 영향이 있다. 제안 버전 `0.2.0`; fixture에 중첩 및 빈 폴더, 문서 이동을 추가하고 Web/API/fixture 검증을 갱신한다. Subject를 폴더로 간주하는 대안이면 공통 제품 용어를 바꾸는 결정이 필요하다.
2. **현재 parse revision 조회**: `GET /v1/documents/{id}/pages/{page_index}`가 `parse_revision`을 필수 query로 요구하지만 `Document` list/detail에 해당 필드가 없어 웹이 처음 읽을 revision을 알 수 없다. Document에 현재 `parse_revision`(분석 전에는 null)을 반환하거나, 페이지 API에서 query 생략 시 현재 revision을 고르고 응답 `Page.parse_revision`을 돌려주도록 한다. UNIT-01 API와 Web/계약 fixture 영향; 제안 `0.2.0`; fixture 검증에 list→page→stale revision 거부를 포함한다.
3. **읽던 위치 저장**: 계약은 `LearningState.progress.last_page_index` 읽기만 제공하고 일반 Reader 위치를 저장하는 경로가 없다. 같은 문서의 Mac/iPad 간 복구를 위해 버전 묶음 `page_index + viewport_rect`를 GET/PUT하는 API와 문서 revision/멱등 규칙을 정의한다. UNIT-01 저장·UNIT-03/04 iPad·UNIT-05 Web 소비 영향; 제안 `0.2.0`; 두 client 재시작/상호 복구 fixture와 제품 검증을 추가한다. 현 UI의 브라우저 로컬 저장은 같은 브라우저 복구에만 해당한다.
4. **분석 재시도**: `DocumentUpdate`는 title/subject만 받으며 failed parse/index를 다시 시작하는 action이 없다. 실패 문서에 대한 재시도 endpoint, idempotency 및 parse/index 상태 전이를 정의한다. UNIT-01/02와 Web Library 영향; 제안 `0.2.0`; failed→running→ready 및 재시도 실패 fixture/검사를 추가한다.
5. **Tutor 입력 wire**: native `/ws` protocol 2.0의 `start_turn`은 기존 upstream schema이고 `TurnRequest`(capability, `ReaderContext`, `response_language`)를 싣는 확장 규칙이 명시되지 않았다. HTTP `TurnRequest`는 schema에만 있고 start/turn 생성 route는 없다. HTTP 생성 경로를 추가하지 않는 결정은 유지하되, `start_turn.config`의 contract-versioned Mnemosyne field와 UNIT-02 소비 규칙을 공통 문서/fixture에 고정해야 한다. UI 제안은 `config.mnemosyne.turn_request`이며 통합 담당 확인 전 서버 연결 완료로 간주하지 않는다. Web/02/API fixture 영향; 제안 `0.2.0`; `chat/quiz/mastery/solve` request round-trip와 document/version-bound stream events를 검사한다.
6. **Web pairing cookie**: `/v1/session/pair` 응답 `PairReceipt`에는 bearer `access_token`이 필수지만 WebSocket은 브라우저에서 Authorization header를 설정할 수 없고 공통 보안 문서는 Web same-origin 보호 cookie를 요구한다. 웹 pairing이 HttpOnly/Secure/SameSite cookie를 설정하고 JS에는 bearer를 반환하지 않는 Web 전용 경로 또는 응답 분기를 계약으로 명시한다. UNIT-02 auth/router와 Web 영향; 제안 `0.2.0`; 쿠키 세션 WebSocket handshake, Origin 거부, token 비노출을 검사한다.

## 현재 소스 조립 상태 재확인 (2026-10-09)

작업 중인 공유 트리에는 UNIT-01/02 서비스 변경도 보이지만 이는 UNIT-05가 수정하지 않는다. UNIT-01의 `build_library_router(library)`는 설정·과목·문서·페이지·검색·인용 검증·주석·export handler를 만들지만, `deeptutor/api/main.py`는 lifespan에서 `app.state.mnemosyne` 서비스만 만들고 이 router를 `include_router`하지 않는다. 따라서 OpenAPI의 planned endpoint는 실제 HTTP 기능으로 광고할 수 없다. 같은 current tree에서 `/v1/readiness`, pairing/revoke, learning state/review, quiz/attempt, tutor turn 조회, parse/index retry, cross-device reader position router는 확인되지 않았다. 이 확인은 정적 소스 대조이며 API 실행 검증은 아니다.

서버 router의 `expected_revision()`은 `If-Match`에 따옴표가 포함된 ETag 형식(`"7"`)을 요구한다. UNIT-05 API client는 이에 맞게 모든 revision 조건부 요청을 인용된 값으로 보낸다.

화면 JSX는 등록 어댑터 `register.ts`와 분리한다. 사용자가 2026-10-09에 `upstreams/DeepTutor/web/features/mnemosyne/screens.tsx`를 UNIT-05에 배정했으며 `integration/ownership.json`, registry 파일 수, OWNERSHIP 표에 반영했다. 웹 same-origin proxy도 native `/ws`와 같은 backend base로 `/v1/*`를 전달하도록 확장했다.

요청된 `docs/handoffs/unit-05.md`는 `integration/ownership.json`에 UNIT-05 소유 경로로 배정되어 있지 않다. 정확 경로 규칙과 “새 파일은 통합 담당이 먼저 배정” 지침에 따라 이 내용은 기존 UNIT-05 배정 파일에 기록했다. 해당 문서 경로를 사용하려면 통합 담당의 소유권 배정이 필요하다.

## 브라우저 시각 검증 대상

- Library: 빈 라이브러리, 과목 필터/검색, PDF 업로드 진행/실패, 분석 상태, 삭제 확인/오류.
- Reader: `/Rotate 90` + CropBox 페이지의 highlight/note/iPad ink overlay, 확대·창 회전/크기 변경 후 좌표 유지, 읽던 위치 복구, 서버 PDF 검색과 페이지 이동.
- Tutor: 한국어 stream, 검증 출처 링크와 Reader 이동, 취소/재연결, 다른 문서/version 이벤트 거부, annotate 제안 승인 전 미저장.
- 학습/설정: Quiz 제출 및 Assessment 오류, 실제 Memory review/Mastery/Progress 상태, settings revision conflict, 설정 API 실패, credential mask만 렌더링.

이 검증은 실제 브라우저+통합 서버가 있어야 완료할 수 있다. fixture나 개발 server의 가짜 응답으로 제품 인수를 주장하지 않는다.

## UNIT-05 구현 및 검증 기록 (2026-10-09)

- 구현: `features/mnemosyne/register.ts`는 계약 API/등록 어댑터를 제공하고 화면은 새 UNIT-05 소유 경로 `features/mnemosyne/screens.tsx`에 둔다. 한국어 Library/Reader/학습/Quiz/Tutor/설정 UI를 기존 PDF.js, annotation layer, native `/ws` stream client, shared `apiFetch`/browser storage 경계에 연결했다. 외부 AI credential은 브라우저 저장소나 화면 상태에 유지하지 않는다.
- 라우팅: 루트는 `/learning/reading`으로 보내고 개인용이 아닌 레거시 경로는 호환 redirect한다. same-origin proxy가 `/v1/*`와 `/ws/*`를 backend로 전달한다.
- PASS: `npm --prefix upstreams/DeepTutor/web run contracts:check`; `typecheck`; `test:node` (1304 tests); `test:unit` (146 files, 653 tests); `build` (Next.js compile, TypeScript, 44 static pages). 처음 동시 실행에서 4개가 실패했다(2개 timeout, Task Board 1개, 이전 Practice 제목 assertion 1개). build 종료 후 timeout/Task Board 포함 영향 경로 4개 파일이 15/15 통과했고, Practice assertion을 새 Mnemosyne 학습 화면에 맞춘 뒤 전체 653개도 재실행해 통과했다.
- 차단: `python3 checks/validate_contracts.py --require-ready`는 현재 Python runtime에 `jsonschema`가 없어 검사하지 못했고 requirements를 설치하라는 메시지를 반환했다. 최초 sandbox build는 Google Fonts 네트워크 제한으로 진행되지 않았으나 승인된 network-enabled retry는 통과했다.
- 제품/기기 미검증: `deeptutor/api/main.py`에서 library router를 mount하지 않은 상태라 실제 `/v1` API, pairing cookie, readiness, learning/review, quiz/turn 조회, parse retry, cross-device reading position 및 실제 stream/annotation flow를 통합 서버에서 검증하지 못했다. iPad/browser device verification도 미실행이다. 이 결과로 `product_ready` 또는 cloud publication 상태를 올리지 않는다.

## UNIT-02 목적별 모델 UI 후속 (2026-10-09)

- `/settings`의 Mnemosyne 화면에 UNIT-02가 추가한 `mnemosyne_chat`, `mnemosyne_reading`, `mnemosyne_quiz`, `mnemosyne_assessment`, `mnemosyne_mastery`, `mnemosyne_solve` 각각의 모델 선택기를 연결했다. 현재 대화 모델을 쓰는 `inherit` 선택을 기본으로 보여주며, catalog에 저장된 LLM/task 모델을 고르면 기존 `/api/settings/apply/registry`에 저장하고 서버 확인·실패 상태를 화면에 표시한다. 일반 Task Models 화면에도 여섯 목적의 이름·설명과 `Follow the chat model` 기본 선택을 반영했다.
- 기존 `Ink annotations` 번역 키 누락을 en/zh/de/pl에 추가해 strict locale audit를 통과시켰다.
- PASS: `typecheck`; `contracts:check`; `test:node` 1,304/1,304; `i18n:check`; `build` (Next.js compile 5.3분, TypeScript 완료, 44 static pages); 최신 UNIT-01 library/citation fixture 5개 (5 passed, 6 warnings).
- 주의: `test:unit`은 146개 파일 중 142개 통과, 653개 중 649개 통과, 4개 실패했다. `tests/i18n-audit.spec.ts`, `tests/question-bank-picker.spec.tsx`, `tests/usage-statistics.spec.tsx`는 5초 timeout, `tests/task-board.spec.tsx`는 `Task note` textbox 조회 실패였다. 이는 전체 UNIT-05 UI 회귀 통과로 보고하지 않는다.
- 실제 브라우저 설정 round-trip은 확인하지 못했다. 현재 `deeptutor/api/main.py`는 bootstrap service만 lifespan에 등록하고 Library REST router를 mount하지 않는다. `integration/registry.json`은 `product_ready: false`, cloud access는 `local_only_no_origin` 상태다.
