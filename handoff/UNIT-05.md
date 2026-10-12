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
5. **Tutor 입력 wire**: native `/ws` protocol 2.0의 `start_turn`은 기존 upstream schema이고 `TurnRequest`(capability, `ReaderContext`, `response_language`)를 싣는 확장 규칙이 명시되지 않았다. HTTP `TurnRequest`는 schema에만 있고 start/turn 생성 route는 없다. 현재 Web은 기존 `/ws` consumer가 실제로 읽는 최상위 capability를 보내고, 읽히지 않는 `config.mnemosyne.turn_request` wrapper는 제거했다. 이 때문에 현재 command에는 문서/version/page/selection context가 없고 실제 문서 Tutor는 아직 동작하지 않는다. 계약 version이 있는 request extension과 stream event 소비를 UNIT-02/통합 담당이 공통 fixture에 확정한 뒤 Web sender를 연결해야 한다. Web/02/API fixture 영향; 제안 `0.2.0`; `chat/quiz/mastery/solve` request round-trip와 document/version-bound stream events를 검사한다.
6. **Web pairing cookie**: `/v1/session/pair` 응답 `PairReceipt`에는 bearer `access_token`이 필수지만 공통 보안 문서는 브라우저 same-origin 보호 cookie와 네이티브 `Authorization`을 요구한다. 현재 upstream `ws_require_auth()`는 query `token` 또는 `dt_token` cookie만 확인하므로 query 금지 규칙 아래에서 WebSocket 인증을 끝내려면 서버가 인식하는 cookie 발급/검증 경로가 필요하다. 웹 pairing이 HttpOnly/Secure/SameSite cookie를 설정하고 JS에는 bearer를 반환하지 않는 경로 또는 응답 분기를 계약에 명시한다. UNIT-02 auth/router와 Web 영향; 제안 `0.2.0`; 쿠키 세션 WebSocket handshake, Origin 거부, token 비노출을 검사한다.

## 현재 소스 조립 상태 재확인 (2026-10-09)

작업 중인 공유 트리에는 UNIT-01/02 서비스 변경도 보이지만 이는 UNIT-05가 수정하지 않는다. UNIT-01의 `build_library_router(library)`는 설정·과목·문서·페이지·검색·인용 검증·주석·export handler를 만들지만, `deeptutor/api/main.py`는 lifespan에서 `app.state.mnemosyne` 서비스만 만들고 이 router를 `include_router`하지 않는다. 따라서 OpenAPI의 planned endpoint는 실제 HTTP 기능으로 광고할 수 없다. 같은 current tree에서 `/v1/readiness`, pairing/revoke, learning state/review, quiz/attempt, tutor turn 조회, parse/index retry, cross-device reader position router는 확인되지 않았다. 이 확인은 정적 소스 대조이며 API 실행 검증은 아니다.

Tutor source도 별도 연결이 필요하다. `unified_ws.py`의 native start 분기는 `TutorAdapter.start_native_turn()`을 호출하고 `native_protocol_turn_request()`는 최상위 native capability를 정규화한다. `TutorAdapter.start_turn()`이 `ReaderContext` 기반 `native_turn_request()`와 server-resolved material 인자를 받지만 `/ws` 분기는 이 진입점을 호출하지 않는다. `reading`은 server material ID/revision 없이는 거부되고 다른 capability도 현재 Mnemosyne document context를 받지 않는다. `auth.py`의 현 `ws_require_auth()`는 query token 또는 upstream `dt_token` cookie만 읽는다. 이 source 상태의 `/ws` handler는 Web cookie·Mnemosyne pairing bearer의 route/auth 통합을 포함하지 않는다.

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
- 라우팅: 루트 페이지는 `/learning/reading`으로 보내며, proxy는 `/learning`, `/learning/reading`, 문서 Reader 경로, `/settings`, 로그인·handoff·callback 및 정적 자산을 유지한다. 나머지 upstream UI 경로는 `/learning/reading`으로 보내며 기존 명시적 폐기 경로 `/partners/groups`는 404로 차단한다. same-origin proxy가 `/v1/*`와 `/ws/*`를 backend로 전달한다.
- PASS: `npm --prefix upstreams/DeepTutor/web run contracts:check`; `typecheck`; `test:node` (1304 tests); `test:unit` (146 files, 653 tests); `build` (Next.js compile, TypeScript, 44 static pages). 처음 동시 실행에서 4개가 실패했다(2개 timeout, Task Board 1개, 이전 Practice 제목 assertion 1개). build 종료 후 timeout/Task Board 포함 영향 경로 4개 파일이 15/15 통과했고, Practice assertion을 새 Mnemosyne 학습 화면에 맞춘 뒤 전체 653개도 재실행해 통과했다.
- 차단: `python3 checks/validate_contracts.py --require-ready`는 현재 Python runtime에 `jsonschema`가 없어 검사하지 못했고 requirements를 설치하라는 메시지를 반환했다. 최초 sandbox build는 Google Fonts 네트워크 제한으로 진행되지 않았으나 승인된 network-enabled retry는 통과했다.
- 제품/기기 미검증: `deeptutor/api/main.py`에서 library router를 mount하지 않은 상태라 실제 `/v1` API, pairing cookie, readiness, learning/review, quiz/turn 조회, parse retry, cross-device reading position 및 실제 stream/annotation flow를 통합 서버에서 검증하지 못했다. iPad/browser device verification도 미실행이다. 이 결과로 `product_ready` 또는 cloud publication 상태를 올리지 않는다.

## UNIT-02 목적별 모델 UI 후속 (2026-10-09)

- `/settings`의 Mnemosyne 화면에 UNIT-02가 추가한 `mnemosyne_chat`, `mnemosyne_reading`, `mnemosyne_quiz`, `mnemosyne_assessment`, `mnemosyne_mastery`, `mnemosyne_solve` 각각의 모델 선택기를 연결했다. 현재 대화 모델을 쓰는 `inherit` 선택을 기본으로 보여주며, catalog에 저장된 LLM/task 모델을 고르면 기존 `/api/settings/apply/registry`에 저장하고 서버 확인·실패 상태를 화면에 표시한다. 일반 Task Models 화면에도 여섯 목적의 이름·설명과 `Follow the chat model` 기본 선택을 반영했다.
- 기존 `Ink annotations` 번역 키 누락을 en/zh/de/pl에 추가해 strict locale audit를 통과시켰다.
- PASS: `typecheck`; `contracts:check`; `test:node` 1,304/1,304; `i18n:check`; final `build` (Next.js compile 2.0분, TypeScript 완료, 44 static pages); 최신 UNIT-01 library/citation fixture 5개 (5 passed, 6 warnings).
- `test:unit` 기본 worker 실행은 146개 파일 중 142개 통과, 653개 중 649개 통과, 4개 실패했다. `tests/i18n-audit.spec.ts`, `tests/question-bank-picker.spec.tsx`, `tests/usage-statistics.spec.tsx`는 5초 timeout, `tests/task-board.spec.tsx`는 `Task note` textbox 조회 실패였다. 이 네 파일을 `--maxWorkers=1`로 다시 실행해 18/18 통과했고, 전체 `test:unit --maxWorkers=1 --reporter=dot`도 146/146 파일·653/653 테스트 통과했다. 따라서 병렬 worker 실행에서는 시간 민감한 기존 fixture 실패가 있었으며 직렬 전체 회귀는 통과했다.
- 수정 TSX 두 파일의 ESLint 검사는 exit 0, 0 errors, 38 `i18n/no-literal-ui-text` warnings였다. Mnemosyne 화면의 한국어 JSX 문구가 이 규칙의 literal UI warning 대상이다.
- 실제 브라우저 설정 round-trip은 확인하지 못했다. 현재 `deeptutor/api/main.py`는 bootstrap service만 lifespan에 등록하고 Library REST router를 mount하지 않는다. `integration/registry.json`은 `product_ready: false`, cloud access는 `local_only_no_origin` 상태다.

## UNIT-05 메뉴·라우팅 후속 (2026-10-09)

- 메뉴를 한국어 `라이브러리`, `학습 기록·복습`, `설정`으로 줄였다. 루트 페이지는 `/learning/reading`을 열고, proxy page allowlist는 `/learning`, `/learning/reading`, 단일 문서 Reader 경로, `/settings`를 보존한다. 기존 채팅·파트너·작업공간·가입·기타 upstream UI 페이지는 Library로 보내며 `/partners/groups`는 기존 retired-route 가드로 404를 유지한다. backend API/WebSocket, callback, 로그인·handoff, 정적 파일은 이 page redirect에서 제외했다.
- PASS: `npm --prefix upstreams/DeepTutor/web run typecheck`; `test:node` 1,307/1,307; 변경된 `sidebar-defaults.spec.tsx`·`learner-navigation.spec.tsx` 2 files / 10 tests; production `build` (44 static pages). 빌드에서 webpack cache snapshot 경고가 있었으나 종료 코드는 0이었다.
- 브라우저 smoke (좌측 rail 변경 전): 로컬 production server 화면에서 `/`와 `/agents`가 `/learning/reading`에 도달했고 Library 및 Settings의 한국어 UI를 렌더링했다. 서버가 없는 상태에서 Library/Settings API가 HTTP 500을 반환하는 오류 UI도 확인했다. 그러므로 실제 PDF→Tutor→Reader 이동, ink overlay, Quiz·설정 성공 round-trip은 여전히 서버 통합에 막혀 검증하지 않았다.
- 빌드는 upstream route module들도 계속 산출물에 포함한다. 런타임 proxy가 allowlist 밖 페이지 요청을 redirect해 제품 진입 경로를 제한하지만, 물리적 route 파일 삭제는 하지 않았다.

## UNIT-05 좌측 탐색 반영 (2026-10-09)

- 공통 Mnemosyne header를 반응형 좌측 rail로 변경했다. 데스크톱 Library에서는 과목을 rail에서 선택하고 과목 추가를 시작할 수 있으며, 작은 화면은 상단 가로 탐색을 유지한다.
- PASS: 변경 후 `typecheck`; `test:node` 1,307/1,307; `sidebar-defaults.spec.tsx`·`learner-navigation.spec.tsx` 2 files / 10 tests; production `build` (44 static pages); `screens.tsx` ESLint 0 errors, 38 `i18n/no-literal-ui-text` warnings. webpack cache snapshot 경고는 있었으나 build 종료 코드는 0이었다.
- 최종 좌측 rail의 브라우저 재확인은 브라우저 접근이 거절되어 실행하지 않았다. 화면 시각 검증은 미완료이며, 위의 이전 smoke는 rail 변경 전 화면에 한정된다.

## UNIT-02 서버 커밋 인수 확인 (2026-10-09)

- 제공된 UNIT-02 source commits `7191750`, `0ed61d3`, `b1d3956`을 이 작업 branch에 cherry-pick했다. 대상 SHA는 각각 `7e7ee28`, `10cde35`, `8e61d58`이며, 현재 branch HEAD는 `8e61d58`이다. 변경 파일은 learning validation/service와 Tutor 및 해당 API runtime fixture이고 UNIT-05 소스는 변경되지 않았다.
- PASS (서버 fixture): `PYTHONPATH=. .venv/bin/python -m pytest -q -ra tests/api/test_unified_ws_turn_runtime.py` — 45 passed, 4 warnings, 4.16s. 이는 runtime fixture 검사이며 실제 서버/API 통합 검증이 아니다.
- PASS (공통 계약 fixture): Python 3.12 임시 `.venv`에서 `checks/validate_contracts.py` — OpenAPI operations 30, schemas 4, schema instances 80, negative cases 19, sync steps 10, geometry cases 4. `--require-ready` 실행은 `docs/handoffs/unit-02.md`가 `integration/ownership.json`에서 미배정으로 검출되어 실패했다. 그 문서는 import된 UNIT-02 commit에 포함됐지만 UNIT-05 소유가 아니므로 이 unit에서 소유권 파일을 변경하지 않는다. gate 없는 PASS 출력은 `ownership_checked=false`, `source_gate_checked=false`였다.
- 환경 제한: 표준 `uv run --extra dev`는 `markitdown[all]`과 `youtube-transcript-api`의 Python 3.14 분기 충돌로 resolve하지 못했다. `requirements/dev.txt`는 Mac에서 FAISS 소스 빌드 중 `swig` 부재로 멈췄다. 타깃 fixture는 `/tmp` 임시 requirement 목록에서 FAISS 항목만 제외한 Python 3.12 환경으로 실행했다. 이 우회는 FAISS 검증이나 표준 전체 dev 환경 준비 성공을 뜻하지 않는다.
- 제품 API, pairing cookie, 파싱/검색/주석 저장, Tutor stream의 브라우저 왕복은 여전히 미검증이다. `deeptutor/api/main.py`에서 Mnemosyne REST router가 mount되지 않은 정적 소스 상태이며 이 파일은 INTEGRATOR 소유다. 최종 좌측 탐색 브라우저 확인도 이전에 거절된 브라우저 접근으로 미완료다. registry의 `product_ready: false`, `cloud_repository_access: local_only_no_origin`을 유지한다.

## UNIT-05 주석 저장 실패 복구 (2026-10-09)

- Reader의 주석 mutation이 거부되면 노트 입력과 Tutor의 승인 대기 제안을 유지해 다시 시도할 수 있게 했다. 서버가 mutation을 적용한 뒤 snapshot 새로고침만 실패한 경우에는 저장 성공과 목록 갱신 실패를 구분해 알리고, 확인된 mutation 기준으로 초안을 정리한다.
- `web/tests/reading-v2-surface.test.ts`에 실패 응답 전에 입력을 닫지 않도록 하는 source regression check를 추가했다.
- PASS: Node 24.19.0 `npm --prefix upstreams/DeepTutor/web run typecheck`; `test:node` 1,308/1,308; `test:unit -- tests/sidebar-defaults.spec.tsx tests/learner-navigation.spec.tsx --reporter=dot` 2 files / 10 tests; `build` (Next.js 16.2.3, webpack, 44 static pages); `i18n:check`; 변경 TSX/test ESLint (0 errors, 38 `i18n/no-literal-ui-text` warnings); `git diff --check`.
- 브라우저 재확인은 앞서 접근이 거절되어 이번에도 실행하지 않았다. 실제 API 호출·실패 후 재시도와 Tutor 제안 저장은 통합 서버에서 검증해야 하며, Mnemosyne REST router가 미등록인 현재 source 상태를 제품 완료 근거로 삼지 않는다.

## UNIT-05 화면 내 입력·확인 대화상자 (2026-10-09)

- Library의 과목 추가/이름 변경/과목 삭제/문서 삭제, Reader 주석 삭제, 설정의 페어링 폐기에 브라우저 기본 `prompt`/`confirm` 대신 한국어 화면 내 대화상자를 연결했다. 공통 대화상자는 제목과 `aria-modal`을 제공하고, Tab focus를 가두며 Escape/바깥 클릭/취소로 닫힌다. 저장·삭제 API 실패 시 입력과 확인 상태를 유지하고 오류를 대화상자 안에 표시한다.
- `web/tests/reading-v2-surface.test.ts`에 Mnemosyne 화면 내 prompt/confirm 금지 및 접근성 대화상자 사용 회귀 검사를 추가했다.
- PASS: Node 24.19.0 `typecheck`; `test:node` 1,309/1,309; `test:unit -- tests/sidebar-defaults.spec.tsx tests/learner-navigation.spec.tsx --reporter=dot` 2 files / 10 tests; production `build` (Next.js 16.2.3, webpack, 44 static pages); 변경 TSX/test ESLint (0 errors, 기존 literal UI text 경고 38개); `git diff --check`. 최초 ESLint에서 render 단계의 ref 갱신 오류가 검출되어 effect 단계로 옮긴 후 최종 lint를 통과했다.
- 최종 UI의 시각 및 키보드 조작은 브라우저 접근 거절로 확인하지 않았다. 서버 API 성공/실패 round-trip은 Mnemosyne REST router가 미등록 상태라 실제 서비스 검증으로 보고할 수 없다. `product_ready: false`, Cloud `local_only_no_origin` 유지.

## UNIT-05 웹/API 실제 경로 재감사 (2026-10-09)

- `npm run contracts:check` PASS는 생성된 TypeScript 계약 산출물이 루트 계약과 일치함을 확인한다. `contracts/openapi.yaml`의 `/v1/*` 28개 operation은 모두 `x-implementation: planned-unit-extension`이므로 이 검사는 server route 등록·동작 확인이 아니다.
- 실제 소스에서 UNIT-01 `build_library_router(library)`는 settings/subjects/documents/pages/search/citation/annotations/export handler를 정의하지만 통합 담당 소유 `deeptutor/api/main.py`는 lifespan에서 `register_mnemosyne`으로 service만 보관한다. `include_router(build_library_router(...))` 호출과 session/readiness, Tutor turn 조회, quiz/attempt, learning/review handler 등록은 확인되지 않았다. native `/ws`만 기존 main에서 별도로 조립되며 이는 Mnemosyne REST 연결 완료를 증명하지 않는다.
- 웹 proxy는 same-origin `/v1/*` 요청을 backend로 전달하지만 대응 route를 만들지 않는다. 이 상태에서 browser client의 Library/Reader/quiz/learning/settings REST 호출은 실제 API가 아니라 FastAPI의 미등록 경로로 향한다. 오류 UI가 404를 노출하는 것은 연결 구현의 대체가 아니다.
- Web pairing 계약 `PairReceipt`는 `access_token`을 응답으로 요구하고 현재 client는 JSON에서 읽은 뒤 버린다. HTTP-only cookie 응답이나 Web 전용 server-side 교환 경로가 없으면 브라우저 JS에 bearer가 전달되며 이후 보호 요청도 인증되지 않는다. 통합 담당은 pairing 응답/경로의 version·소비자 영향과 cookie/Origin fixture를 확정해야 한다.
- 정확한 소유권상 UNIT-05는 `api/main.py`, server router, 계약 및 contract copies를 고칠 수 없다. 통합 요청은 위 실제 mount/handler gap과 Web pairing cookie gap을 포함해 통합 담당에 전달한다. 이 재감사에서 backend files는 편집하지 않았다.
- 현재 branch에는 지정 UNIT-02 커밋 `7191750`, `0ed61d3`, `b1d3956`을 대상 SHA `7e7ee28`, `10cde35`, `8e61d58`로 이미 가져와 있다. runtime fixture 45개 PASS는 해당 fixture 범위이며 REST route mount·실제 HTTP·브라우저 연결 검증이 아니다. git remote가 없으므로 이 branch에서 초안 PR을 만들 수 없다.

## UNIT-05 PDF 주석 geometry fixture 검사 (2026-10-09)

- PDF.js의 표시 CropBox/rotation/userUnit을 계약의 canonical PDF-space anchor와 iPad ink에 적용하는 점·사각형·획 너비 변환을 `register.ts`의 순수 helper로 두고 Reader가 이를 사용하도록 연결했다. 기존 변환과 같은 식을 유지하면서 계약의 예제값으로 직접 검사 가능하게 했다.
- PASS: `npm run typecheck`; `test:node` 1,309/1,309; `test:unit -- tests/pdf-reading-resize.spec.tsx --reporter=dot` 1 file / 9 tests (회전 0/90/180/270, CropBox 사각형, UserUnit 획 너비 포함); production `build` (44 static pages); 변경 TSX/test ESLint (0 errors, 38 existing `i18n/no-literal-ui-text` warnings); `git diff --check`.
- 이 검사는 좌표 수식·fixture 수준이며 PDF.js와 화면의 실제 overlay, 브라우저 줌/창 회전 후 시각 일치는 검증하지 않았다. 브라우저 접근은 앞서 거절되어 재시도하지 않았다.

## UNIT-05 Tutor native command 경계 (2026-10-09)

- `/ws` start 분기는 등록된 Tutor의 `start_native_turn()`을 호출하며 이 경로는 최상위 protocol 2.0 `capability`를 읽는다. 화면이 보냈던 `capability: "chat"`와 `config.mnemosyne.turn_request` 조합에서는 선택한 quiz/mastery/solve action이 소비되지 않고 기본 채팅으로 처리될 수 있어, UNIT-02의 `CAPABILITY_MAP`에 맞게 최상위 native capability를 보낸다. Mnemosyne 요청 wrapper는 native capability `config`에 넣지 않는다.
- `memory`, `progress`, `review`는 UNIT-02 설명대로 native turn capability가 아니므로 `/ws` 채팅으로 전송하지 않는다. 학습 화면의 기존 상태·카드·평가 조작을 안내한다.
- 남은 API 경계: `reading` native turn에는 서버가 확인한 `reading_material_id`와 `reading_material_revision`이 필요하다. UNIT-05 문서 DTO에는 이 식별자가 없고 `/ws` handler도 `TutorAdapter.start_turn()`의 server resolver 경로를 호출하지 않는다. 웹 파일을 통한 추정 매핑은 하지 않았다. PDF context·검증 인용이 native turn에 도달하는 adapter/server route를 통합 담당이 연결하기 전에는 실제 문서 Tutor 성공으로 보고할 수 없다.
- PASS: Node 24.19.0 `npm run typecheck`; `npm run test:node` 1,310/1,310; production `npm run build` (Next.js 16.2.3, 44 static pages); 변경 파일 ESLint 0 errors, 기존 `i18n/no-literal-ui-text` warning 38개; `git diff --check`.
- 이 검증은 client mapper/source와 빌드 fixture다. 실제 `/ws` 요청·서버 capability 실행·현재 PDF context/검증 인용 전달은 미검증이며 server resolver/router 통합이 필요하다.

## 원격 저장소 확인 (2026-10-12)

- `origin`은 `https://github.com/rightheous/mnemosyne.git`로 설정되어 있고, 원격 `main`은 이 작업의 기준 `origin/main`과 같은 `16130d21410d1b2349ffee0757d44462c899ebbf`임을 확인했다.
- 이 확인은 GitHub 원격 접근만 뜻하며 Cloud 게시나 제품 인수 완료를 뜻하지 않는다. `integration/registry.json`의 준비/Cloud 상태는 통합 담당 소유라 UNIT-05가 수정하지 않는다.

## 기준 브랜치에서 다시 확인 (2026-10-12)

- 공통 준비 tag `mnemosyne-bootstrap-v0.1.0`은 `5715a32927e3a73dc28782d306880e3dd1f62441`을 가리킨다. 새 UNIT-05 검토 branch는 최신 로컬/원격 `main` `16130d21410d1b2349ffee0757d44462c899ebbf`에서 시작했다.
- `Node 24.19.0`: `npm run typecheck` PASS; `npm run test:node` 1,310/1,310 PASS; `npm run test:unit -- --maxWorkers=1 --reporter=dot` 146 files / 656 tests PASS; `npm run build` PASS (Next.js 16.2.3, static pages 44). Sidebar navigation의 제거된 `/chat` entry 참조를 guard하고 기존 History 테스트를 현재 한국어 Library navigation에 맞춘 뒤 전체 단위 검사를 통과했다.
- `npm ci`는 lockfile대로 945 packages를 설치했다. 설치 시 환경 기본 Node 20의 engine 경고가 있었으나 검사는 Node 24.19.0으로 실행했다. npm 설치 감사 요약은 28 findings (5 low, 7 moderate, 15 high, 1 critical)였으며 dependency나 lockfile은 바꾸지 않았다.
- 모든 PASS는 fixture·typecheck·제품 build 범위다. 실제 REST router/pairing-cookie/Tutor document-context 통합, 실제 브라우저의 Library→PDF→Tutor 동선 및 기기 확인은 미검증이고 서버/통합 담당 작업에 의존한다.
