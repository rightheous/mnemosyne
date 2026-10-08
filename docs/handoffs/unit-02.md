# UNIT-02 Korean Tutor 및 학습 엔진 인수 명세

작성일: 2026-10-09

공통 contract: `0.1.0`

공통 준비 상태: `integration/registry.json` 기준 `product_ready: false`

상세 진행 기록: [`handoff/UNIT-02.md`](../../handoff/UNIT-02.md)

## 현재 상태와 적용 범위

이 문서는 사용자 요청에 따라 DB, API, contract, dependency 경계와 소유자별 패치 제안을 모은다. `integration/ownership.json`에는 이 문서 경로가 아직 배정되지 않았다. 통합 담당은 다음 통합 기준선에서 `docs/handoffs/unit-02.md`를 담당 경로에 등록해야 한다. 기존 담당 경로를 수정하지 않고 명세 인수에 사용한다.

현재 UNIT-02 구현은 DeepTutor native `/ws` protocol 2.0 tutor route, 목적별 모델 선택, Attempt/MemoryReview 입력 검증, public Quiz/Assessment/LearningState 출력 검증을 포함한다. contract는 `0.1.0`이고 `/v1/*` 경로는 `contracts/openapi.yaml`에서 `planned-unit-extension`으로 표시된다. `TutorAdapter`가 등록된다는 사실은 해당 HTTP API가 mount됐거나 제품 기능이 완료됐다는 뜻이 아니다.

`TutorAdapter.get_quiz`는 현재 `LearningStateStore.get_quiz`를 duck-typing으로 요구하지만, 통합 담당 소유 `mnemosyne/ports.py`의 Protocol에는 아직 이 메서드가 없다. `LearningStateStore` 주입도 bootstrap에서 `None`이다. 따라서 durable quiz/learning 기능과 `product_ready`는 미완료다. `get_learning_state`는 요청 버전과 저장 상태 버전을 비교하지만, 현재 port의 `get_state(document_id)` 입력에는 version이 없으므로 DB adapter가 문서·버전 조회 경계를 명확히 제공해야 한다.

현재 TutorAdapter 메서드에는 authenticated principal 인자가 없다. 통합 담당은 사용자별 store adapter를 요청 범위에 묶거나 검증된 principal을 Unit02 service/port에 명시 전달해야 한다. UUID 추측 불가성만으로 사용자 격리를 대체할 수 없다.

## 소유자별 변경 제안

| 소유자 | 변경 책임 | 파일 경계 |
|---|---|---|
| 통합 담당 | Store port 메서드·반환 의미, bootstrap 의존성 주입, 인증된 router 조립, API error/version header 계약 및 contract snapshot 생성 | `deeptutor/mnemosyne/ports.py`, `mnemosyne/bootstrap.py`, `api/main.py`, `app/container.py`, 공유 router 조립, 루트 `contracts/`와 생성 복사본 |
| UNIT-01 | SQLite schema/migration, user/document/version scope, 예약·commit·revision CAS, 상태·attempt·activity의 atomic persistence 및 restart replay | `deeptutor/learning/storage.py`, `learning/migration.py` 및 지정된 DB 소유 파일 |
| UNIT-02 | 한국어 tutor와 채점/학습 orchestration, private rubric을 이용한 provider 평가, DTO·citation 검사, 저장 결과를 소비하는 service | `deeptutor/learning/service.py`, `learning/assessment.py`, `deeptutor/mnemosyne/tutor.py`, UNIT-02 배정 router 및 prompt 파일 |
| UNIT-05 | 6개 tutor purpose의 한국어 라벨·도움말과 현재 대화 모델 상속 UI | 배정된 DeepTutor web feature/UI 경로 |
| UNIT-06 | 실제 신규 runtime dependency가 필요할 때 Python manifest, lock, container 및 CI 반영 | backend dependency/manifest 소유 파일 |

`mnemosyne/ports.py`, bootstrap, main/container, 계약 원본과 generated `MnemosyneContracts`는 UNIT-02가 직접 수정하지 않는다. DB patch는 UNIT-01에, 공유 port/API/contract patch는 통합 담당에 전달하고 각 구현은 담당자가 자기 소유 경로에서 반영한다.

## 현재 contract와 API 경계

기존 `contracts/models.schema.json`에 필요한 주요 payload가 이미 정의되어 있다.

| DTO | contract `0.1.0` 필드 및 경계 |
|---|---|
| `Quiz` | `quiz_id`, `document_id`, 전체 `sha256:` `version_id`, `title`, `questions`, `response_language`. 공개 Question에는 prompt/kind/choices/verified citations만 들어간다. 정답과 rubric은 Quiz 및 일반 API 응답에 포함하지 않는다. |
| `Attempt` | `attempt_id`, `client_mutation_id`, `quiz_id`, `document_id`, `version_id`, `base_learning_revision`, `submitted_at`, 비어 있지 않은 question answer 배열. |
| `Assessment` | `attempt_id`, `[0,1]` score, 한국어 `feedback_ko`, 양수 `learning_revision`, 하나 이상의 `VerifiedCitation`. |
| `LearningState` | document/version/revision, quiz attempts, mastery 및 근거 attempt ID, memory와 citation, progress, activities. 전체 public state에서 rubric/answer key를 제외한다. |
| `MemoryReview` | `client_mutation_id`, `memory_id`, `base_learning_revision`, 0–3 grade, `reviewed_at`. |
| `VerifiedCitation` | `citation_id`, `verification_id`, `verified: true`, 해당 문서/version에 묶인 `TextAnchor`. Schema 형태 검사는 원문 quote 재검증을 대신하지 않는다. |

OpenAPI에 이미 기재된 경로는 다음과 같으며 모두 아직 계획된 확장이다.

| 경로 | 요청/응답 | 예상 책임 |
|---|---|---|
| `GET /v1/quizzes/{quiz_id}` | `200 Quiz` | 인증된 사용자 범위에서 public Quiz 반환 |
| `POST /v1/quizzes/{quiz_id}/attempts` | `Attempt` → `Assessment` | attempt 검증, private grading, 평가, atomic commit 또는 idempotent replay |
| `GET /v1/documents/{document_id}/learning?version_id=...` | `200 LearningState` | 정확한 immutable document version의 학습 상태 조회 |
| `POST /v1/memory/{memory_id}/reviews` | `MemoryReview` → `LearningState` | revision CAS를 적용한 review 반영 |

이 경로들은 OpenAPI 문서에 있어도 등록된 API가 아니다. 통합 담당은 router를 인증·contract-version header와 함께 mount하고 상태 코드/error mapping을 fixture로 연결한다. 신규 공개 DTO나 conflict/pending 응답 envelope가 필요하면 소비자 영향과 Pumice/web fixture를 포함해 contract 변경을 먼저 제안한다. 기존 DTO만 사용하면 `0.1.0`을 유지한다. Native turn transport는 별도로 기존 `/ws` protocol 2.0을 사용한다.

## 통합 담당에 전달할 port patch 제안

현재 `LearningStateStore`의 네 메서드만으로는 private grading 조회, provider 호출 전 idempotency claim, 채점 후 atomic commit을 분리할 수 없다. 통합 담당은 다음 경계를 `ports.py`에 제안하고 bootstrap에서 실제 store를 주입한다. 반환 타입은 실제 저장소 의미에 맞는 dataclass/enum으로 정리하며 아래는 이름과 상태 의미를 합의하기 위한 pseudo-signature다.

```python
async def get_quiz(user_id, quiz_id) -> PublicQuiz: ...
async def get_grading_input(user_id, quiz_id, document_id, version_id) -> PrivateQuiz: ...
async def begin_attempt(user_id, attempt, payload_sha256) -> AttemptClaim: ...
async def commit_assessment(user_id, attempt_id, payload_sha256, assessment) -> LearningState: ...
async def release_attempt_for_retry(user_id, attempt_id, payload_sha256, safe_error_code) -> None: ...
async def get_state(user_id, document_id, version_id) -> LearningState: ...
```

`PrivateQuiz`는 backend service 전용이다. router/DTO/log/UI로 직렬화하지 않고 provider 입력 생성에만 쓴다. `AttemptClaim`의 상태 의미는 `claimed`, `completed_replay`, `in_progress`, `payload_conflict`다. 외부 error body가 새 contract shape를 요구하면 통합 담당이 버전과 generated fixture 변경을 제안한다. 현재 server store가 인증된 user ID를 가지고 있지 않으면 `user_id`는 API 계층이 검증한 주체로 전달하고 body/query/header에서 임의로 신뢰하지 않는다.

UNIT-02 채점 service 처리 순서:

1. contract 형식, UUID, 전체 version hash, answer ID/중복 여부, safe integer, 시각과 요청 크기를 검사한다. quiz의 document/version과 요청의 document/version이 일치하는지 확인한다.
2. 정규화된 `Attempt`를 UTF-8 JSON, key 정렬, 고정 separator로 직렬화해 SHA-256 payload hash를 만든다. 정규화 규칙은 fixture로 고정한다.
3. 짧은 DB transaction에서 `(user_id, client_mutation_id)`를 claim한다. 같은 ID·같은 hash의 완료 요청은 저장된 원 Assessment를 돌려주며 provider를 다시 호출하지 않는다. 같은 ID·다른 hash는 conflict다. 진행 중 동일 요청은 두 번째 provider 평가를 시작하지 않고 pending/retry 규칙으로 처리한다.
4. transaction을 끝낸 뒤 server-only grading input과 사용자 answer를 평가 provider에 전달한다. provider timeout/error는 durable 상태를 부분 반영하지 않고 재시도 가능한 claim 상태와 안전한 내부 error code로 기록한다. private rubric/answer와 credentials는 client 또는 일반 로그에 쓰지 않는다.
5. Assessment citations가 해당 immutable quiz의 검증된 citation 집합 안에 있고, quiz document/version과 일치하는지 검사한다. 현재 in-process 구조 검증은 `verified: true`를 읽는 단계만 한다. 실제 quote/page/hash 검증은 citation verifier에 맡기고 그 결과를 연결한다.
6. 두 번째 짧은 transaction에서 claim/hash를 재확인하고 `base_learning_revision` CAS를 수행한다. 성공 시 attempt, Assessment, 근거가 있는 mastery 변화, progress/activity 및 새 revision을 한 번에 저장한다. revision conflict면 일부 학습 데이터 변경 없이 conflict를 반환한다. 응답에서 `Assessment.learning_revision`과 저장 `LearningState.learning_revision`이 같다.
7. 성공 후 동일 mutation replay는 저장된 동일 Assessment를 반환한다. process가 claim 이후 종료된 경우 lease/expiry 또는 명시적 retry 경로가 provider 중복 호출을 안전하게 복구해야 한다.

## UNIT-01 DB 및 migration patch 제안

아래는 UNIT-01이 현존 SQLite schema 및 migration 정책에 맞춰 조정할 additive patch spec이다. 공통 migration 파일을 UNIT-02가 직접 추가하지 않는다. 실제 DB transaction 경계 안에서만 상태를 변경하고 기존 사용자의 데이터를 삭제하거나 private payload를 public JSON에 섞지 않는다.

```sql
-- schema names illustrative; UNIT-01 aligns them to its storage conventions.
CREATE TABLE mnemosyne_quizzes (
  user_id TEXT NOT NULL,
  quiz_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  public_quiz_json TEXT NOT NULL,
  private_grading_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, quiz_id)
);

CREATE TABLE mnemosyne_attempts (
  user_id TEXT NOT NULL,
  attempt_id TEXT NOT NULL,
  client_mutation_id TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  quiz_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  base_learning_revision INTEGER NOT NULL CHECK (base_learning_revision >= 0),
  status TEXT NOT NULL CHECK (status IN ('in_progress', 'retryable', 'completed')),
  request_json TEXT NOT NULL,
  assessment_json TEXT,
  lease_expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, attempt_id),
  UNIQUE (user_id, client_mutation_id),
  FOREIGN KEY (user_id, quiz_id) REFERENCES mnemosyne_quizzes(user_id, quiz_id),
  CHECK ((status = 'completed') = (assessment_json IS NOT NULL))
);

CREATE TABLE mnemosyne_learning_revisions (
  user_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  learning_revision INTEGER NOT NULL CHECK (learning_revision >= 1),
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, document_id, version_id)
);
```

Migration acceptance points:

- Existing DB startup and migration replay are idempotent. Additive schema migration preserves existing learning data and can roll back its own DDL transaction on failure.
- Quiz public and private grading payloads are immutable after creation; quiz ID points to exactly one document/version. A replacement quiz gets a new ID.
- User scope is included in primary/unique keys and every read/update predicate. Document/version foreign association is checked on reads and writes.
- Attempt claim uniqueness enforces idempotency under concurrent requests. A request hash mismatch never overwrites the first payload. Completed `assessment_json` is immutable.
- `commit_assessment` compares the current revision to the attempt's base revision and writes attempt completion plus all derived state under one transaction. A failed constraint, crash, or stale revision leaves no partial mastery/progress/activity update.
- If existing storage already keeps normalized state rows, use those rows instead of `state_json`; the transaction, public DTO, replay and CAS guarantees remain the same.

## Mastery, memory, activity 및 model 동작

- Mastery는 assessment 또는 명시적으로 검증된 학습 근거에서만 갱신한다. 대화 횟수만으로 점수를 올리지 않는다. `evidence_attempt_ids`는 같은 user/document/version의 저장된 attempt로 FK 또는 동등 검증을 한다.
- Memory review는 `client_mutation_id` 중복 방지와 `base_learning_revision` CAS를 적용하고 `MemoryReview`만으로 카드 내용이나 citation을 신뢰하지 않는다. 결과 state 전체를 revision과 함께 atomic 반환한다.
- Activity/progress 기록은 document/version 및 native `turn_id`와 연결한다. 복구/재생 시 중복 행이 생기지 않도록 native event identity 또는 mutation ID에 유니크 제약을 둔다.
- 기존 `/api/settings` purpose catalog를 재사용한다. purpose override가 비어 있거나 `inherit`이면 현재 turn 모델을 계속 사용한다. UI의 tutor 6개 purpose에는 한국어 표시와 “현재 대화 모델 사용” 선택지를 제공한다.
- 신규 provider SDK, DB package 또는 frontend package는 이 명세에 포함하지 않는다. 현재 서비스 경계로 충분하다. 실제 의존성이 필요해지면 UNIT-06/UNIT-05 담당이 해당 manifest, lockfile, container/CI와 license/source를 함께 갱신한다. UNIT-02는 다른 담당의 dependency 파일을 수정하지 않는다.

## 계약 및 fixture 변경 제안

현존 `0.1.0` Quiz/Attempt/Assessment/LearningState/MemoryReview/TextAnchor shape를 유지하면 공개 contract bump는 요구되지 않는다. `get_grading_input`과 claim/commit 포트는 internal server API이며 public contract에 포함하지 않는다.

통합 담당이 public pending status, conflict detail, provider retry status를 client에 반환하기로 선택하면 다음을 함께 제안한다.

1. Contract `0.2.0`의 error/status DTO와 OpenAPI response/status code 명세.
2. 소비자: DeepTutor API/client, Pumice iPad, UNIT-05 web 및 contract schema/fixture 검증기.
3. Root `contracts/` schema/OpenAPI/fixture/manifest 갱신과 generator를 통한 upstream snapshot 동기화.
4. 같은 mutation ID replay, 다른 payload conflict, revision conflict, in-progress response의 fixture 및 migration/API regression 검증.

계약 복사본은 generated output이므로 직접 수정하지 않는다. 변경 전 통합 담당이 version/consumer 영향과 검증 명령을 확정한다.

## 검증 계획과 이번 checkpoint 결과

| 영역 | 지금 확인된 것 | 제품 인수 전에 추가할 것 |
|---|---|---|
| DTO/adapter fixture | public Quiz의 추가 private field 거부, document version mismatch 거부, Attempt/MemoryReview 입력, native turn routing fixture | 모든 nested LearningState field, malformed citation, 중복 answer/question, Assessment attempt/citation/version mismatch |
| DB | 이번 UNIT-02 checkpoint는 실제 DB patch를 적용하지 않음 | migration fresh/upgrade/replay, atomic rollback, 동시 idempotency, 같은 ID 다른 hash, revision CAS, user isolation, process restart replay |
| Provider | 기존 fixture는 mock/provider-free | private rubric의 server-only 접근, 한국어 feedback, timeout/error/retry, provider 중복 방지, 실제 credential 환경의 평가 |
| API | `contracts/openapi.yaml` 경로 확인. Router mount 검증은 없음 | auth/user scope, contract header, status/error mapping, `/v1/*` 실 mount, API integration fixture |
| Citation | adapter에서 citation DTO의 shape와 quiz source set membership을 확인 | citation verifier가 page text/hash/quote/geometry를 source document에 대조하고 실패를 거부하는 end-to-end fixture |
| 앱 | 이 checkpoint에서 browser, iPad simulator/device, 설치형 product build 수행 안 함 | UNIT-05 한국어 UI, iPad online/offline 상태, 제품 build/device 검증 |

2026-10-09에 실행한 명령은 다음과 같다.

```text
env DEEPTUTOR_HOME=/private/tmp/mnemosyne-unit02-test-home uv run --directory upstreams/DeepTutor --no-project --with pytest --with pytest-asyncio --with fastapi --with httpx --with pydantic --with pydantic-settings --with PyYAML --with PyMuPDF --with openai --with aiosqlite --with python-multipart --with jinja2 --with tiktoken --with requests --with aiohttp --with ddgs --with tenacity --with packaging --with jsonschema --with redis --with loguru --with json-repair --with croniter --with psutil --with 'python-jose[cryptography]' --with defusedxml --with bcrypt -- python -m pytest deeptutor/learning/tests/test_prompt_language_fallback.py tests/api/routers/test_quiz_judge_unit.py tests/runtime/test_lazy_builtin_catalogs.py tests/api/test_unified_ws_turn_runtime.py tests/multi_user/test_learning_reading_turns.py tests/services/test_task_models.py
```

결과: **132 passed, 4 warnings**. `tutor.py` 및 해당 runtime fixture는 Python AST parse를 통과했고, 변경 UNIT-02 파일의 `git diff --check`도 통과했다. 이 결과는 source fixture/unit 검사다. mounted API, 실제 SQLite migration/restart, 실제 provider 호출, iPadOS build/device는 검증하지 않았다. 테스트 및 문법 검사는 upstream 라이선스/원본 경로를 변경하지 않았다.
