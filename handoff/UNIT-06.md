# UNIT-06 — 환경·Docker·CI·통합 검증

기준: 계약 `0.1.0`, 준비 tag `mnemosyne-bootstrap-v0.1.0` (`5715a32927e3a73dc28782d306880e3dd1f62441`), 작업 branch `codex/unit-06-cloud-runtime`. Registry는 공통 시작점 준비 `true`, 제품 준비 `false`다. 원격 Git remote는 현재 설정되어 있지 않아 PR은 만들 수 없다.

## Host와 Cloud 도구 상태

2026-10-09 확인: 호스트는 macOS arm64, Python 3.14.7과 uv 0.11.21이 있다. Python 3.11 실행 파일은 PATH에 없다. 시스템 Node는 20.20.2/npm 10.8.2, 번들 Node는 24.19.0이며 로컬 Node 22는 없다. upstream Dockerfile/CI 기준은 Node 22다. `xcodebuild` shim은 active developer directory가 Command Line Tools뿐이라 실패하고 `xcodegen`도 없다. Docker CLI 29.4.1/Compose 5.1.3과 Docker Desktop daemon 29.4.1 ARM64는 user-approved socket access로 확인했다. Clean-source Docker image build는 아래에서 진행 중이다. GitHub CLI는 있으나 `git remote -v`는 비어 있다.

## 이번 변경

- `upstreams/DeepTutor/compose.yaml`은 앱 한 서비스만 실행한다. upstream 기본 단일 worker는 memory turn coordinator를 사용하고 turn event/business state는 SQLite에 저장하므로 Redis는 연결하지 않았다. PocketBase와 sandbox runner도 이 단일 사용자 프로필에 필요하지 않아 제외했다. 포트는 기본 `127.0.0.1`에만 게시하고 앱 readiness check, 재시작 정책, 원본/SQLite/설정/작업공간의 단일 `data/` 영속 경로를 둔다.
- graceful shutdown은 upstream runtime의 60초 turn drain에 맞춰 Supervisor가 backend를 75초 기다리고, Compose가 컨테이너에 90초를 준다. 프로세스 그룹에도 TERM/KILL 신호를 전달하도록 했다.
- `upstreams/DeepTutor/requirements.txt`를 지정 snapshot의 `pyproject.toml`과 `[project.optional-dependencies].partners`에서 해석한 Python 3.11 대상 backend runtime lock으로 교체했다. uv 0.11.21이 192개 고정 항목을 해석했고 잠금에는 3,587개의 SHA-256 해시가 있다. 기존 소유 경로를 사용해 새 파일 배정은 필요하지 않다. Dockerfile은 `pip install --require-hashes`로 잠금과 해시를 강제한다. 소스 프로젝트 자체는 build context에서 설치하므로 lock에서 제외했다. Docker base 이미지 tag와 apt 시스템 패키지는 이 Python lock 범위에 포함되지 않는다.
- `checks/requirements.txt`는 contract fixture와 source probe에서 쓰는 고정 Python 검증 환경을 `checks/audit-environment.txt`에 연결하고 OpenAPI validator를 고정한다. 이것은 backend lock과 별도의 검증 도구 환경이다.
- `checks/validate_contracts.py`에서 fixture 검사와 완전한 readiness gate를 분리했다. 기본 실행은 계약 fixture만 검사하고, `--require-ready`는 ownership 및 upstream/source gate까지 검사한다. 기본 PASS를 제품 통합 PASS로 해석하지 않는다.

## 실행 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| `/tmp` 임시 venv에 `pip install -r checks/requirements.txt`에 필요한 고정 패키지 설치 | PASS | Python 3.12.14, macOS arm64. 승인된 네트워크 설치. Windows/Linux 설치는 미검증. |
| `uv run --with-requirements checks/requirements.txt --no-project --python 3.12 python3 checks/validate_contracts.py` | PASS | OpenAPI 30 operations, schema instance 80, negative case 19, sync step 10, geometry case 4. 소스/readiness gate는 실행하지 않음. |
| Backend runtime lock 정적 검사 (위 fixture 검사에 포함) | PASS | 192개 Python 3.11 대상 잠금 항목, 3,587개 해시, 필수 backend 패키지, Docker `--require-hashes` 적용을 확인. 같은 uv 명령의 재해석 결과와 잠금 파일이 바이트 단위로 일치. Docker daemon이 없어 이미지 설치는 미검증. |
| `python checks/validate_contracts.py --require-ready` | FAIL | 공유 worktree에서 `upstreams/Pumice/Sources/Network/MnemosyneModels.swift`가 ownership에 배정되지 않았다고 보고했다. 통합 소유자 확인 필요. |
| `checks/source_adapters.py` against clean `HEAD` `6e7277a` and pinned DeepTutor `6cf793bd868ba5ecbe64722936d4be8fab5a01df` | FAIL | Fixture input `reader_context.content_language=en`, `response_language=ko`: expected native `language=en` and `reply_language_override=ko`; actual is `language=ko`, `reply_language_override=ko`. Mapping is in `upstreams/DeepTutor/deeptutor/mnemosyne/tutor.py:100`, owned by UNIT-02. Required change: forward content language to native `language` while retaining response language as the reply override. UNIT-06 added the exact values to the assertion message; product code remains untouched. |
| `docker compose -f upstreams/DeepTutor/compose.yaml config --quiet` | PASS | YAML/Compose 구성 정적 검사. 1개 앱 서비스, 루프백 포트, persistence와 종료 유예를 확인. |
| `docker compose -f upstreams/DeepTutor/docker-compose.yml config --quiet` | PASS | 기존 upstream compose 구성 정적 검사. 새 Mnemosyne 프로필의 기동 증거는 아님. |
| `python -m pip check` | PASS | 설치한 검증 venv 안의 패키지 관계만 확인. |
| `docker info` | PASS | 권한 승인 후 Docker Desktop daemon 29.4.1 ARM64 응답 확인. |
| Clean-source `docker compose ... build deeptutor` | 진행 중, 아직 terminal result 없음 | `HEAD` archive에 UNIT-06 Dockerfile/Compose만 overlay했다. BuildKit이 Docker Hub Python/Node base metadata를 기다리고 있으며 새 base image는 cache에 나타나지 않았다. |
| Compose up/readiness/restart/backup·restore | 미검증 | 이미지 build 완료 전 기동하지 않았다. |
| 웹 `npm ci` / `npm run check` | 미실행 | 시스템 Node 20.20.2, 번들 Node 24.19.0이며 upstream Docker/CI는 Node 22를 사용한다. Node 22 환경에서 실행해야 한다. |
| iPad macOS/Xcode build 및 signing 분리 job | 미실행 | 이 호스트는 full Xcode/XcodeGen이 없다. GitHub Mac runner도 실행되지 않았다. |
| Windows/WSL2 서버, 실제 iPad Pencil, 실제 LLM provider | 대기 | 이 실행에서 해당 장치/서버를 사용할 수 없었다. fixture 검사는 이 인수 검증을 대체하지 않는다. |

위 source-adapter 실패는 clean archive of commit `6e7277a`에서 재현했으므로 공유 worktree 변경 탓으로 돌리지 않는다. 현재 shared worktree에는 UNIT-01/02/03/05의 비커밋 제품 변경이 있다. 이 변경은 검사·stage·commit 대상에서 제외했다. 수정 후에는 사용자가 제공한 정확한 commit/PR 목록의 revision에서 다시 실행해야 한다.

## 계약 fixture와 제품 인수의 경계

| 요구 | 현재 증거 | 남은 제품 검사 |
|---|---|---|
| PDF hash, geometry, quote, 잘못된 locator 거부 | fixture validator에서 계약 hash/좌표/인용 negative cases PASS | 서버 업로드·파싱·원본 파일 hash 불변의 runtime 재검사 |
| 주석 upsert/delete/tombstone/중복 mutation | 10개 fixture sync step의 reference model PASS | 실제 서버 transaction, 다른 클라이언트 수신, app 재시작 복구 |
| Tutor event/citation/Reader/quiz/learning state | schema와 fixture linkage, native wire/replay fixture 검사 PASS | 실제 `/ws` streaming, 인용 이후 Reader 명령, durable quiz/mastery/memory 저장·재시작 |
| 마이그레이션·export | 이번 검사에서 실행 안 함 | UNIT-01 storage/migration 적용 뒤 원본 보존, export 산출물, rollback 검사 |
| 사설 접속·최소 보호·secret | Compose loopback 기본값 및 env의 key/token/secret 부재를 정적 검사 | 앱 pairing/Origin 보호는 UNIT-02, WSL2 firewall/Tailscale는 실제 기기에서 검사 |
| 백업·복원 | 중지·tar·복원 절차만 문서화 | Docker daemon 복구 후 실제 데이터를 넣어 restore smoke test |
| LLM no-secret 경로 | PublicSettings의 secret 필드 거부 fixture PASS | test-only provider는 실제 `/ws` test harness에 아직 연결되지 않아 미검증. 실제 provider 연결은 별도 실행 필요 |

fixture PASS는 표의 runtime 검사를 완료했다는 뜻이 아니다.

## Codex Cloud 및 재현 명령

공식 Codex Cloud 환경은 web/desktop의 `Settings > Codex Cloud > Environments`에서 만들고, GitHub repository를 선택한 뒤 `Install script`와 `Start skill`을 검토·저장·게시한다. 현재 task 도구에는 실제 계정의 Cloud 환경을 편집하는 UI/API가 없고 `request_environment_input`/`finalize_environment`는 prototype catalog만 다룬다. `git remote -v`도 비어 있어 게시할 GitHub repository를 확인할 수 없으므로 Cloud 환경은 만들거나 게시하지 않았다. 공식 절차: [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).

환경 생성 시 upstream과 같은 Python 3.11, Node 22를 요청한다. 의존성 설치에는 Package managers 네트워크 정책(Python: PyPI, Web: npm)이 필요하다. 아래 fixture/server 검사에는 provider secret이 필요하지 않다.

### Install script

```sh
python3.11 -m venv .venv/unit06-runtime
.venv/unit06-runtime/bin/python -m pip install --require-hashes -r upstreams/DeepTutor/requirements.txt

python3.11 -m venv .venv/unit06-checks
.venv/unit06-checks/bin/python -m pip install -r checks/requirements.txt

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

WSL2 운영은 저장소를 Linux 파일시스템에 두고 다음 명령을 `upstreams/DeepTutor`에서 실행한다. Compose 정적 검사만 확인했으며 빌드·기동은 daemon 복구 후 실행한다.

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

복구는 먼저 서비스 종료 후 현재 `data/`를 별도 보존하고, 검증한 백업을 프로젝트 경로에 풀어 다시 기동한다. 자동 백업·복구 smoke test는 실제 Docker daemon이 없어 미실행이다.

## 통합 담당자에게 필요한 배정/확인

1. `integration/ownership.json`에서 현재 gate가 지적한 `upstreams/Pumice/Sources/Network/MnemosyneModels.swift` 소유자를 명시한다.
2. root CI 파일(예: `.github/workflows/mnemosyne.yml`)을 UNIT-06에 배정한다. 현재 할당된 `.github/workflows/tests.yml`은 upstream 하위 경로라 이 Mnemosyne root 저장소의 GitHub Actions workflow로 실행되지 않는다. Backend runtime lock은 기존 UNIT-06 소유 경로인 `upstreams/DeepTutor/requirements.txt`에 작성했다.
3. 목표에서 지정한 `docs/handoffs/unit-06.md`는 현재 정확한 소유 목록에 없고 기존 배정 파일은 `handoff/UNIT-06.md`다. 이 handoff는 허용된 경로를 사용했다. 새 문서 경로를 원하면 먼저 배정한다.
4. 다음 원본 snapshot 변경의 사유와 SHA-256을 `integration/upstreams.json`의 수정 예외에 반영한다. 해당 메타데이터는 통합 담당 소유라 여기서는 고치지 않았다.
   - `upstreams/DeepTutor/compose.yaml`: `a86bfe994c63763b93125f3c3861e32c9942a618fb2d191a83d9a0e3629a8bab`
   - `upstreams/DeepTutor/Dockerfile`: `89d6073ce35feb2978961bc91e0638f5236291e294ea021ac4d73588eb871ea3`
   - `upstreams/DeepTutor/requirements.txt`: `c4c5917e5cb1288e80e21bafc6daab70b713eb39f89a59186cce07a2c44a32b5`
5. 사용자 제공 UNIT-01/02/03/04/05 commit/PR 목록을 받으면 각 정확한 revision에서 통합 검사와 소유 gate를 재실행한다. UNIT-02는 Tutor 언어 분리 assertion을 확인하고, UNIT-04는 iPad simulator/device 검증 결과를 제공해야 한다.

## 대기 인수

- 실제 Windows/WSL2 설치·기동·재시작·백업/복구 확인
- 실제 iPad에서 Pencil 입력, 오프라인 저장, 종료/재시작 복구 확인
- 실제 LLM provider 연결(명시적 테스트 자격증명 사용, 로그/fixture에 secret 금지)
- Docker daemon 복구 후 이미지 build, Compose up, `/health/ready`, Redis 및 DB 재시작 복구 확인
- Node 22 웹 검사, GitHub Linux/macOS/Xcode CI 결과
