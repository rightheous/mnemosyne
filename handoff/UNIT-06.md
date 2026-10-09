# UNIT-06 — 환경·Docker·CI·통합 검증

기준: 계약 `0.1.0`, 준비 tag `mnemosyne-bootstrap-v0.1.0` (`5715a32927e3a73dc28782d306880e3dd1f62441`), 작업 branch `codex/unit-06-cloud-runtime`. Registry는 공통 시작점 준비 `true`, 제품 준비 `false`다. 원격 Git remote는 현재 설정되어 있지 않아 PR은 만들 수 없다.

## Host와 Cloud 도구 상태

2026-10-09 확인: 호스트는 macOS arm64, Python 3.14.7과 uv 0.11.21이 있다. Python 3.11 실행 파일은 PATH에 없다. 시스템 Node는 20.20.2/npm 10.8.2, 번들 Node는 24.19.0이며 로컬 Node 22는 없다. upstream Dockerfile/CI 기준은 Node 22다. `xcodebuild` shim은 active developer directory가 Command Line Tools뿐이라 실패하고 `xcodegen`도 없다. Docker CLI 29.4.1/Compose 5.1.3과 Docker Desktop daemon 29.4.1 ARM64는 승인된 socket access로 확인했다. Docker base image digest를 고정한 뒤 Docker build와 Compose readiness/stop smoke를 재실행했다. GitHub CLI는 있으나 `git remote -v`는 비어 있다.

## 이번 변경

- `upstreams/DeepTutor/compose.yaml`은 앱 한 서비스만 실행한다. upstream 기본 단일 worker는 memory turn coordinator를 사용하고 turn event/business state는 SQLite에 저장하므로 Redis는 연결하지 않았다. PocketBase와 sandbox runner도 이 단일 사용자 프로필에 필요하지 않아 제외했다. 포트는 기본 `127.0.0.1`에만 게시하고 앱 readiness check, 재시작 정책, 원본/SQLite/설정/작업공간의 단일 `data/` 영속 경로를 둔다.
- graceful shutdown은 upstream runtime의 60초 turn drain에 맞춰 Supervisor가 backend를 75초 기다리고, Compose가 컨테이너에 90초를 준다. 프로세스 그룹에도 TERM/KILL 신호를 전달하도록 했다.
- `upstreams/DeepTutor/requirements.txt`를 지정 snapshot의 `pyproject.toml`과 `[project.optional-dependencies].partners`에서 해석한 Python 3.11 대상 backend runtime lock으로 교체했다. uv 0.11.21이 192개 고정 항목을 해석했고 잠금에는 3,587개의 SHA-256 해시가 있다. 기존 소유 경로를 사용해 새 파일 배정은 필요하지 않다. Dockerfile은 `pip install --require-hashes`로 잠금과 해시를 강제한다. 소스 프로젝트 자체는 build context에서 설치하므로 lock에서 제외했다. Docker base 이미지 tag와 apt 시스템 패키지는 이 Python lock 범위에 포함되지 않는다.
- Dockerfile의 Node 22/Python 3.11 base image는 검증 당시 Docker가 resolve한 manifest digest로 고정했다. OS `apt` package index/version은 snapshot lock에 포함되지 않는다.
- `checks/audit-environment.txt`는 uv 0.11.21의 Python 3.12 universal resolution으로 만든 검증 도구 전체 lock이며 110개 패키지 항목에 SHA-256 해시 2,456개를 기록한다. 기존 106개 버전 pin은 바꾸지 않았고 플랫폼 조건부 네 패키지만 포함했다. `checks/requirements.txt`가 이를 포함하며 `pip install --require-hashes`로 설치한다. Backend production lock과 별도 환경이다.
- `checks/validate_contracts.py`에서 fixture 검사와 완전한 readiness gate를 분리했다. 기본 실행은 계약 fixture만 검사한다. `--require-ready`는 ownership 및 upstream/source gate를 독립 실행해 양쪽 결과를 보고하고, 원본 snapshot SHA 불일치는 전체 경로와 실제 SHA-256을 출력한다. 기본 PASS를 제품 통합 PASS로 해석하지 않는다.
- `checks/source_adapters.py`는 실제 DeepTutor OpenAI-compatible streaming adapter를 ephemeral loopback SSE server에 연결한다. 키나 외부 네트워크 없이 두 content delta와 terminal reason을 확인하며, server/client 오류는 PASS로 낮추지 않는다. 이는 provider HTTP adapter 검증이지 실제 Tutor `/ws` 제품 흐름 검증은 아니다.

## 실행 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| 새 `/tmp` venv에서 `pip install --require-hashes -r checks/requirements.txt`와 `pip check` | PASS | Python 3.12.13, macOS arm64. 110개 universal lock 패키지와 2,456개 artifact SHA-256 해시. Windows/Linux 설치는 미검증. |
| uv 0.11.21로 checks lock 재해석 및 version/hash 비교 | PASS | `uv pip compile checks/requirements.txt --python-version 3.12 --universal --generate-hashes --no-header`; 110개 패키지의 version/artifact hash가 모두 일치. 생성 provenance 주석은 달라 byte-identical 비교는 아님. |
| `checks/validate_contracts.py` on clean archive `bf174ab` | PASS | OpenAPI 30 operations, 4 schemas, 80 schema instances, 19 negative cases, 10 sync steps, 4 geometry cases. 소스/readiness gate는 실행하지 않음. |
| Backend runtime lock 정적 검사 (위 fixture 검사에 포함) | PASS | 192개 Python 3.11 대상 잠금 항목, 3,587개 해시, 필수 backend 패키지, Docker `--require-hashes` 적용을 확인. 같은 uv 명령의 재해석 결과와 잠금 파일이 바이트 단위로 일치. |
| `checks/validate_contracts.py --require-ready` on clean archive `bf174ab` | FAIL | Ownership: `docs/handoffs/unit-02.md` is unassigned; `absent=[]`. Source gate: 79 tracked upstream files differ from pinned snapshot hashes without `current_sha256` exceptions (UNIT-02 42, UNIT-05 34, UNIT-06 3); output includes each path's current SHA-256. Other source/provenance, contract-copy, registration and license checks completed. |
| `checks/source_adapters.py` on clean archive `bf174ab` and pinned DeepTutor `6cf793bd868ba5ecbe64722936d4be8fab5a01df` | PASS | PDF pages 2, native frames 12, native commands 5, SQLite reopen/replay true, duplicate append creates no events, capability mappings 6. Actual OpenAI-compatible provider streamed two deltas from a loopback server without credentials or external network. `product_ready=false`. |
| `ruff check checks/source_adapters.py` | PASS | Probe is executable and import-sorted. |
| DeepTutor `tests/api/test_unified_ws_turn_runtime.py` on clean archive `5bb0a23` | FAIL, 54/55 | One test cannot import `LibraryError` from `deeptutor.mnemosyne.library`; the class exists only in the current uncommitted UNIT-01 library changes. The same test against the dirty shared worktree advances farther but fails at `library.py:1095` with SQLite's “statement uses 4, 3 supplied” bindings error. The test was read-only; neither failure was changed by UNIT-06. |
| `docker compose -f upstreams/DeepTutor/compose.yaml config --quiet` | PASS | YAML/Compose 구성 정적 검사. 1개 앱 서비스, 루프백 포트, persistence와 종료 유예를 확인. |
| `docker compose -f upstreams/DeepTutor/docker-compose.yml config --quiet` | PASS | 기존 upstream compose 구성 정적 검사. 새 Mnemosyne 프로필의 기동 증거는 아님. |
| `python -m pip check` | PASS | 설치한 검증 venv 안의 패키지 관계만 확인. |
| `docker info` | PASS | 권한 승인 후 Docker Desktop daemon 29.4.1 ARM64 응답 확인. |
| Clean-source `docker compose ... build deeptutor` on `5bb0a23` | PASS | Pinned Node 22/Python 3.11 manifest digest references resolved; production image built (matching frontend builder layers reused from cache). Local image manifest-list digest: `sha256:7faba25eb9b6db5f9a27275fa4096e0d9f8cc630ae948f2485530d79590ec6f8`. It was not pushed or published. |
| Compose up/readiness/health/stop on clean archive `5bb0a23` | PASS, limited smoke | One service started and became Docker `healthy`; internal backend `/health/ready` returned HTTP 200 `{"status":"ready"}`, frontend port 3782 `/` returned HTTP 307 to `/learning/reading`, and graceful `compose stop` exited 0. Startup logs warn that no active LLM model is configured, so Tutor streaming was not exercised. Checks ran inside the container. |
| Generated default-data tar backup/restore smoke | PASS, limited | Stopped test service data was tarred, extracted to a separate `/tmp` directory, and recursively compared equal. This was generated empty/default runtime data only, with no uploaded source documents or provider secrets; live database recovery with user data remains untested. |
| Node 22 `npm ci --legacy-peer-deps` on clean archive `f62813b` | PASS | Node 22.23.3/npm 10.9.9; installed 950 packages. npm audit reported 28 vulnerabilities (5 low, 7 moderate, 15 high, 1 critical). |
| Node `check:fast` through `test:node` on clean archive `f62813b` | PASS | Contract generation check, architecture check (913 modules / 2,844 dependencies, no violations), typecheck, and Node tests passed; `npm run check` then reached Vitest. |
| Node `test:unit` full parallel suite on clean archive `f62813b` | FAIL, 646/653 | 142/146 files passed. Two tests timed out at 5 seconds; five tests in `sidebar-lazy-history` and `sidebar-prefetch` failed because `SidebarHome` reads `entry.href` from an undefined navigation entry. Isolated serial rerun passed the two timeout tests and question-bank tests; all five sidebar failures reproduced (8/13 passed across the four affected files). |
| Node `lint` / `i18n:check` on clean frontend image `f62813b` | PASS with warnings | Lint exited 0 with 89 warnings and no errors. i18n parity/audit exited 0 with potential UI-literal notes. |
| Docker frontend production build / Node `perf:check` on clean frontend image `f62813b` | BUILD PASS / PERF FAIL | Docker production build completed. Route-budget check expected `/` to redirect to `/chat`, but got HTTP 307 to `/learning/reading`. This aligns with the Compose smoke. Routing and sidebar code are outside UNIT-06 ownership. |
| iPad macOS/Xcode build 및 signing 분리 job | 미실행 | 이 호스트는 full Xcode/XcodeGen이 없다. GitHub Mac runner도 실행되지 않았다. |
| Windows/WSL2 서버, 실제 iPad Pencil, 실제 LLM provider | 대기 | 이 실행에서 해당 장치/서버를 사용할 수 없었다. fixture 검사는 이 인수 검증을 대체하지 않는다. |

계약 fixture/source-adapter 검사와 두 readiness gate는 clean source archive commit `bf174ab643fadd5e020f0fae9a4a4d06da7b0213`에서 실행했다. 해시 설치 검증에는 현재 UNIT-06 checks lock 두 파일을 archive에 덮어 복사했으며 제품 소스는 수정하지 않았다. scratch Git index는 `git add -f -A`로 복원해 upstream `.gitignore`의 ignored-but-tracked 파일을 보존했다. `absent=[]`이며 검사 출력과 venv는 archive 밖에 두었다. Web 전체 검사는 clean archive `f62813b`에서 Node 22.23.3으로 실행했고, Web 파일은 `f62813b..bf174ab` 사이 바뀌지 않았다. Clean archive와 달리 현재 shared worktree에는 UNIT-01/03 변경이 미커밋 상태이므로 그 소스를 포함한 targeted backend 재실행 결과를 별도로 기록했다. 다른 유닛 파일은 stage하거나 commit하지 않았다.

## 계약 fixture와 제품 인수의 경계

| 요구 | 현재 증거 | 남은 제품 검사 |
|---|---|---|
| PDF hash, geometry, quote, 잘못된 locator 거부 | fixture validator에서 계약 hash/좌표/인용 negative cases PASS | 서버 업로드·파싱·원본 파일 hash 불변의 runtime 재검사 |
| 주석 upsert/delete/tombstone/중복 mutation | 10개 fixture sync step의 reference model PASS | 실제 서버 transaction, 다른 클라이언트 수신, app 재시작 복구 |
| Tutor event/citation/Reader/quiz/learning state | schema와 fixture linkage, native wire/replay fixture 검사 PASS | 실제 `/ws` streaming, 인용 이후 Reader 명령, durable quiz/mastery/memory 저장·재시작 |
| 마이그레이션·export | 이번 검사에서 실행 안 함 | UNIT-01 storage/migration 적용 뒤 원본 보존, export 산출물, rollback 검사 |
| 사설 접속·최소 보호·secret | Compose loopback 기본값 및 env의 key/token/secret 부재를 정적 검사 | 앱 pairing/Origin 보호는 UNIT-02, WSL2 firewall/Tailscale는 실제 기기에서 검사 |
| 백업·복원 | 생성된 기본 `data/` 디렉터리의 tar→extract→recursive diff smoke PASS | 업로드 원본과 실제 SQLite 학습 상태를 포함한 복원 및 재기동 검사는 미실행 |
| LLM no-secret 경로 | 실제 OpenAI-compatible client가 loopback fake SSE server에서 두 content delta를 받고 `finish_reason=stop`을 반환, key/external network 없음 | 이는 provider HTTP adapter만 검증한다. Compose에 active model이 없어 실제 Tutor `/ws` streaming 및 실제 provider 연결은 미검증. |

fixture PASS는 표의 runtime 검사를 완료했다는 뜻이 아니다.

## Codex Cloud 및 재현 명령

공식 Codex Cloud 환경은 web/desktop의 `Settings > Codex Cloud > Environments`에서 만들고, GitHub repository를 선택한 뒤 `Install script`와 `Start skill`을 검토·저장·게시한다. 현재 task 도구에는 실제 계정의 Cloud 환경을 편집하는 UI/API가 없고 `request_environment_input`/`finalize_environment`는 prototype catalog만 다룬다. `git remote -v`도 비어 있어 게시할 GitHub repository를 확인할 수 없으므로 Cloud 환경은 만들거나 게시하지 않았다. 공식 절차: [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).

환경 생성 시 upstream과 같은 Python 3.11, Node 22를 요청한다. 의존성 설치에는 Package managers 네트워크 정책(Python: PyPI, Web: npm)이 필요하다. 아래 fixture/server 검사에는 provider secret이 필요하지 않다.

### Install script

```sh
python3.11 -m venv .venv/unit06-runtime
.venv/unit06-runtime/bin/python -m pip install --require-hashes -r upstreams/DeepTutor/requirements.txt

python3.11 -m venv .venv/unit06-checks
.venv/unit06-checks/bin/python -m pip install --require-hashes -r checks/requirements.txt

cd upstreams/DeepTutor/web
npm ci --legacy-peer-deps
```

The runtime lock selects the Python 3.11 backend dependencies; the separate checks environment pins fixture/source-probe tools. Node 22 matches the upstream Dockerfile and its CI workflow.

### Check commands

```sh
.venv/unit06-checks/bin/python checks/validate_contracts.py
.venv/unit06-checks/bin/python checks/source_adapters.py
(cd upstreams/DeepTutor/web && npm run check)
docker compose -f upstreams/DeepTutor/compose.yaml config --quiet
```

### Start skill

First run `docker info`. If it reaches a daemon:

```sh
docker compose -f upstreams/DeepTutor/compose.yaml up -d --build
docker compose -f upstreams/DeepTutor/compose.yaml ps
curl -fsS http://127.0.0.1:8001/health/ready
```

If no daemon is available, run only the Compose `config --quiet` check and report container start/readiness as unverified. Do not treat missing Docker or provider configuration as a passing runtime check. Stop the app with `docker compose -f upstreams/DeepTutor/compose.yaml stop`; keep `upstreams/DeepTutor/data/` for recovery.

Backend lock 재생성은 DeepTutor 디렉터리에서 실행한다. Python 3.11 대상의 universal resolution이며 DeepTutor 소스 패키지는 Docker build context에서 복사되므로 lock 출력에서 제외한다.

```sh
cd upstreams/DeepTutor
uv pip compile pyproject.toml --extra partners --python-version 3.11 --universal --generate-hashes --no-emit-package deeptutor -o requirements.txt
```

`--require-ready`는 ownership 목록과 모든 등록 seam이 실제 파일에 연결된 뒤 실행한다. 웹 검사에는 upstream 지침대로 Node 22와 `npm ci --legacy-peer-deps`, `npm run check`가 필요하다.

WSL2 운영은 저장소를 Linux 파일시스템에 두고 다음 명령을 `upstreams/DeepTutor`에서 실행한다. 동일 Compose의 빌드·기동·readiness는 macOS ARM64 Docker에서 확인했지만, Windows/WSL2 파일시스템·포트 전달·Firewall 동작은 별도 검증이 필요하다.

```sh
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml up -d --build
docker compose -f compose.yaml ps
curl -fsS http://127.0.0.1:8001/health/ready
```

기본 게시 주소는 loopback이며 `DEEPTUTOR_BIND_ADDRESS`, `HOST_PORT_BACKEND`, `HOST_PORT_FRONTEND`로 바꿀 수 있다. LAN 공개가 필요하면 Windows Firewall에서 지정한 사설 인터페이스/기기만 허용하고, 라우터 port-forward는 만들지 않는다. UNIT-02의 pairing/Origin 보호 구현 전에는 외부 인터페이스로 바인딩하지 않는다. Tailscale 경로와 Windows Firewall 동작은 실제 WSL2 기기에서 확인 대기다.

백업은 애플리케이션을 멈춰 SQLite와 업로드 원본을 일관된 시점에 저장한다. 백업에는 provider 설정/비밀값이 포함될 수 있으므로 접근 권한을 제한하고 저장소나 로그에 두지 않는다.

```sh
cd upstreams/DeepTutor
docker compose -f compose.yaml stop
umask 077
tar -czf /secure-backup/mnemosyne-data.tar.gz data
docker compose -f compose.yaml start
```

복구는 먼저 서비스 종료 후 현재 `data/`를 별도 보존하고, 검증한 백업을 프로젝트 경로에 풀어 다시 기동한다. 생성된 기본 data 트리의 archive/extract/content comparison은 PASS했으나, 업로드 원본·실제 SQLite 학습 기록의 복구 후 재기동은 아직 미검증이다.

## 통합 담당자에게 필요한 배정/확인

1. `integration/ownership.json`에서 tracked 상태인 `docs/handoffs/unit-02.md`에 단독 담당자를 배정한다. Corrected archive check에서 다른 소유 경로의 누락은 없다.
2. root CI 파일(예: `.github/workflows/mnemosyne.yml`)을 UNIT-06에 배정한다. 현재 할당된 `.github/workflows/tests.yml`은 upstream 하위 경로라 이 Mnemosyne root 저장소의 GitHub Actions workflow로 실행되지 않는다. Backend runtime lock은 기존 UNIT-06 소유 경로인 `upstreams/DeepTutor/requirements.txt`에 작성했다.
3. 목표에서 지정한 `docs/handoffs/unit-06.md`는 현재 정확한 소유 목록에 없고 기존 배정 파일은 `handoff/UNIT-06.md`다. 이 handoff는 허용된 경로를 사용했다. 새 문서 경로를 원하면 먼저 배정한다.
4. Clean source `bf174ab`에서 79개 tracked upstream 수정의 사유와 실제 SHA-256을 `integration/upstreams.json`의 수정 예외에 반영한다. 계산된 분포는 UNIT-02 42개, UNIT-05 34개, UNIT-06 3개다. `--require-ready` source gate 출력에 현재 SHA-256이 포함된다. 해당 metadata는 통합 담당 소유라 여기서는 고치지 않았다. UNIT-06 변경의 현재 SHA-256:
   - `upstreams/DeepTutor/compose.yaml`: `a86bfe994c63763b93125f3c3861e32c9942a618fb2d191a83d9a0e3629a8bab`
   - `upstreams/DeepTutor/Dockerfile`: `c42b5bdf68bc4bd6811c0022b8ac01c5d7abaaee7aacd0c3b9ac39cd698e07cb`
   - `upstreams/DeepTutor/requirements.txt`: `c4c5917e5cb1288e80e21bafc6daab70b713eb39f89a59186cce07a2c44a32b5`
5. 최종 통합에는 의도한 UNIT-01/03/04의 정확한 revision 또는 PR URL이 필요하다. 검사 당시 history에는 UNIT-02의 변경이 `bf174ab`까지, UNIT-05의 이전 커밋이 포함되어 있었다. 선택한 정확한 revision을 정한 뒤 소유 gate와 통합 검사를 다시 실행한다. UNIT-04는 iPad simulator/device 검증 결과도 제공해야 한다.
6. `docs/VALIDATION.md`는 integrator 소유이며 설치 예시가 아직 `pip install -r checks/audit-environment.txt`를 가리킨다. 새 lock을 검증된 방식으로 쓰도록 `pip install --require-hashes -r checks/requirements.txt`로 갱신한다.

## 대기 인수

- 실제 Windows/WSL2 설치·기동, SQLite 기록의 재시작 복구, 업로드 원본을 포함한 백업/복구 확인
- 실제 iPad에서 Pencil 입력, 오프라인 저장, 종료/재시작 복구 확인
- 실제 LLM provider 연결(명시적 테스트 자격증명 사용, 로그/fixture에 secret 금지)
- Docker 단일 서비스 profile은 clean archive `5bb0a23`에서 image build, Compose up, `/health/ready`, healthy, graceful stop까지 PASS. 실제 자료를 이용한 upload/parse/sync/restart/backup recovery는 미검증이며 이 profile은 Redis를 사용하지 않는다.
- Node 22 full `npm run check`는 full parallel suite의 5개 sidebar assertion/runtime 오류와 2개 timeout으로 중단되어 build와 perf step까지 도달하지 않았다. Timeout 두 건은 serial retry PASS, sidebar 다섯 건은 재현. Docker build는 PASS했고 별도 `perf:check`는 `/` → `/chat` 기대와 실제 `/learning/reading` redirect 차이로 FAIL. Root GitHub Linux/macOS/Xcode CI workflow는 현재 소유 배정이 없어 미추가·미실행.
- 공식 Codex Cloud 환경은 생성·게시하지 않았다. Task 도구는 prototype catalog만 편집하며 GitHub remote/repository도 확인되지 않았다. Docker image도 로컬에서만 만들었고 push하지 않았다.
