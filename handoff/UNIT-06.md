# UNIT-06 — 환경·Docker·CI·통합 검증

기준: 계약 `0.1.0`, 준비 tag `mnemosyne-bootstrap-v0.1.0` (`5715a32927e3a73dc28782d306880e3dd1f62441`), 작업 branch `codex/unit-06-cloud-runtime`. Registry는 공통 시작점 준비 `true`, 제품 준비 `false`다. 원격 Git remote는 현재 설정되어 있지 않아 PR은 만들 수 없다.

## 이번 변경

- `upstreams/DeepTutor/compose.yaml`을 Windows/WSL2 Docker Compose 프로필로 바꿨다. 지정 DeepTutor snapshot을 로컬 빌드하고, FastAPI+Next.js 한 서비스와 내부 Redis만 사용한다. PocketBase와 sandbox runner는 이 단일 사용자 프로필에서 시작하지 않는다. 포트는 기본 `127.0.0.1`에만 게시하고, 앱 readiness healthcheck, 재시작 정책, 종료 유예, Redis AOF, 원본/SQLite/설정/작업공간의 단일 `data/` 영속 경로를 둔다.
- `checks/requirements.txt`는 contract fixture와 source probe에서 쓰는 고정 Python 검증 환경을 `checks/audit-environment.txt`에 연결하고 OpenAPI validator를 고정한다. **이것은 backend production lock이 아니다.** DeepTutor의 Python runtime manifest는 버전 범위이며 새 lockfile 경로가 소유권에 배정되지 않았다.
- `checks/validate_contracts.py`에서 fixture 검사와 완전한 readiness gate를 분리했다. 기본 실행은 계약 fixture만 검사하고, `--require-ready`는 ownership 및 upstream/source gate까지 검사한다. 기본 PASS를 제품 통합 PASS로 해석하지 않는다.

## 실행 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| `/tmp` 임시 venv에 `pip install -r checks/requirements.txt`에 필요한 고정 패키지 설치 | PASS | Python 3.12.14, macOS arm64. 승인된 네트워크 설치. Windows/Linux 설치는 미검증. |
| `python checks/validate_contracts.py` | PASS | OpenAPI 30 operations, schema instance 80, negative case 19, sync step 10, geometry case 4. 소스/readiness gate는 실행하지 않음. |
| `python checks/validate_contracts.py --require-ready` | FAIL | 공유 worktree에서 `upstreams/Pumice/Sources/Network/MnemosyneModels.swift`가 ownership에 배정되지 않았다고 보고했다. 통합 소유자 확인 필요. |
| `python checks/source_adapters.py` | 이전 실행에서 FAIL, 확정 revision 재검사 대기 | fixture `content_language=en`, `response_language=ko` 입력에서 `value.language == "en"` assertion이 실패했다. Tutor mapping은 UNIT-02 소유이며 이후 공유 worktree에 그 경로의 비커밋 변경이 나타났다. 사용자 제공 revision을 받은 뒤 계약의 content/response 언어 분리가 보존되는지 다시 확인한다. 제품 결함으로 확정하거나 해당 경로를 수정하지 않았다. |
| `docker compose -f upstreams/DeepTutor/compose.yaml config --quiet` | PASS | YAML/Compose 구성 정적 검사. |
| `docker compose -f upstreams/DeepTutor/docker-compose.yml config --quiet` | PASS | 기존 upstream compose 구성 정적 검사. 새 Mnemosyne 프로필의 기동 증거는 아님. |
| `python -m pip check` | PASS | 설치한 검증 venv 안의 패키지 관계만 확인. |
| Docker 실제 build/up, readiness, restart, 백업·복구 | 미검증 | Docker CLI/Compose는 있으나 Docker daemon socket 접근이 거부됐다. |
| 웹 `npm ci` / `npm run check` | 미실행 | 시스템 Node 20.20.2, 번들 Node 24.19.0이며 upstream Docker/CI는 Node 22를 사용한다. Node 22 환경에서 실행해야 한다. |
| iPad macOS/Xcode build 및 signing 분리 job | 미실행 | 이 호스트는 full Xcode/XcodeGen이 없다. GitHub Mac runner도 실행되지 않았다. |
| Windows/WSL2 서버, 실제 iPad Pencil, 실제 LLM provider | 대기 | 이 실행에서 해당 장치/서버를 사용할 수 없었다. fixture 검사는 이 인수 검증을 대체하지 않는다. |

`source_adapters.py` 결과는 다른 유닛의 로컬 변경이 섞이지 않은 확정 commit 결과로 간주하지 않는다. 현재 공유 worktree에는 UNIT-01/02/03/05 경로의 비커밋 변경이 보인다. 보존했으며 검사·stage·commit 대상에서 제외한다. 각 구현은 사용자 제공 commit/PR 목록을 받은 뒤 해당 revision으로 다시 검사한다.

## 계약 fixture와 제품 인수의 경계

| 요구 | 현재 증거 | 남은 제품 검사 |
|---|---|---|
| PDF hash, geometry, quote, 잘못된 locator 거부 | fixture validator에서 계약 hash/좌표/인용 negative cases PASS | 서버 업로드·파싱·원본 파일 hash 불변의 runtime 재검사 |
| 주석 upsert/delete/tombstone/중복 mutation | 10개 fixture sync step의 reference model PASS | 실제 서버 transaction, 다른 클라이언트 수신, app 재시작 복구 |
| Tutor event/citation/Reader/quiz/learning state | schema와 fixture linkage, native wire/replay fixture 검사 PASS | 실제 `/ws` streaming, 인용 이후 Reader 명령, durable quiz/mastery/memory 저장·재시작 |
| 마이그레이션·export | 이번 검사에서 실행 안 함 | UNIT-01 storage/migration 적용 뒤 원본 보존, export 산출물, rollback 검사 |
| 사설 접속·최소 보호·secret | Compose loopback 기본값, Redis 비공개 포트, Compose env의 key/token/secret 부재를 정적 검사 | 앱 pairing/Origin 보호는 UNIT-02, WSL2 firewall/Tailscale는 실제 기기에서 검사 |
| 백업·복원 | 중지·tar·복원 절차만 문서화 | Docker daemon 복구 후 실제 데이터를 넣어 restore smoke test |
| LLM no-secret 경로 | PublicSettings의 secret 필드 거부 fixture PASS | test-only provider는 제품 경계에 구현되지 않아 미검증. 실제 provider 연결은 별도 실행 필요 |

fixture PASS는 표의 runtime 검사를 완료했다는 뜻이 아니다.

## Codex Cloud 및 재현 명령

새 환경의 install command:

```sh
python3 -m pip install -r checks/requirements.txt
```

fixture check command:

```sh
python checks/validate_contracts.py
python checks/source_adapters.py
```

`--require-ready`는 ownership 목록과 모든 등록 seam이 실제 파일에 연결된 뒤 실행한다. 현재는 ownership 검사 실패가 확인됐다. 웹 검사에는 upstream 지침대로 Node 22와 `npm ci --legacy-peer-deps`, `npm run check`가 필요하다.

WSL2 운영은 저장소를 Linux 파일시스템에 두고 다음 명령을 `upstreams/DeepTutor`에서 실행한다. Compose 정적 검사만 확인했으며 빌드·기동은 daemon 복구 후 실행한다.

```sh
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml up -d --build
docker compose -f compose.yaml ps
curl -fsS http://127.0.0.1:8001/health/ready
```

기본 게시 주소는 loopback이며 `DEEPTUTOR_BIND_ADDRESS`, `HOST_PORT_BACKEND`, `HOST_PORT_FRONTEND`로 바꿀 수 있다. LAN 공개가 필요하면 Windows Firewall에서 지정한 사설 인터페이스/기기만 허용하고, 라우터 port-forward는 만들지 않는다. UNIT-02의 pairing/Origin 보호 구현 전에는 외부 인터페이스로 바인딩하지 않는다. Tailscale 경로와 Windows Firewall 동작은 실제 WSL2 기기에서 확인 대기다. Codex Cloud 프로젝트의 install/start/check 설정은 이 저장소 작업에서 변경할 수 있는 UI/API가 확인되지 않아 위 명령을 설정 문서로 남긴다.

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
2. Python backend production lock을 위한 신규 경로(예: `upstreams/DeepTutor/uv.lock`)와 root CI 파일(예: `.github/workflows/mnemosyne.yml`)을 UNIT-06에 배정한다. 현재 할당된 `.github/workflows/tests.yml`은 upstream 하위 경로라 이 Mnemosyne root 저장소의 GitHub Actions workflow로 실행되지 않는다.
3. 목표에서 지정한 `docs/handoffs/unit-06.md`는 현재 정확한 소유 목록에 없고 기존 배정 파일은 `handoff/UNIT-06.md`다. 이 handoff는 허용된 경로를 사용했다. 새 문서 경로를 원하면 먼저 배정한다.
4. Compose 원본 snapshot 파일 변경의 사유와 SHA-256 `d2e88f60c274305012835dfd3c0f533fe19ab7664412c0c6c83b43c74e2e3d74`을 `integration/upstreams.json`의 수정 예외에 반영한다. 해당 파일은 통합 담당 소유라 여기서는 고치지 않았다.
5. 사용자 제공 UNIT-01/02/03/04/05 commit/PR 목록을 받으면 각 정확한 revision에서 통합 검사와 소유 gate를 재실행한다. UNIT-02는 Tutor 언어 분리 assertion을 확인하고, UNIT-04는 iPad simulator/device 검증 결과를 제공해야 한다.

## 대기 인수

- 실제 Windows/WSL2 설치·기동·재시작·백업/복구 확인
- 실제 iPad에서 Pencil 입력, 오프라인 저장, 종료/재시작 복구 확인
- 실제 LLM provider 연결(명시적 테스트 자격증명 사용, 로그/fixture에 secret 금지)
- Docker daemon 복구 후 이미지 build, Compose up, `/health/ready`, Redis 및 DB 재시작 복구 확인
- Node 22 웹 검사, GitHub Linux/macOS/Xcode CI 결과
