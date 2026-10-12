# Mnemosyne integration handoff

기준 브랜치 `origin/main` / `16130d21410d1b2349ffee0757d44462c899ebbf`, 준비 기준 `5715a32927e3a73dc28782d306880e3dd1f62441`. 현재 작업 브랜치는 `codex/mnemosyne-integration`이다. 기본 브랜치에는 직접 반영하지 않았다.

## 확인된 유닛 결과

| Unit | 적용한 정확한 결과 | 통합 상태 |
|---|---|---|
| UNIT-01 | `codex/unit-01-library-sync` · `c1f1f16b1cf12c9e66da1b3f24755cdb1412550f` · [Draft PR #2](https://github.com/rightheous/mnemosyne/pull/2), 아직 main에 미병합 | integration branch에 clean merge. Library adapter와 보존 가능한 PDF/주석 서비스 포함. API router는 bearer/Origin guard 뒤 startup에 등록. 실제 fixture upload/parse/search/annotation/export 흐름을 확인했다. |
| UNIT-02 | 별도 branch/PR 없음. 기준 `main` HEAD `16130d21410d1b2349ffee0757d44462c899ebbf`가 사용 가능한 결과 | Tutor adapter 포함. LearningStateStore 실제 구현과 HTTP 학습 route는 없음. |
| UNIT-03 | 사용자 제공 ref: `codex/unit-03-reader` · `ae202f0cf1096d5fcc0ab1ecd325ac20a0d8e4b1` · PR 없음 | 소스 객체를 현재 workspace의 local refs/object DB나 `origin`에서 가져올 수 없어 diff를 확인하거나 통합하지 못했다. 정확한 branch fetch는 `couldn't find remote ref`, SHA fetch는 `not our ref`, GitHub commit API는 422 `No commit found for SHA`를 반환했다. 현재 Pumice tree에는 concrete durable Reader/local store 구현이 없다. |
| UNIT-04 | `codex/unit-04-ipad-app` · `ced01afba5138598601c3b25933329d23a41282b` · [Draft PR #3](https://github.com/rightheous/mnemosyne/pull/3), 아직 main에 미병합 | integration branch에 clean merge. App composition은 UNIT-03 concrete type을 참조하므로 제품 빌드 차단. 개발 유닛 번호가 표시되던 사용자 문구는 제거. |
| UNIT-05 | `codex/unit-05-api-refresh` · `e22a0e9d421adf3020e5359dcbda541e5ba378e0` · [Draft PR #4](https://github.com/rightheous/mnemosyne/pull/4) | 통합 branch에 clean merge. native Tutor capability 선택, Reader 화면/PDF geometry, save 실패 입력 유지 및 확인 UI를 보완. 서버 Reader context/document resolver/Tutor·learning API가 없어 전체 학습 흐름은 아직 확인하지 못함. |
| UNIT-06 | `codex/unit-06-cloud-status` · `e14c599cb9977a41f5f17358a9ca17f33bce2327` · [Draft PR #1](https://github.com/rightheous/mnemosyne/pull/1), 아직 main에 미병합 | integration branch에 clean merge. Compose에 브라우저 origin 설정을 전달하도록 연결. 현재 Cloud 설정에는 Git/LLM secrets와 실행 capability가 없음. |

사용자가 UNIT-03 branch/SHA를 제공했으나 그 ref의 소스는 현재 checkout과 origin에서 확인되지 않아 코드 통합을 보류했다. 단독 UNIT-03 PR은 앞서 자동 승인 검토가 `429 Too Many Requests`로 중단됐다는 사용자 보고가 있어 다시 만들지 않았다. UNIT-05 정확한 branch/commit과 Draft PR #4는 확인 후 integration branch에 통합했다. UNIT-01/04/06의 PR #2/#3/#1은 계속 열린 draft이며, 해당 변경은 이 통합 branch에만 포함돼 있다.

## 실제 통합 변경

- `api/main.py` lifespan이 `register_mnemosyne`로 만든 동일 서비스에 Library HTTP router를 연결한다. 모든 Library route는 일회성 페어링으로 발급한 bearer 또는 HttpOnly cookie, Origin 검사 뒤 실행된다.
- `mnemosyne/security.py`, `http.py`, `pairing.py`는 10분·1회 pairing code, 90일 만료/폐기 가능한 bearer session, 경로 `/v1` HTTP 보호, browser cookie WebSocket bridge, exact Origin 정책을 제공한다. code/token 원문은 state file에 저장하지 않으며 Linux file lock + atomic replace를 쓴다. `ws://`/`wss://` 내부 Origin 비교와 `MutableHeaders`의 실제 삭제 API 결함을 live bridge 확인 중 찾아 수정했다.
- `GET /v1/readiness`는 현재 실제 의존성 상태를 반환한다. learning store/provider가 없는 현재 서버는 `degraded`이며 필수 capability를 제공한다고 보고하지 않는다.
- Compose는 `MNEMOSYNE_ALLOWED_ORIGINS`를 backend에 전달한다. 브라우저 공개 origin은 reverse proxy 앞 주소로 정확히 지정해야 한다.
- `register_mnemosyne`는 RAG, provider callbacks, learning store를 실제 container에 제공될 때 명시적으로 연결할 인자를 받는다. 지금 container에는 해당 adapter가 없어 값을 조립하지 않는다.
- iPad 화면의 `UNIT-03`/facade 개발 상태 문구를 사용자용 오류/연결 상태로 바꿨다. 앱의 concrete Reader 구현은 공급되지 않아 빌드는 되지 않는다.

## 기능 상태

| Requirement | 구현 상태 | 이 통합에서 확인한 상태 |
|---|---|---|
| R01 Library, 과목, PDF upload/delete | server adapter 및 guarded router 연결 | 2쪽 PDF fixture의 upload/parse/page/search/source verification은 live HTTP로 통과. RAG indexing은 `llama_index` 부재로 `failed`; 문서 삭제 경로는 별도 미검증. |
| R02 Reader open/search/position | UNIT-04 호출자 코드 있음, web page API 존재 | 서버 page/search 응답은 확인. 실제 Pumice Reader facade/local store 부재로 iPad open/selection/position 복구는 차단. |
| R03 Pencil/undo/redo/geometry | 계약·consumer 예상값과 App seam 있음 | 실제 Reader/Pencil 구현·기기 검증 없음 |
| R04 주석·필기·tombstone·export | server sync/export adapter 있음 | live HTTP annotation retry/delete tombstone/SQLite reopen/export 및 원본 SHA 불변 확인. iPad local sidecar와 두 기기 sync는 미검증. |
| R05 offline/outbox/retry | 요청/adapter 경계만 있음 | durable local store 부재 |
| R06 central document storage/index | Library persistent adapter/router 등록 | original/page/annotation SQLite 저장과 재시작 복구 확인. fixture indexing은 `failed` (`llama_index` 미설치); provider 적용 및 실제 vector/RAG 준비는 미완료. |
| R07 Tutor/Quiz/Mastery/Memory/Progress | Tutor service adapter/UI source 존재 | durable `LearningStateStore`, mounted HTTP routes 없음; 부분 기능을 후속 완료로 표시하지 않음 |
| R08 Mac web flow | Korean pages/routes/API consumer 및 UNIT-05 UI/API consumer 보완 포함 | 통합 검사: contract/typecheck 통과, Node 1,310개·unit 656개 통과, UNIT-05 화면 관련 12개 통과. Next production build는 Google Fonts fetch로 막혔고 실제 브라우저/Tutor API 흐름도 미검증. |
| R09 Korean UI/Tutor | 한국어 화면·prompt adapter 존재 | actual provider/LLM 호출 없음 |
| R10 verified citation and Reader targeting | Library/Tutor citation verification code 존재 | `/v1/tutor/turns` route가 없어 end-to-end 이동/강조 미검증 |
| R11 WSL2/Docker | upstream Docker/Compose files 유지, origin env 연결 | Docker daemon에 접근 권한이 없어 실제 기동 불가; 실제 Windows 미검증 |
| R12 replaceable OpenAI-compatible LLM | UI/contract model exists | settings callbacks와 runtime provider apply가 조립되지 않음 |
| R13 pairing/Origin/errors | pairing/session, bearer+cookie guard, exact Origin checks added | live HTTP에서 pairing/replay/auth/degraded readiness/Origin/CSRF/revocation, ASGI WebSocket bridge 통과. account boundary는 personal single-session scope. |
| R14 shared start/gates | exact base, sources, contracts, route wiring recorded | contract/source/ownership gates 통과. Cloud, Google Fonts 차단된 web production build, Docker 기동, Xcode/iPad 인수 미실행; `product_ready=false` 유지. |

## 실행과 미확인 환경

이번 작업에서 실행한 명령과 결과는 [docs/VALIDATION.md](../VALIDATION.md)에 기록했다. Cloud runtime은 연결됐으나 capability와 credentials 배열이 비어 있다. Docker local socket은 `permission denied`다. `llama_index`와 LLM credentials가 없어 실제 인덱싱/LLM 요청은 확인하지 못했다. Xcode/iPadOS SDK·실제 기기는 현재 executor에 없다.
