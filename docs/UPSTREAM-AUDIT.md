# Upstream 감사

2026-10-08 (Asia/Seoul). **실제 Pumice/DeepTutor 소스 미확인.**

## 확인한 환경

- 현재 경로: `/Users/honghyeonseo/Documents/ChatGPT/므네모시네`.
- 초기 상태: `.git/`만 있음. 파일·커밋·remote 없음. 브랜치 `master`는 unborn 상태였음.
- 이 경로와 상위 디렉터리에 적용되는 기존 `AGENTS.md` 없음.
- 연결된 Codex 프로젝트 목록에는 이 빈 저장소와 비개발 공부 폴더만 있음. Pumice/DeepTutor 소스 프로젝트나 첨부 worktree 없음.
- 사용자에게 정확한 두 저장소 URL/로컬 경로와 기준 ref를 요청함. 동명 프로젝트를 웹에서 선택하거나 clone하지 않음.

## 필수 증거 표

| 항목 | Pumice | DeepTutor |
|---|---|---|
| 지정 URL/경로 | 제공 대기 | 제공 대기 |
| remote 및 branch | 미확인 | 미확인 |
| 기준 commit SHA | 미확인 | 미확인 |
| LICENSE/SPDX, NOTICE/재배포 조건 | 미확인 | 미확인 |
| 기존 AGENTS/개발 지침 | 미확인 | 미확인 |
| 실제 build/test 명령과 실행 결과 | 미확인 | 미확인 |
| 실제 파일/등록 지점 | 미확인 | 미확인 |
| API/기존 streaming transport | 해당 연결 미확인 | 미확인 |
| 저장 구조/migration | Reader 로컬 구조 미확인 | DB·원본·파싱·임베딩 구조 미확인 |

## 재사용·수정 후보 (소스 증거가 없는 요구사항 매핑)

Pumice에서 Reader/PDF 선택·검색·목차·읽기 위치/Pencil 코드의 재사용 가능성을 확인해야 한다. `ReaderFacade`는 새 경계 이름이며 upstream 클래스 이름이 아니다. 실제 관련 경로는 비워 두었다. 앱 화면과 Xcode 설정은 UNIT-04, PDF/Pencil 내부는 UNIT-03으로 나누되 실제 파일별 충돌을 감사해야 한다.

DeepTutor에서 파싱/RAG/문서 근거/각 학습 capability/모델 adapter/streaming/학습 상태 저장을 조사해야 한다. 아래 계약의 경로는 새 외부 후보 API이며 기존 API 이름이라는 주장이 아니다. 불필요한 서비스의 경량화가 필수 학습 capability를 제거해서는 안 된다. 웹 UI 재설계 범위와 서버 assembly/manifest의 실제 소유 경로는 미확정이다.

## 연결 후 감사 절차

1. 지정 URL/경로의 remote/ref/SHA와 dirty 상태를 기록한다. 사용자 변경을 보존한다.
2. AGENTS와 license/NOTICE, manifest/lockfile, README/CI에서 build/test 명령을 읽고 정확한 출처 경로를 기록한다.
3. Reader geometry/storage/undo, backend ingest/search/citation/runtime/streaming/database, web root를 실제 코드까지 추적한다. 관찰한 심볼·파일·행 번호를 표에 추가한다.
4. 사용 가능한 도구에서 build/test를 실행한다. 기기·WSL2·외부 LLM 부재는 미검증으로 남긴다.
5. 기존 streaming을 기준으로 외부 transport 하나를 선택한다. 후보 SSE와 upstream streaming adapter의 동작을 검증한다. 외부 SSE/WebSocket을 동시에 만들지 않는다.
6. 실제 경로를 `OWNERSHIP.md`와 `integration/registry.json`에 채우고 계약을 조정한다. 모든 필수 capability와 offline 저장소를 연결하는 최소 골격만 추가한다.

두 저장소라면 원래 레이아웃을 유지한다. 준비 저장소의 계약 묶음을 immutable tag/SHA+SHA-256 manifest로 각 소비 저장소에 배포하고 동일 digest를 CI에서 확인한다. 단일 저장소로 이미 제공된 경우 그 레이아웃의 `docs/`·`contracts/`를 사용한다. 현재 빈 폴더를 이유로 실제 upstream을 강제로 통합/재배치하지 않는다.
