# 통합 경계와 시작 조건

## 현재 상태

계약 `0.1.0-draft.1`, 실제 소스 미연결, 제품 API/빌드/transport 미검증. `integration/registry.json`의 `ready_for_parallel_implementation=false`. 지금 commit은 **검토용 준비 초안**이며 여섯 제품 작업의 시작 SHA가 아니다. 원본 upstream을 확인하기 전 새 backend/iPad/web 구조를 강제로 만들지 않는다.

## 등록 함수 후보

아래 이름은 통합 경계를 명세하는 **새 인터페이스 후보**이며 실제 upstream 심볼이 아니다. 언어의 await/error 타입과 실제 symbol/path는 소스 감사 후 registry에 고정한다. 각 유닛은 자신의 adapter를 내보내고 통합 담당만 기존 assembly에서 한 번 등록한다.

| 유닛 | export 후보와 입력 | 제공 port | 소비자 |
|---|---|---|---|
| 01 | `register_library(host, config)` | DocumentRepository, DocumentSearch, CitationVerifier, AnnotationSync | Tutor 02, client 04/05, assembly |
| 02 | `register_tutor(host, document_search, citation_verifier, learning_store, provider)` | TutorRuntime, LearningStateStore, capability registry | API assembly, client 04/05 |
| 03 | `make_reader_facade(local_config)` | ReaderFacade와 원자 local store/outbox | iPad 04 |
| 04 | `make_ipad_app(reader_facade, api_client, sync_worker)` | 앱 root/화면, network/worker | 앱 진입점 자체 소유 |
| 05 | `mount_mnemosyne_web(api_config)` | web root, PDF viewer/event consumer | 웹 진입점 자체 소유 |
| 06 | `run_integration_checks(config)` | 설치·실행·CI·health smoke 및 검사 | 개발자/CI |

공통 host는 router/container/상태 조회의 최소 조립 객체다. 유닛이 전역 singleton/import side effect로 router를 등록하지 않는다. DB session/UoW는 UNIT-01이 제공하고 UNIT-02가 학습 port 구현에 사용한다. UNIT-02가 DB schema를 직접 만들지 않는다. plugin/capability 등록에는 필수 `chat, reading, quiz, assessment, mastery, solve, memory, progress, review`가 모두 있어야 한다. 없어도 성공으로 표기하는 경량화는 금지한다.

## port 메서드와 데이터

- DocumentRepository(01): `get_document(id, version?)`, `get_page(id, version, page_index, parse_revision)`, `get_asset(id, version, asset_id)`; 외부 path를 받지 않는다.
- DocumentSearch(01): `search(document_ids, query, language, limit)` → score+anchor+segment geometry. 문서 접근·준비 상태를 확인한다. 실제 embedding/vector store adapter를 재사용한다.
- CitationVerifier(01): `verify_citation(anchor)` → 검증된 citation 또는 ErrorEnvelope. page/text/hash/geometry를 서버 데이터로 대조한다. Tutor가 `verified:true`를 직접 만들어내지 않는다.
- AnnotationSync(01): `apply_mutations(batch)`와 `snapshot(document,version)`, `changes(cursor,limit)` → 공통 schema. 멱등 receipt+revision+log는 한 transaction.
- LearningStateStore(02): `get_state(document_id)`, `save_activity(activity, mutation_id, base_revision)`, `submit_attempt(attempt)`, `review_memory(review)` → learning snapshot/receipt. DB schema 변경은 `handoff/UNIT-02.md`에 migration 요구로 01에 전달한다. mutation receipt와 파생 상태 갱신을 한 UoW로 묶는다.
- TutorRuntime(02): `create_turn(request)`, `subscribe(turn_id,after_event_id)`, `cancel(turn_id)`; 후보 외부 SSE를 기존 streaming에 adapter로 연결한다. token/secret은 서버에만 있다.
- ReaderFacade(03): `open_cached(document,version)`, `download_state()`, `get_context()`, `goto(target)`, `show_highlight(target,ttl)`, `flash(target,ttl)`, `propose_annotation(event)`, `commit_local_edit(edit)`, `undo()`, `redo()`, `pending_mutations(limit)`, `apply_sync_receipts(receipts)`, `apply_remote_page(changes,cursor)`, `export_annotated_copy()`.
- local store/outbox(03): page position, immutable PDF cache+hash, ink/annotation draft, mutation receipt, last event seq/approved annotate event ID/cursor를 원자적으로 저장한다. UNIT-04 worker는 facade API만 사용한다. 로컬 저장 성공 전에 `기기에 저장됨`을 표시하지 않는다.

언어 중립 port DTO는 `models.schema.json`, `annotations.schema.json`, `events.schema.json`을 사용한다. HTTP DTO와 internal transaction은 구별하되 문서/version/좌표/offset 의미를 바꾸지 않는다. 취소·오류를 숨기는 빈 성공 값은 반환하지 않는다.

## 실행·통합 순서

1. 정확한 두 소스를 연결해 UPSTREAM-AUDIT의 URL/SHA/LICENSE/명령/transport/저장 구조를 채운다. 기존 경로를 유지한다.
2. 실제 파일 소유표와 registry의 symbol/path를 고정하고 통합 담당이 최소 등록 adapter/assembly 변경을 커밋한다. 아직 어떤 제품 코드도 이 준비에서 만들지 않았다.
3. source-backed 계약을 확정하고 fixture에 실제 parser/Reader adapter의 대응 결과를 추가한다. 외부 streaming은 하나만 선택한다. 클라이언트 모델/codegen을 실제 스택에서 검사한다.
4. UNIT-06은 실제 backend/web/iPad build 명령과 WSL2/Docker 실행을 연결한다. 통합 담당은 각 port의 signature/import 검사를 실행한다.
5. 같은 기준 SHA와 contract digest를 여섯 작업에 전달한다. 작업별 브랜치에서 단독 소유 파일만 수정한다. 시작 후 공통 contracts/assembly는 통합 담당을 통해 변경한다.
6. Library/storage → Tutor/learning → Reader/app/web 소비 경계를 실제 서버에서 통합 검사한다. 이것은 **통합 순서**이며 필수 제품 기능의 후속 phase 이관이 아니다.

## 기준 commit과 두 저장소 배포

검토용 준비 commit은 `git rev-parse codex/mnemosyne-bootstrap`으로 확인한다. clean 상태, `contracts/manifest.json` digest, `integration/registry.json` 상태를 함께 보관한다. 확정 시작은 모든 upstream SHA와 실제 경로가 등록되고 `checks/validate_contracts.py --require-ready`가 성공한 뒤 통합 담당이 immutable tag를 만든다. source tree가 dirty하면 확인한 변경 diff와 기준 commit을 별도로 기록한다.

두 저장소인 경우 각 소스는 원래 경로와 independent commit을 유지한다. 계약은 준비 저장소의 동일 immutable bundle을 `vendor/mnemosyne-contracts/` **후보** 위치에 배포하되 실제 기존 vendor 관례에 맞춰 최종 위치를 기록한다. registry에 각 source SHA와 contract bundle SHA/digest를 기록하고 양쪽 CI가 fixture를 소비한다. 후보 vendor 위치가 기존 레이아웃 재배치를 지시하는 것은 아니다. 단일 저장소인 경우 루트 계약을 직접 소비한다.

## 실제 제품 인수 검사

UNIT-06은 real adapter를 사용한 문서 업로드/파싱/검색/인용 검증, 2-device 수정·삭제·재전송·cursor 만료, turn resume/cancel/error, 전체 학습 capability 저장/복구, 원본 hash 보존/파생 export를 검사한다. iPad는 실제 Pencil/오프라인/앱 재시작/가로세로 geometry, Mac은 실제 PDF rendering과 ink 표시/근거 이동을 검사한다. mock/fixture 성공을 이 결과로 대체하지 않는다.

## 남은 필수 입력

정확한 Pumice와 DeepTutor URL/로컬 경로 및 ref, 실제 제품 저장소 연결, PR용 remote. 저장소에 git identity가 없어 준비 commit은 명시된 `Codex Bootstrap <codex-bootstrap@localhost>` identity로 기록한다. 제품 경로·라이선스·build·transport·시작 SHA와 cloud repository 접근성은 아직 확정할 수 없다.
