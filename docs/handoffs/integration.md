# Mnemosyne integration handoff

통합 브랜치 `codex/mnemosyne-integration`은 PR 기준 `main`
`16130d21410d1b2349ffee0757d44462c899ebbf`에서 분기했다. 공통 준비 commit은
`5715a32927e3a73dc28782d306880e3dd1f62441`이다. 아래 여섯 unit SHA가 모두
현재 통합 브랜치의 조상임을 확인했다. 기본 브랜치에 직접 반영하지 않았다.

## 입력 unit과 적용 결과

| Unit | 정확한 결과 | 통합 결과 |
|---|---|---|
| UNIT-01 | `codex/unit-01-library-sync` · `c1f1f16b1cf12c9e66da1b3f24755cdb1412550f` · [Draft PR #2](https://github.com/rightheous/mnemosyne/pull/2) | immutable PDF Library, subject/document API, parse/search/citation/annotation/export 서비스를 서버 lifespan이 만드는 실제 Library 인스턴스에 연결했다. |
| UNIT-02 | `codex/unit-02-learning-api` · `e024f81209a15b81630a5ab169013bdb868320d9` · PR 없음 | 퀴즈 조회·응시, learning state, Memory review, progress 경로를 실제 Tutor adapter와 연결했다. `/v1`는 pairing 인증, Origin, contract version 검사를 한다. |
| UNIT-03 | `codex/unit-03-reader` · `ae202f0cf1096d5fcc0ab1ecd325ac20a0d8e4b1` · PR 없음(사용자 요청) | 원본 hash 검증 cache, persistent Reader facade, Pencil sidecar, tombstone/outbox/cursor/receipt 복구를 UNIT-04 app 조립에 연결했다. |
| UNIT-04 | `codex/unit-04-ipad-app` · `ced01afba5138598601c3b25933329d23a41282b` · [Draft PR #3](https://github.com/rightheous/mnemosyne/pull/3) | iPad app composition, paired API, native `/ws`, local Reader, library/study/settings 화면을 실제 service에 연결했다. 통합 수정으로 progress와 퀴즈 생성·응시 및 Memory review 재전송 식별자를 기기에 보존한다. |
| UNIT-05 | `codex/unit-05-api-refresh` · `e22a0e9d421adf3020e5359dcbda541e5ba378e0` · [Draft PR #4](https://github.com/rightheous/mnemosyne/pull/4) | Web Reader/Tutor/API와 PDF geometry를 연결했다. Tutor는 버전 계약 envelope와 검증할 selection을 전송하며, quiz/progress 재시도는 durable browser storage의 같은 mutation ID를 사용한다. |
| UNIT-06 | `codex/unit-06-cloud-status` · `e14c599cb9977a41f5f17358a9ca17f33bce2327` · [Draft PR #1](https://github.com/rightheous/mnemosyne/pull/1) | Compose/CI 설정을 통합했다. Compose는 `MNEMOSYNE_ALLOWED_ORIGINS`를 backend로 전달한다. |

UNIT-02는 제공된 전용 브랜치/commit으로 통합했고 PR 링크는 제공되지 않았다. UNIT-03은 사용자 요청대로 PR을 만들지 않았다. UNIT-01/#2, UNIT-04/#3, UNIT-05/#4, UNIT-06/#1은 각각 별도의 열린 초안 PR로 남아 있다. 통합 결과는 [Draft PR #5](https://github.com/rightheous/mnemosyne/pull/5)에서 검토한다.

## 실제 연결 경로

- `deeptutor/api/main.py` lifespan이 process container에 `register_mnemosyne`를 한 번 호출해 Library, Tutor, SQLite 학습 저장소, provider runtime, quiz generator를 구성한다. Library HTTP router는 같은 Library 인스턴스를 사용한다. `/ws` native protocol은 교체하지 않았다.
- 웹과 iPad는 `config.mnemosyne.turn_request` envelope를 native `/ws`에 넣는다. 서버는 document/version/page, 선택 anchor와 응답 언어를 검사한다. Reading material ID/revision은 브라우저나 기기가 주지 않고, immutable Library document version에서 서버가 조회한다. 선택 인용은 Library citation verifier로 다시 검증한다.
- 웹과 iPad가 재접속 때 쓰는 `GET /v1/tutor/turns/{turn_id}` receipt route도 실제 Tutor adapter에 등록했다. 영속 turn/event log와 `turn.started` 언어 이벤트에서 receipt를 만들며, route는 pairing bearer 및 contract version guard를 통과해야 한다. 이 route는 OpenAPI의 계획 표식만 있던 연결 결함을 해결한다.
- `SQLiteMnemosyneLearningStore`는 Library와 같은 개인 runtime data root 아래에 quiz, private grading input, attempt, assessment, mastery, Memory, progress와 activity를 transaction으로 저장한다. schema version은 2다. Memory/assessment 상태를 process memory에만 두지 않는다.
- quiz generator는 실제 parsed page에서 문항을 만들고 source quote를 재검증한 뒤 공개 퀴즈와 private grading 자료를 분리 저장한다. 생성·attempt ID와 payload digest를 보존해 재전송 시 중복 레코드를 막는다.
- progress API는 parsed page/version 검증 후 실제 Reader 이벤트와 측정 시간을 저장한다. SQLite는 mutation ID 재전송을 멱등 처리하고 stale revision을 거부한다. 웹과 iPad는 요청 식별자 및 payload를 재전송 전에 저장한다. iPad progress queue는 같은 SHA를 가진 서로 다른 document ID를 구별한다.
- OpenAI-compatible provider 설정은 guarded Settings API를 통해 서버에만 저장한다. API key를 공개 settings 응답에 싣지 않는다. RAG indexing은 DeepTutor의 실제 knowledge initializer/parser/index를 사용하며 ready를 추측해 응답하지 않는다.
- UNIT-03 facade/outbox는 UNIT-04 app에 실제 조립되어 있다. 원본 PDF는 읽기 전용 cache에 hash 검증 후 설치하고, 주석/필기는 별도 sidecar로 기록한다. export는 파생 PDF다.
- contract `0.2.0`에 퀴즈 생성·progress DTO와 fixture를 추가했다. OpenAPI, web/Swift consumer, 세 계약 사본을 함께 갱신했다. `checks/sync_contracts.py`에서 두 downstream copy의 12-file bundle을 확인한다.
- `integration/ownership.json`은 모든 changed files의 단독 owner를 기록한다. 신규 progress/quiz fixture도 각 downstream contract copy와 함께 INTEGRATOR 소유다. upstream original hash는 `integration/upstreams.json`에 예외 및 현재 digest로 남긴다.

## 필수 기능 구현 / 검증 상태

| ID | 구현 상태 | 이 통합 실행기에서의 검증 상태 |
|---|---|---|
| R01 Library·과목·PDF upload/delete/read | 실제 guarded route, SQLite/ReadingStore 보존, PDF upload/download 및 삭제 경로 연결 | loopback HTTP로 pairing·upload·2쪽 parse·search·verified citation을 실행했다. 원본 PDF SHA도 export 전후 보존됐다. |
| R02 iPad Reader·선택·검색·위치 복구 | hash 검증 cache와 persistent Reader facade/app callback 연결 | web PDF.js fixture 2쪽 검사 통과. 실제 browser selection 및 iPad build/reopen은 미검증. |
| R03 Pencil·undo/redo·geometry | PDFKit/Pencil sidecar 및 canonical CropBox/rotation geometry 경로 연결 | geometry fixture 4개 통과. Apple SDK와 실제 Pencil 입력은 미검증. |
| R04 주석·필기·tombstone·export | durable sidecar/outbox, sync receipt/cursor, server mutation/export 연결 | loopback HTTP annotation retry, 삭제 tombstone, derived export, SQLite reopen, 원본 SHA 불변을 확인했다. 실제 iPad sidecar sync는 미검증. |
| R05 offline/outbox/retry | 서버 원본 cache 및 기기 durable annotation/progress/quiz/review queue 연결 | SQLite progress retry/reopen과 turn/quiz mutation replay 검사를 통과했다. 비행기 모드와 iPad app 재시작·재접속은 미실행. |
| R06 중앙 저장·검색·RAG | PDF/page/annotation Library 저장과 DeepTutor indexing adapter 연결 | 실제 HTTP parse/search/citation은 확인. `llama_index` 부재로 vector index는 `failed`, `ready` 미확인. |
| R07 Tutor·Quiz·Assessment·Mastery·Memory·Progress | Tutor native WS, source quiz generator, SQLite 학습/평가 저장소, API와 web/iPad 진입점 연결 | 기존 targeted pytest run 42개 통과, 별도 durable quiz insert/replay/다른 digest 거부 test 1개 통과. 그 뒤 전체 targeted pytest 재실행은 executor에서 완료되지 않아 최신 전체 suite 재실행 결과는 없다. attempt/assessment/mastery/Memory/progress 저장·reopen은 이전 targeted suite에서 확인했다. 실 LLM 생성과 전체 UI 복구 흐름은 미검증. |
| R08 Mac web 전체 흐름 | Korean Library/Reader/Tutor/Quiz/Learning/Settings 화면과 APIs 연결 | contracts/typecheck/architecture 통과. Node suite 206/209, unit suite 652/656 통과; 남은 subprocess 테스트는 sandbox 제한으로 실패. production build는 Google Fonts fetch에서 중단, 실제 browser E2E 미검증. |
| R09 한국어 UI/Tutor | 응답 언어 `ko`, 원문 인용/수식/코드 보존 지침과 한국어 화면 적용 | receipt와 turn request 언어 경로 및 한국어 화면/계약 검증. live provider 응답 품질은 자격증명 부재로 미검증. |
| R10 검증 출처·Reader targeting | 서버에서 document version/page/quote/citation 재검증 후 명령 전달 | loopback HTTP verified citation, consumer event/geometry fixture 검사 통과. 실제 Reader 화면 선택에서 강조까지는 미검증. |
| R11 Windows WSL2/Docker | 고정 DeepTutor Compose profile 및 origin 전달 연결 | `python scripts/docker_compose.py config --quiet` 통과. daemon socket 권한 거부로 image/build/start 미실행; Windows 복구도 미검증. |
| R12 교체 가능한 OpenAI-compatible LLM | 서버 전용 provider 설정/credential store와 runtime scope 구현 | credential 없는 loopback fake provider transport 검사 통과. 실제 provider/LLM 요청은 미실행. |
| R13 pairing·Origin·오류·readiness | route guards, request/contract headers, degraded readiness, 사용자 오류 경로 구현 | 계약 validator, API adapter tests, pairing/HTTP flow 통과. Python targeted tests는 42 passed. live deployment readiness는 미검증. |
| R14 공통 기준·소유권·계약 | 여섯 exact commit, adapter registry, 단독 ownership, 0.2.0 contract bundle 기록 | 여섯 SHA 모두 통합 HEAD의 조상. 계약 sync 및 validator 통과. |

어떤 필수 기능도 후속 phase로 미뤄졌다고 표시하지 않는다. 다만 코드 연결과 제품 환경 검증은 구분한다. 현재 `product_ready=false`이며, 실행 결과와 blocker는 [docs/VALIDATION.md](../VALIDATION.md)에 기록했다.

## End-to-end 수락 흐름 상태

작은 PDF end-to-end는 **부분 실행**했다. `checks/integration_pdf_flow.py --allow-index-unavailable`의 loopback HTTP 요청은 pairing부터 upload, 2쪽 parse/search, verified citation, annotation retry와 tombstone, export, 원본 SHA 보존, SQLite reopen, progress retry, session revoke/WebSocket bridge까지 통과했다. index 상태는 `llama_index` 부재로 `failed`였다. 따라서 실제 Tutor LLM 답변, Reader의 선택/문장 강조, iPad 필기 sync, 웹에서 복구한 전체 UI와 RAG 기반 quiz 생성은 아직 단일 흐름에서 검증되지 않았다. SQLite 저장소 테스트는 quiz/attempt/assessment/mastery/Memory의 저장·중복 재전송·reopen을 별도 확인했으며, 이를 전체 사용자 흐름 통과로 간주하지 않는다. 실행별 자세한 결과는 [docs/VALIDATION.md](../VALIDATION.md)에 있다.

## 브랜딩 후속 작업

사용자가 제공한 불꽃·청록 원·M 심볼을 1024×1024 PNG로 준비해 iOS `AppIcon`과 웹 `public/mnemosyne-mark.png`에 연결했다. 웹 전역 아이콘 메타데이터와 Mnemosyne 내비게이션 헤더가 같은 자산을 사용하고, 활성 메뉴 색을 심볼의 청록 계열로 맞췄다. `integration/ownership.json`의 세 기존 경로 예외와 `integration/upstreams.json`의 원본 override·신규 통합 자산 digest를 기록했다. 웹 typecheck, consumer fixture, contract/source/ownership 검사는 통과했다. 외부 Google Fonts fetch가 막혀 production build는 계속 미완료이며, 실제 브라우저와 Xcode/iPad 빌드도 이 환경에서 확인하지 않았다.
