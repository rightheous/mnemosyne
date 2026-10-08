# UNIT-02 인수 경계

담당: Tutor runtime/API·한국어 prompt·필수 학습 서비스. 공통 시작 tag `mnemosyne-bootstrap-v0.1.0`, 계약 `0.1.0`.

실제 등록 경로: `upstreams/DeepTutor/deeptutor/mnemosyne/tutor.py` · `register_tutor`. docs/INTEGRATION.md의 signature와 callers를 읽는다.

외부 reading/quiz/mastery/solve를 immersive_reading/deep_question/mastery_path/deep_solve로 매핑. Chat, Reading, Quiz/Assessment, Mastery, Deep Solve, Memory, Progress/Review 모두 이번 범위. native /ws v2 하나, persisted metadata.mnemosyne, exact citation verify 후 Reader 명령. 개인 auth/Origin/header 보호 및 query secret 금지. learning services를 ports.py에 구현하고 DB 명세를 01에 전달.

현재 common seam/fixture가 있다는 것은 제품 구현 완료가 아니다. 빈 port를 success/no-op으로 채우지 않는다. 필수 기능은 모두 이번 범위다.

정확한 수정 가능 파일 1738개는 integration/ownership.json의 owners.UNIT-02 배열이다. 주요 directory는 OWNERSHIP.md 참조. 다른 소유자의 공통 startup/계약/DB/manifest 파일을 편집하지 않는다.

새 계약 변경은 소비자 영향·version·fixture·검증 변경을 포함해 통합 담당에게 제안한다. DB 요구는 schema/migration/transaction/검증 명세로 01에 전달한다. 사용자 지시 없이 다른 채팅에 메시지를 보내지 않는다.

인수 결과는 실행한 명령·실제 source/service/build/device 종류·실패/차단을 구별하고 기록한다. 공통 fixture PASS를 제품 오프라인/LLM/기기 검증으로 대체하지 않는다. 원본 hash, 잘못된 인용 거부, replay/cancel/error와 재시작 저장을 실제 경계에서 확인한다.

## 구현 checkpoint — 2026-10-09

계약은 계속 0.1.0이다. UNIT-02 소유 경로에서 다음 구현과 fixture를 추가했다.

- `tutor.py`는 chat/reading/quiz/mastery/solve를 DeepTutor capability에 매핑하고, 클라이언트 mutation UUID·문서 UUID·전체 `sha256:` 버전을 검증한다. Reading은 서버가 확인한 ReadingStore material ID/revision을 요구한다. 클라이언트 selection quote는 확인 전 native viewport에 전달하지 않는다. 응답 언어와 문서 언어를 분리하고 선택형 Skills/MCP는 명시적으로 비운다.
- TutorAdapter가 native turn 시작, 순번 cursor 구독/재개, idempotent cancel, 학습상태/attempt/activity/memory 호출을 감싼다. durable LearningStateStore가 없으면 학습상태 호출은 실패한다.
- native `/ws` 프레임 안에 같은 `turn_id`/`seq`를 쓰는 semantic extension을 기록한다. allowlist capability의 시작과 content delta, failed/cancelled 완료를 변환한다. 성공 `turn.done`은 `summary_ko`와 양수 `learning_revision`이 native DONE metadata에 있을 때만 발행한다. 현재 실행 조립은 그 learning revision을 제공하지 않아 성공 종료 semantic event는 검증되지 않았다.
- 한국어 tutor/mastery/quiz prompt, 명시적 사용자 주석 요청 gate, reader goto의 정확한 인용 확인 실패 시 이동 거부를 추가했다.

## 미완료 경계 및 소유자 인수 요청

- 공통 `api/main.py` lifespan은 `register_mnemosyne`을 `app.state.mnemosyne`에 등록하지만, 현재 소스에서 그 state를 사용하는 Mnemosyne API/turn 경로는 찾지 못했다. 공유 assembly와 auth/Origin/Header 경계는 통합 담당이 실제 consumer를 연결해야 한다. `build_library_router` 같은 계획된 router/facade 존재를 외부 API 제공 완료로 간주하지 않는다. registry도 source bootstrap 준비 상태이며 `product_ready: false`, Cloud 저장소 접근은 local-only/no-origin이다.
- 현재 bootstrap은 `register_tutor(..., learning_store=None)`로 호출한다. `LearningStateStore`의 실제 durable 구현 및 재시작 보존은 연결되지 않았다. UNIT-01은 quiz 비공개 정답/채점 기준, idempotent attempt, 점수·mastery·memory·progress·activity와 `learning_revision`을 포함하는 저장/트랜잭션 경계를 제공하고 통합 담당은 이를 bootstrap에 주입해야 한다.
- UNIT-01의 LibraryAdapter에는 citation verification과 annotation mutation API가 있으나, Tutor 경로에 document/version ↔ ReadingStore material/revision 해석 consumer가 연결되지 않았다. UNIT-01에 검증된 reader-material resolver/verified citation bridge를 요청한다. UNIT-02 `ReaderAnnotateTool`은 명시 요청과 quote 검증을 거치지만 현재 `ReadingStore.save_annotation`으로 즉시 기록한다. Mnemosyne mutation confirmation/outbox로 연결된 것으로 보고하지 않는다. UNIT-01과 통합 담당이 resolver 및 mutation 경계를 정한 뒤 UNIT-02 reader tool consumer를 갱신해야 한다.
- native turn 경로, 인증된 Mnemosyne API 소비자, citation verified event, `learning.updated` event, provider/model 설정 연결은 제품 경계에서 검증되지 않았다. `register_tutor`의 API 단독 fixture는 운영 경로 통합 증거가 아니다. per-action model 선택은 0.1.0 요청 계약에 없으므로 필요한 경우 소비자 영향·새 버전·fixture·검증을 적어 통합 담당에게 계약 제안한다.
- `tests/reading/test_capability.py`의 기존 assertion은 과거의 bare goto 및 검증되지 않은 quote 이동/annotation 저장 동작을 전제로 할 수 있다. 현재 `integration/ownership.json`상 UNIT-01 소유이므로 UNIT-01이 해당 fixture를 갱신해야 한다. UNIT-02는 이 파일을 수정하지 않았다.

## 이번 checkpoint 검증

- 임시 `DEEPTUTOR_HOME`과 uv 의존성 런타임으로 다음 5개 파일을 실행: `deeptutor/learning/tests/test_prompt_language_fallback.py`, `tests/api/routers/test_quiz_judge_unit.py`, `tests/runtime/test_lazy_builtin_catalogs.py`, `tests/api/test_unified_ws_turn_runtime.py`, `tests/multi_user/test_learning_reading_turns.py` — **110 passed, 4 warnings**. Quiz provider 호출은 mock이며 실제 provider 호출은 없었다.
- 이 결과는 fixture/unit 수준이다. DeepTutor 제품 설치/build, 인증/Origin을 포함한 mounted API, citation UI, server restart replay, provider credentials, iPadOS simulator/device는 검증하지 않았다.
- UNIT-02 소유 파일에 한정한 `git diff --check`는 통과했다. Python 16개 파일의 소스는 `compile()` 기반 문법 검사에 통과했다. `python3 -m py_compile`은 macOS Python 3.9가 workspace 밖 `~/Library/Caches/...`에 bytecode cache를 쓰려다 권한 오류로 중단되어, bytecode 생성 검사는 수행하지 못했다.
