# 공통 시작점과 연결 경계

계약은 `0.2.0`이다. `codex/mnemosyne-integration`은 사용자가 제공한 여섯
unit 결과를 준비 기준 `5715a32927e3a73dc28782d306880e3dd1f62441` 위에
통합한 별도 브랜치다. 기준 `main`은
`16130d21410d1b2349ffee0757d44462c899ebbf`다. 변경은 기본 브랜치에 직접
반영하지 않았다. 전체 unit SHA/PR과 요구사항별 상태는
[`docs/handoffs/integration.md`](handoffs/integration.md)를 본다.

현재 코드에는 Library, Tutor, 퀴즈/평가, 기억 카드, 복습, 진도의 실제
저장 경로가 있다. provider 자격증명·RAG 인덱스·Docker daemon·Apple SDK·기기
검증은 이 executor에서 사용할 수 없어 `product_ready=false`로 남긴다.

## 등록 함수와 실제 호출 경로

| 경계 | 구현과 연결 |
|---|---|
| 서버 조립 | `deeptutor/api/main.py` lifespan이 `register_mnemosyne`로 Library, Tutor, SQLite 학습 저장소, provider runtime, quiz generator를 구성하고, session 및 learning router를 등록한다. Library router는 같은 서비스 인스턴스에 bearer/Origin dependency를 붙여 장착한다. |
| Library/PDF | `LibraryAdapter`는 원본 불변 PDF, full SHA version, 파싱 page/asset, annotation sync, 검증 citation을 기존 `ReadingStore`와 연결한다. `resolve_reading_material(document_id, version_id)`는 저장된 문서 버전에서만 Tutor material ID와 revision을 가져온다. |
| Tutor | native `/ws` protocol 2.0을 유지한다. 웹과 iPad가 contract `0.2.0` `config.mnemosyne.turn_request`를 실어 보내며 adapter가 제출 ID, 한국어 응답, 문서 언어, 페이지, 선택 anchor를 검사한다. 선택 anchor는 Library에서 다시 검증한다. 재접속용 `GET /v1/tutor/turns/{turn_id}`는 durable turn/event log에서 receipt를 읽고 pairing/version guard를 적용한다. semantic event도 contract `0.2.0`을 기록한다. 외부 skill/MCP는 비활성화한다. |
| 학습 저장 | 통합 소유 `SQLiteMnemosyneLearningStore`는 Library의 개인 데이터 root 아래 `mnemosyne-learning/learning.sqlite3`에 quiz, 비공개 채점 자료, 평가 시도, mastery, memory, progress/activity mutation을 transaction으로 쓴다. SQLite schema version 2를 사용하며 고정 임시 메모리 store를 사용하지 않는다. |
| 퀴즈/평가 | `POST /v1/documents/{id}/quizzes`는 실제 parsed page로 생성하고 citation을 검증한 뒤 공개 문제와 비공개 grading 데이터를 분리 저장한다. 같은 mutation의 재시도는 저장된 문제를 반환한다. 평가 attempt ID/client mutation ID도 SQLite transaction과 lease로 중복을 차단한다. |
| 진도/복습 | `POST /v1/documents/{id}/progress`는 실제 parsed page를 확인하고 page 집합·마지막 페이지·측정 초를 transaction으로 기록한다. 같은 mutation은 한 번만 반영한다. web은 보이는 Reader의 실제 elapsed time을 outbox에 저장하고, iPad는 실제 페이지 변경을 durable UserDefaults queue로 전송한다. Memory review는 저장된 카드와 revision을 검사한다. |
| 웹 | 한국어 Reader/Tutor/Quiz/Learning 화면은 guarded API facade와 같은-origin cookie를 사용한다. Tutor start command는 versioned envelope를 포함하고, 재접속은 기존 turn ID/sequence를 사용한다. PDF page, citation, note/ink sync, progress를 기존 화면에 연결한다. |
| iPad | `makeIPadApp()`이 UNIT-03 persistent Reader facade/local store와 UNIT-04 network/API를 조립한다. Tutor composer는 실제 Reader selection을 검색·검증하고 같은 native turn envelope로 보낸다. page change는 같은 API로 mutation queue에 쌓이며 response loss/offline 재전송은 동일 ID를 사용한다. 원본 캐시와 sidecar 필기/주석은 구분한다. |
| 계약 | `contracts/`가 유일한 원본이다. quiz generation 및 progress mutation DTO/fixture, OpenAPI, validation consumers를 함께 업데이트해 0.2.0을 기록하고 `checks/sync_contracts.py`로 두 snapshot에 복사한다. |
| 배포 | `upstreams/DeepTutor/compose.yaml`의 `MNEMOSYNE_ALLOWED_ORIGINS`가 exact browser-origin 설정을 service로 전달한다. 기본 bind는 loopback이고 데이터는 `data/` volume에 둔다. 실제 이미지 build/start와 Windows WSL2 복구는 별도 검증이다. |

## 보호와 멱등성

HTTP write는 paired bearer 또는 HttpOnly cookie, exact Origin, contract version,
request ID 경계를 쓴다. 브라우저 WebSocket cookie는 `/ws` 요청 동안 내부
DeepTutor 인증으로 변환되며 pairing secret은 URL에 넣지 않는다. Provider API
key는 서버의 private system store에만 쓰고 로그·공개 설정·웹 응답에 포함하지
않는다.

Quiz create, assessment attempt, progress, annotation sync는 mutation identity와
payload를 영속 보관한다. progress revision 충돌 시 client가 최신 state를 받아
같은 mutation ID와 동일 page/time payload로 재시도한다. 삭제 annotation은
tombstone과 cursor로 sync하고 export는 별도 파생 PDF를 만든다. 원본 경로는
서버가 관리하며 export가 원본을 덮어쓰지 않는다.

## 검토 가능한 반복 실행

통합 저장소 root에서 `python -m pip install -r checks/requirements.txt` 후
`python checks/sync_contracts.py --check`,
`python checks/validate_contracts.py --require-ready`,
`python checks/source_adapters.py`,
`python checks/integration_pdf_flow.py --allow-index-unavailable`,
`node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON checks/web-consumer.mjs`를
실행한다. 웹 typecheck/build, 실제 provider 호출, Compose 기동, Xcode 및 Pencil
검증은 각각 실제 toolchain/network/device가 있는 환경에서 실행한다. 이
fixture/adapter 검사는 해당 제품 수락 검사를 대신하지 않는다.

## 확정 시작점

`mnemosyne-bootstrap-v0.1.0`은 통합 시작 commit
`5715a32927e3a73dc28782d306880e3dd1f62441`을 가리킨다. 통합 브랜치에는
새 contract manifest digest와 unit source SHA를 기록한다. 검토 대상은 draft
PR #5이며 기본 브랜치에는 바로 통합하지 않는다.
