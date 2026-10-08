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

### 재개 작업 결과

- 이제 `api/routers/unified_ws.py`가 lifespan에 등록된 `app.state.mnemosyne.tutor`를 사용해 native protocol 2.0의 turn 시작·cursor 재구독·취소를 처리한다. turn ID와 sequence는 upstream 저장 이벤트를 그대로 쓴다. 등록된 tutor가 없을 때의 기존 fallback도 남아 있다. route fixture는 한국어 기본값, start, `resume_from(seq=7)`, cancel 라우팅을 확인한다.
- `TaskKind`에 `mnemosyne_chat`, `mnemosyne_reading`, `mnemosyne_quiz`, `mnemosyne_assessment`, `mnemosyne_mastery`, `mnemosyne_solve`를 추가했다. 기존 `/api/settings`의 동적 `task_kinds`와 task model catalog override를 재사용한다. 각 목적을 명시적으로 고르지 않으면 현재 turn의 모델을 계속 사용하고, 선택한 목적에만 task-service 모델을 적용한다. 별도 비밀값 저장소나 클라이언트 credential 필드는 추가하지 않았다. 평가 WebSocket도 assessment 목적 override와 그 모델의 vision 지원을 사용한다. 다만 현재 judge 입력은 클라이언트가 `correct_answer`/`explanation`을 보낼 수 있고 결과를 durable Assessment로 저장하지 않으므로, 새 quiz attempt 채점 API로 간주할 수 없다.
- 설정 API 데이터에는 목적 ID가 추가됐지만 제품 UI의 현지화 이름/도움말은 검증하지 않았다. 현재 TaskModelsWorkspace는 미등록 ID를 그대로 표시하고, 목적별 기본값을 “전역 task 모델 사용”이라고 표시한다. UNIT-05는 위 6개 ID의 한국어 라벨/설명을 추가하고, 이 6개 목적에는 `inherit` 선택지를 “현재 대화 모델 사용”으로 표시해야 한다. 목적별 미설정/`inherit`는 현재 대화 모델을 유지하고 명시 override만 task model을 쓰도록 화면과 API 동작을 함께 확인해야 한다.
- 사용한 확인은 fixture 범위다. real provider 호출, 브라우저 설정 흐름, 사용자별 catalog 설정 round-trip은 수행하지 않았다.

## 미완료 경계 및 소유자 인수 요청

- 공통 `api/main.py` lifespan 등록 state를 native `/ws`가 소비하기 시작했다. 이는 tutor adapter가 turn 시작/구독/취소 경로에 실제 연결된 fixture 증거이며, 인증된 외부 Mnemosyne REST API, 사용자별 저장소 주입, Origin/Header 경계, 제품 실행 증거는 아니다. 공유 startup/auth 경계는 통합 담당이 소유한다. `build_library_router` 같은 계획된 router/facade를 외부 API 제공 완료로 간주하지 않는다. registry는 source bootstrap 준비 상태이며 `product_ready: false`, Cloud 저장소 접근은 local-only/no-origin이다.
- 현재 bootstrap은 `register_tutor(..., learning_store=None)`로 호출한다. `LearningStateStore`의 실제 durable 구현 및 재시작 보존은 연결되지 않았다. UNIT-01은 quiz 비공개 정답/채점 기준, idempotent attempt, 점수·mastery·memory·progress·activity와 `learning_revision`을 포함하는 저장/트랜잭션 경계를 제공하고 통합 담당은 이를 bootstrap에 주입해야 한다.

### UNIT-01 및 통합 담당 요청 — durable quiz/learning state

- 문제와 immutable quiz version에 기준 답안·부분점수 rubric·해설을 서버 전용으로 저장한다. 공개 quiz/state 응답에 기준 답안이나 rubric을 직렬화하지 않는다. `get_quiz(quiz_id, version_id)` 같은 서버 전용 grading 입력 조회와 채점 결과 제출 경계를 제공한다.
- attempt는 `attempt_id`, `client_mutation_id`, quiz/version, 사용자 답안, 제출 시각, `base_learning_revision`으로 식별한다. 저장 시 canonical payload hash를 함께 기록한다. 동일 mutation ID와 동일 hash의 재전송은 저장된 원 Assessment를 반환하고, 같은 ID에 다른 hash가 오면 conflict를 반환한다. 서버 재시작 뒤에도 이 규칙은 유지한다.
- provider 평가는 DB transaction 바깥에서 수행해 장기 transaction을 피한다. 이후 원자 transaction에서 idempotency/hash와 base revision을 다시 확인하고, attempt, Assessment(`score`, 한국어 feedback, 확인된 citations, 새 `learning_revision`), 근거가 있는 mastery 변화, progress/activity 및 필요한 error/retry 상태를 함께 저장한다. revision 경합은 상태 변경 없이 conflict로 반환한다. 저장된 성공 Assessment는 재시도에서 다시 채점하지 않는다. 단순 대화 횟수만으로 mastery를 올리지 않는다.
- `get_state`, `submit_attempt`, `save_activity`, `review_memory`는 사용자 분리와 revision 검사를 적용한다. review/attempt/activity 실패가 일부 progress만 기록하는 상태를 만들지 않도록 transaction fixture를 제공한다.
- Fixtures는 공개 응답의 rubric 비노출, 중복 replay, 같은 ID/다른 payload conflict, base revision 경합, 재시작 replay, provider 실패, 다중 사용자 격리, citation 검증 실패를 다룬다. 실제 사용자 문서·자격증명·정답 rubric을 로그나 fixture에 넣지 않는다.

### UNIT-01 및 통합 담당 요청 — Reading citation 및 annotation

- Library document/version을 서버 ReadingStore material/revision으로 해석하고, quote와 TextAnchor를 해당 immutable revision의 원문과 대조하는 consumer bridge가 필요하다. 변환된 인용은 citation service가 검증한 것만 assessment 및 읽기 응답에 붙인다.
- `ReaderAnnotateTool`의 기존 `ReadingStore.save_annotation` 직접 쓰기를 durable mutation confirmation/outbox와 연결할 경계를 정한다. 사용자의 명시적 요청, 문서 revision, 확인 응답, 재전송 중복 처리를 검증한다. 그 경계가 제공되기 전까지 현재 tool을 확인된 Mnemosyne annotation API라고 보고하지 않는다.

### 통합 담당 계약 제안

- 현재 계약은 0.1.0이다. quiz version/attempt/Assessment 또는 citation event의 안정된 shape를 외부 소비자에게 노출해야 한다면 additive 0.2.0 제안으로 `contracts/`, fixture와 validator를 함께 갱신해 달라. 소비자는 DeepTutor TutorAdapter/API, Pumice iPad reader, UNIT-05 web, contract fixture/검증기다. 이 변경은 UNIT-02가 직접 계약 복사본에 반영하지 않는다.
- 목적별 provider 선택은 이번 구현에서 기존 `/api/settings` task-model API와 catalog를 재사용하므로 Mnemosyne credential contract를 새로 추가하지 않았다. 별도 `/v1/settings` 또는 계약상 목적별 설정이 필요하다고 판단되면 public response에는 catalog reference만 노출하고 비밀값을 제외하는 additive 계약/권한/fixture 제안을 통합 담당이 결정해야 한다.
- UNIT-01의 LibraryAdapter에는 citation verification과 annotation mutation API가 있으나, Tutor 경로에 document/version ↔ ReadingStore material/revision 해석 consumer가 연결되지 않았다. UNIT-01에 검증된 reader-material resolver/verified citation bridge를 요청한다. UNIT-02 `ReaderAnnotateTool`은 명시 요청과 quote 검증을 거치지만 현재 `ReadingStore.save_annotation`으로 즉시 기록한다. Mnemosyne mutation confirmation/outbox로 연결된 것으로 보고하지 않는다. UNIT-01과 통합 담당이 resolver 및 mutation 경계를 정한 뒤 UNIT-02 reader tool consumer를 갱신해야 한다.
- native turn start/subscription/cancel과 purpose model scope는 source fixture로 확인했다. durable `learning.updated`, verified citation event, user-isolated learning store, mounted external Mnemosyne API와 real provider/model credentials는 제품 경계에서 검증되지 않았다. per-action model scope는 native request contract 변경 없이 existing settings API에서 읽는다.
- `tests/reading/test_capability.py`의 기존 assertion은 과거의 bare goto 및 검증되지 않은 quote 이동/annotation 저장 동작을 전제로 할 수 있다. 현재 `integration/ownership.json`상 UNIT-01 소유이므로 UNIT-01이 해당 fixture를 갱신해야 한다. UNIT-02는 이 파일을 수정하지 않았다.

## 이번 checkpoint 검증

- 임시 `DEEPTUTOR_HOME`과 uv 의존성 런타임으로 다음 6개 파일을 실행: `deeptutor/learning/tests/test_prompt_language_fallback.py`, `tests/api/routers/test_quiz_judge_unit.py`, `tests/runtime/test_lazy_builtin_catalogs.py`, `tests/api/test_unified_ws_turn_runtime.py`, `tests/multi_user/test_learning_reading_turns.py`, `tests/services/test_task_models.py` — **129 passed, 4 warnings**. Quiz provider 호출은 mock이며 실제 provider 호출은 없었다.
- 이 결과는 fixture/unit 수준이다. DeepTutor 제품 설치/build, 인증/Origin을 포함한 mounted API, citation UI, server restart replay, provider credentials, iPadOS simulator/device는 검증하지 않았다.
- 정확한 committed owner map에서 `docs/handoffs/unit-02.md`는 배정되지 않았고 새 경로는 통합 담당이 소유권에 추가해야 한다. 이 checkpoint는 배정된 `handoff/UNIT-02.md`에 기록했다.
- UNIT-02 변경 파일에 한정한 `git diff --check`는 통과했다. 이번 checkpoint에서 바뀐 Python 7개 파일은 `compile()` 기반 문법 검사에 통과했다. `python3 -m py_compile`은 macOS Python 3.9가 workspace 밖 `~/Library/Caches/...`에 bytecode cache를 쓰려다 권한 오류로 중단되어, bytecode 생성 검사는 수행하지 못했다.
