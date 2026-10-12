# 공통 시작점과 연결 경계

계약 `0.1.0`. 현재 통합 작업 branch `codex/mnemosyne-integration`은 확인된 UNIT-01/04/06 PR을 준비 기준 `5715a32927e3a73dc28782d306880e3dd1f62441`에서 갈라진 `origin/main` 위에 합쳤다. Library router와 pairing/session 경계도 연결했다. `product_ready=false`이며 UNIT-03 concrete Reader와 durable LearningStateStore/API는 공급되지 않았다. 세부 refs와 기능별 상태는 `docs/handoffs/integration.md`를 본다.

## 실제 등록 함수와 호출자

경로는 준비 저장소 기준이다. registry의 source_paths와 ownership.json은 파일 단위의 판정 기준이다.

| 담당 | 실제 등록 경로 / 심볼 | 입력·반환 / 연결 책임 |
|---|---|---|
| 01 | upstreams/DeepTutor/deeptutor/mnemosyne/library.py · register_library(store, annotation_sync=None) | ReadingStore→LibraryAdapter(search, verify_anchor). AnnotationSync/UUID mapping/DB transaction 구현. 02가 검색/검증을 호출. |
| 02 | upstreams/DeepTutor/deeptutor/mnemosyne/tutor.py · register_tutor(turns, library, learning_store=None) | 기존 container.turns + 01 ports→TutorAdapter. 한국어 native request와 metadata.mnemosyne 이벤트 구현. LearningStateStore 구현은 없음. |
| 03 | upstreams/Pumice/Packages/PumiceCore/Sources/PumiceCore/Mnemosyne/ReaderFacade.swift · makeReaderFacade(factory, localStore) | protocol/factory seam만 있음. 실제 factory가 필요하나 참조된 UNIT-03 SHA는 제공 저장소에서 찾을 수 없어 연결되지 않음. |
| 04 | upstreams/Pumice/App/MnemosyneAppDependencies.swift · makeIPadApp(reader,syncWorker,serverURL) | app dependency seam와 Sources/Network/MnemosyneTurnWire.swift의 native frame decoder. 04가 PumiceApp/LaunchView에서 실제 화면을 연결. 네트워크 worker는 facade만 호출. |
| 05 | upstreams/DeepTutor/web/features/mnemosyne/register.ts · mountMnemosyneWeb(dependencies) | native StreamEvent consumer와 한국어 화면이 `app/(workspace)/learning/` 및 settings route에 연결돼 있음. API end-to-end는 server handler 부재로 미완료. |
| 06 | checks/source_adapters.py · run_integration_checks() | 실제 upstream import/ReadingStore/PDF/parser/native protocol/등록 검증. scripts/Docker/CI 및 manifests 소유. |
| 통합 | `mnemosyne/bootstrap.py::register_mnemosyne`, `mnemosyne/http.py::router`, `library.py::build_library_router` | main.py lifespan에서 서비스 등록과 Library router 조립. Session/readiness route는 static mount, Library route는 실제 서비스 생성 후 bearer/Origin dependency와 함께 mount. |

서버 DocumentRepository는 get_document(document_id,version_id?), get_page(document_id,version_id,page_index,parse_revision), get_asset(document_id,version_id,asset_id)다. 실제 구현은 UNIT-01이며 Tutor는 UUID/version 매핑과 접근 검증을 이 경계에서 받아야 한다. 기존 ReadingStore의 OS 경로를 client에 노출하지 않는다.

서버 AnnotationSync는 apply_mutations(batch), snapshot(document_id,version_id), changes(cursor,limit). LearningStateStore는 get_state, submit_attempt, save_activity(activity,mutation_id,base_revision), review_memory. 공통 DB/UoW는 01, 학습 서비스 의미는 02. persistence 변경 명세에는 schema·migration·transaction·롤백·검증을 넣어 01에 전달한다.

Reader facade는 openCached, installDownloadedOriginal, downloadState, readerContext, applyReaderEvent, commitLocalEdit, undo/redo, pendingMutations, applySyncReceipts, applyRemotePage, exportAnnotatedCopy를 고정했다. 각 Data는 계약 DTO JSON이다. 03은 durable 저장·pending outbox·받은 cursor와 receipts·승인 annotate event ID를 원자 보관한다. 04가 다운로드한 임시 파일을 facade에 넘기면 03이 원본 full hash를 검증하고 atomic cache install한다. downloadState의 cached는 검증된 durable 파일에만 해당한다. 04는 Reader DB 파일을 직접 열지 않는다. 03은 네트워크를 만들지 않는다. 05는 iPad ink를 표시만 한다.

## 실제 transport와 API 구현 상태

`/ws`, protocol 2.0을 재사용한다. HTTP turn 생성/취소와 SSE 후보는 제거했다. start_turn/subscribe_turn/resume_from/cancel_turn은 원래 command schema를 사용한다. 모든 native persisted frame.seq를 checkpoint한다. semantic `metadata.mnemosyne`만 거르면 seq가 비어 있을 수 있으므로 그 subset을 다시 1부터 세지 않는다. recoverable native error를 terminal로 오인하지 않는다. native done metadata.status가 completed/failed/cancelled일 때 정확히 하나의 semantic terminal을 싣는다.

`contracts/openapi.yaml`의 `x-implementation=observed-upstream`은 실제 `/health`, `/ready`다. `integration-branch-guarded`는 이 branch에서 pairing bearer/Origin guard 아래 router가 실제 mount된 operation이다. `planned-unit-extension`은 아직 route가 없는 Tutor/learning operation이다. settings handler는 mount됐지만 provider defaults/secret writer/runtime apply callback이 없어 제품 provider 기능은 degraded다. 네이티브 websocket schema는 원래 Pydantic export의 byte-identical copy다. 공통 models/events/annotations는 새로운 Mnemosyne 경계다. upstream REST를 전부 대체하거나 native schema를 임의로 갈아엎지 않는다.

## 계약 배포와 동일 버전

루트 contracts/가 유일한 편집 원본이다. 두 snapshot에는 `MnemosyneContracts/`에 동일한 바이트를 복사했다. `python checks/sync_contracts.py --check`와 `validate_contracts.py --require-ready`가 버전·전체 file digest·두 복사본·원래 소스 provenance·등록 심볼·단독 소유를 확인한다. 복사본은 통합 담당만 generator로 갱신한다. unit은 API 소비 코드만 수정한다.

소스 트리 안에서 각각 독립 작업/빌드할 수 있고 모든 내부 상대 경로는 보존했다. 새로운 파일은 소유자가 먼저 배정한다. 원래 파일의 개발 지침과 license도 그대로 보존한다. `.git`를 중첩해 gitlink로 만들지 않는다.

## 실행과 후속 통합

1. 여섯 branch 모두 아래 시작 SHA와 contracts/manifest.json digest에서 출발한다. 첫 단계에서 각 handoff와 정확한 소유 파일 목록을 읽는다.
2. 01 저장/검색/인용/sync와 03 로컬 facade를 구현한다. 02는 ports를 소비하며 학습 persistence 요구를 01에 전달한다. 04/05는 fixture와 같은 계약으로 UI/네트워크를 독립 구현한다. 06은 기존 manifests/CI/Docker를 연결한다.
3. 서버 main/container/routes의 변경은 통합 담당이 등록 함수만 연결한다. 제품 callback은 각 유닛 파일에 두고 공통 파일 편집 경쟁을 피한다.
4. 실제 upload/parse/search/citation, 두 기기 수정·삭제·retry/cursor expiry, 학습 상태 저장·재시작, WS resume/cancel/error, 원본 hash/파생 export를 통합 검사한다.
5. iPad 오프라인 필기·앱 종료 복구·회전/줌/Pencil, 웹 PDF/ink/한국어 전체 학습, Windows WSL2 설치·재시작·백업 복구를 제품 인수로 검사한다. 준비 fixture 성공으로 대체하지 않는다.

이것은 dependency 통합 순서다. Chat/Reading/Quiz/Assessment/Mastery/Solve/Memory/Progress/Review나 오프라인을 후속 phase로 미루는 뜻이 아니다.

## 시작 commit 확인

`git rev-parse mnemosyne-bootstrap-v0.1.0^{commit}`이 확정 시작 SHA다. tag는 마지막 검사와 commit 이후 만든다. 문서에 자기 자신 commit SHA를 써서 순환시키지 않는다. registry는 두 upstream SHA와 contract digest를, 로컬 tag는 공통 시작 SHA를 고정한다. 기본 브랜치에는 통합하지 않는다.

GitHub remote는 `https://github.com/rightheous/mnemosyne`이다. 통합 branch는 기본 브랜치와 분리하며 draft PR로 검토한다. 연결된 Cloud runtime은 현재 execution capability/secrets를 제공하지 않으므로 실제 LLM/Docker/iPad/Xcode 검증 상태를 별도로 보고한다.
