# 통합 구현과 검증 결과

2026-10-12 · `codex/mnemosyne-integration` · contract `0.2.0` ·
`product_ready=false`.

여섯 unit의 지정 commit은 모두 통합 기준의 조상이다. 통합 과정에서 서버
Tutor 재접속 receipt route를 실제 등록하고, semantic turn event의 계약 버전을
`0.2.0`으로 맞췄다. Quiz 생성, attempt, assessment, mastery, Memory, progress와
activity는 SQLite에 보존한다. 아래 결과는 구현 확인과 실행 환경의 제품 검증을
구분한다.

## 실행한 검사

| 검사 | 결과 |
|---|---|
| `python checks/sync_contracts.py --check` | **PASS** — contract `0.2.0`, 12-file bundle, 두 downstream copy 일치. |
| `python checks/validate_contracts.py --require-ready` | **PASS** — 32 OpenAPI operation, 4 schemas, 82 schema instance, 19 negative case, 10 sync step, 4 geometry case, Compose service 1개, ownership/source gate. Backend lock은 192 package와 3,587 hash를 확인했다. |
| Python compileall 및 Ruff | **PASS** — 수정한 서버/API/test 모듈 문법 검사와 통합 소유 모듈 Ruff 검사. Ruff format 검사도 통과했다. upstream unit 소유 파일 전체를 임의 재포맷하지 않았다. |
| 통합 Python tests | **PARTIAL** — `tests/mnemosyne` 및 Tutor reconnect tests targeted run에서 42 passed, 38 deselected. 별도 `test_sqlite_quiz_create_replays_duplicate_and_rejects_changed_request`도 1 passed. 이 추가 뒤 전체 targeted pytest 재실행은 async store test에서 완료되지 않아 전체 최신 suite 재실행 결과는 없다. |
| 중복 Tutor turn tests | **PASS** — worker 재시작 뒤 같은 submission 재생과 다중 worker 원자 예약, 2 passed. |
| `checks/source_adapters.py` | **PASS** — 2-page parser/search fixture, 12 native frames, 5 native commands, SQLite reopen/replay/duplicate append, capability map, credential 없는 loopback OpenAI-compatible fake stream을 확인했다. 실제 LLM 호출은 아니다. |
| `checks/integration_pdf_flow.py --allow-index-unavailable` | **PARTIAL** — loopback HTTP로 pairing, 업로드, 2쪽 파싱, 검색, 인용 검증, 주석 retry/tombstone, derived export, SQLite reopen, 원본 PDF SHA 보존, session revoke/WebSocket bridge, progress retry/recovery를 확인했다. `llama_index` 부재로 index 상태는 `failed`다. 인덱싱 이후 Tutor 답변과 생성 Quiz까지 이어지는 제품 흐름은 실행되지 않았다. |
| Web `npm run typecheck` / `npm run contracts:check` | **PASS**. |
| Web `npm run architecture:check` | **PASS** — 913 modules, 2,844 dependencies. |
| 변경한 화면의 scoped ESLint | **PASS WITH WARNINGS** — 0 errors, 38 `i18n/no-literal-ui-text` warnings. |
| `checks/web-consumer.mjs` | **PASS** — PDF.js fixture 2쪽, geometry 4 case, 11 events, 12 native frames. `actualBrowserVerified=false`; browser 화면 테스트는 아니다. |
| `npm run test:node` | **PARTIAL** — 206/209 통과. 나머지 3개는 sandbox가 `git` subprocess 및 `os.networkInterfaces()`를 차단해 실패했다. |
| `npm run test:unit -- --maxWorkers=1 --reporter=dot` | **PARTIAL** — 146 files 중 145, 656 tests 중 652 통과. `i18n-audit`의 subprocess 실행 4개는 sandbox 제한으로 stdout/stderr 없이 실패했다. |
| `npm run build` | **BLOCKED** — Next.js가 Google Fonts에서 Geist/Lora를 가져오지 못해 production build를 완료하지 못했다. |
| `python scripts/docker_compose.py config --quiet` | **PASS** — Compose 설정 구문만 확인했다. |

Node/unit suite의 부분 실패와 마지막 pytest 재실행 정체를 숨기지 않는다.
pytest 정체 중 thread dump에서는 worker가 대기 상태이고 async event loop가
완료되지 않았다. Python executor 제한 또는 남아 있는 장기 실행 프로세스가 원인인지
단정할 수 없으므로, 제한이 없는 실행기에서 suite를 다시 실행해야 한다. 현재
통과한 개별 검사나 이전 pytest 결과가 최종 전체 suite의 통과를 뜻하지 않는다.

## 실제 제품 환경에서 확인하지 못한 항목

| 환경/흐름 | 상태와 근거 |
|---|---|
| Cloud 실행 | **미실행** — 이 task executor에 Cloud 실행 capability나 배포 secret이 없었다. |
| 실제 LLM | **미실행** — provider credential이 없다. fake adapter 검사와 실제 provider 답변은 별개다. |
| 실제 PDF RAG index | **미완료** — loopback 업로드/파싱/검색/출처 검증은 됐지만 `llama_index`가 없어 `ready`가 되지 않았다. |
| Docker image/build/start | **미실행** — Compose config는 통과했지만 `/var/run/docker.sock` 접근이 거부됐다. Windows WSL2 복구도 확인하지 않았다. |
| macOS/Xcode/Swift/iPad | **미실행** — Swift, Xcode, iPadOS SDK, Simulator가 없는 Linux 실행기다. |
| 실제 Pencil | **미실행** — 기기 입력이 없었다. native Pencil sample capture는 코드와 fixture 검사 범위에 한정된다. |
| 실제 browser E2E | **미실행** — production build가 외부 폰트 fetch에서 멈췄고 browser UI acceptance는 실행하지 않았다. |
| 전체 작은 PDF 수락 흐름 | **부분 확인** — upload→parse/search→verified citation→annotation sync/tombstone→export와 원본 hash 보존까지 loopback으로 실행했다. 실제 인덱스/LLM Tutor 응답, Reader 선택 강조, 기기 필기, 웹에 복귀한 UI, 전체 퀴즈→Mastery/Memory 복구 흐름은 아직 한 번에 검증되지 않았다. |

요구사항별 구현/검증 상태는 [통합 handoff](handoffs/integration.md)에 있다.
제품 구현은 후속 phase로 미루지 않았지만, `product_ready`는 위 환경 및 수락
검증이 끝날 때까지 false다.

## 재실행

저장소 root에서 Python audit 의존성과 backend 개발 의존성을 설치한다. 실제
통합 검사에서는 해시 고정 `checks/requirements.txt` 환경과 임시
`DEEPTUTOR_HOME`을 사용해 실행기 기본 설정/데이터와 분리했다.

```sh
python -m pip install -r checks/requirements.txt
python -m pip install -e "upstreams/DeepTutor[dev]"
python checks/sync_contracts.py --check
python checks/validate_contracts.py --require-ready
python checks/source_adapters.py
python checks/integration_pdf_flow.py --allow-index-unavailable
node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON checks/web-consumer.mjs
```

strict PDF run은 `--allow-index-unavailable` 없이 실행한다. 실제 인덱스가
`ready`가 아니면 성공으로 처리하지 않는다. Web suite는 Node 24에서 실행한다.

```sh
cd upstreams/DeepTutor/web
npm ci --replace-registry-host=always --registry=https://registry.npmjs.org
npm run contracts:check
npm run typecheck
npm run architecture:check
npm run test:node
npm run test:unit -- --maxWorkers=1 --reporter=dot
npm run build
```

Live LLM, 실제 Docker 기동, Cloud, macOS/Xcode, iPad/Pencil 검사는 각각 접근
가능한 환경에서 수행해야 한다. 실행하지 않은 검사를 통과로 간주하지 않는다.
