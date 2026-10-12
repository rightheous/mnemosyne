# 요구사항과 성공 조건

기준 계약 `0.1.0` · 통합 계약 `0.2.0` · 2026-10-08 · 출처: 사용자가 제공한 목표 파일. 아래는 구현 완료 보고가 아니라 이번 개발 범위다. 공통 준비와 제품 구현은 구별하며 필수 기능을 phase 밖으로 미루지 않는다.

## 제품 경계

한 사람이 개인 공부에 사용한다. iPad 네이티브 PDF Reader는 정확히 지정된 Pumice, 서버는 정확히 지정된 DeepTutor를 재사용한다. Mac은 웹을 사용한다. 기존 언어·프레임워크·저장소 레이아웃을 최대한 유지한다. 원본 PDF는 불변이며 주석·필기는 별도 저장한다. 주석 포함 내보내기는 파생 파일을 생성한다.

## 필수 범위

| ID | 요구사항 | 성공 조건 / 제품 검증 |
|---|---|---|
| R01 | Library, 과목 관리, PDF 업로드·삭제·읽기 | Mac/iPad가 같은 과목·문서를 표시한다. 업로드 hash와 원본 version이 같고 파싱 준비 상태를 구분한다. 삭제는 확인된 문서만 대상으로 한다. |
| R02 | iPad PDF 열람·텍스트 선택·검색·목차·읽던 위치 복구 | 실제 PDF에서 선택·검색 결과가 해당 문장/페이지로 이동한다. 앱 재시작 후 문서 version과 읽던 위치가 복구된다. |
| R03 | Pencil 펜·형광펜·지우개·undo/redo | 실제 iPad에서 입력과 로컬 저장이 네트워크 응답을 기다리지 않는다. 전체 획 지우기가 기본이다. 회전/CropBox/줌에서 위치와 굵기가 유지된다. |
| R04 | 하이라이트·노트·북마크 및 별도 필기 저장 | 주석과 원본 hash가 분리된다. 삭제 tombstone과 undo 새 mutation이 두 기기에서 일관된다. 주석 포함 PDF가 원본을 덮어쓰지 않는다. |
| R05 | 오프라인 PDF 읽기와 Pencil 필기 | 다운로드 완료 문서를 비행기 모드에서 열고 필기·앱 종료·재시작 후 복구한다. 연결 복구 후 중복 없이 outbox를 처리한다. |
| R06 | 서버 중앙 저장 | 원본, 파싱 페이지/텍스트, 그림, 임베딩, RAG, 주석, 학습 기록을 중앙에 보관한다. 삭제·재색인·준비 실패 상태가 추적된다. |
| R07 | Chat, Reading, Quiz/Assessment, Mastery, Deep Solve, Memory, Progress/Review | 각 capability가 실제 문서 근거를 사용하고 화면/API에 연결된다. 문제, 시도, 평가, mastery, memory, 진도/복습 상태가 재시작 후 보존된다. 어떤 필수 capability도 제거하거나 후속 phase로 미루지 않는다. |
| R08 | Mac 웹 전체 학습 흐름 | 과목/Library, PDF 읽기, 하이라이트/노트, iPad 필기 표시, Tutor, Quiz/Mastery/Memory/Progress, 모델·서버 설정을 실제 브라우저에서 검증한다. 손필기 편집 UI는 제공하지 않는다. |
| R09 | Mnemosyne 전용 한국어 UI/Tutor | 재사용 라이브러리의 기본 화면을 그대로 제품 화면으로 노출하지 않는다. 기본 응답 언어는 `ko`, 문서 언어는 별도 필드다. 영문 원문 인용, 수식, 코드를 번역해 변형하지 않는다. |
| R10 | Reader 옆 Tutor와 문서 근거 | 검증된 문서 version·물리 페이지·텍스트 범위로 이동/강조한다. 잘못된 quote/사각형/문서 version은 Reader 명령 생성 전에 거부한다. 근거가 없으면 한계를 알리고 위치를 만들어내지 않는다. |
| R11 | 개인 Windows WSL2/Docker 운영 | 실제 Windows PC에서 설치·시작·재시작·백업/복구를 검증한다. iPad/Mac은 사설망 또는 Tailscale/HTTPS로 접속한다. |
| R12 | 교체 가능한 LLM | 서버만 API 자격증명을 보유한다. OpenAI-compatible adapter를 우선 사용하고 provider/model 선택을 교체할 수 있다. UI/응답/로그는 비밀값을 노출하지 않는다. |
| R13 | 보호·준비 상태·오류 | pairing bearer, Origin 검사, 업로드 용량/형식 검사, 경로 차단, 삭제/설정 보호, request ID를 갖춘 오류를 제공한다. 읽기 가능과 Tutor 준비 완료를 구별한다. |
| R14 | 병렬 작업 가능한 공통 시작점 | upstream commit/license/build/API가 확인되고 모든 제품 파일의 소유자가 하나다. 공통 등록 함수와 facade, 동일 계약 digest, fixture 검사, 실제 adapter 검증을 갖춘 기준 commit에서 여섯 작업이 출발한다. |

## 선택 범위

lasso, 부분 지우개, 도형 보정, 필기 OCR/Vision 확장. 지원하지 않는 기능은 UI에서 숨기거나 지원 여부를 표시한다. 필수 지우개는 전체 획 삭제로 충족할 수 있다. 가입·SaaS·결제·다중 사용자·협업·Rust 재작성은 범위 밖이다.

## 이번 준비의 완료 조건

여덟 지정 산출물, 같은 버전의 검증 가능한 계약/fixture, 실제 upstream 감사, 실제 파일 경로에 연결된 단독 소유표, 최소 adapter/등록 지점, 실행된 검사, 시작 SHA가 필요하다. 지정 upstream을 고정했고 최소 source adapter와 common fixture를 검사했다. 준비 gate는 제품 기능 완료나 Cloud remote 게시를 의미하지 않는다. 제품 기능 구현을 넓게 시작하지 않는다.
