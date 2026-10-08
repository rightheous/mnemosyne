# 검증 기록

2026-10-08 (Asia/Seoul). macOS의 Python 3.14.7 / Node 20.20.2 / Swift 6.3.3에서 실행했다. fixture 검사와 실제 upstream/제품 검증을 분리한다.

| 실행 | 결과 | 입증 범위 |
|---|---|---|
| `python checks/validate_contracts.py` (임시 venv) | PASS, exit 0 | OpenAPI 3.1의 32 operation, JSON/YAML 동일 파싱, draft-2020-12 schema 3개, schema 검증 80회, 잘못된 입력 거부 19건, sync 10단계, geometry 4종, manifest digest와 정확한 단독 소유 경로 |
| `node checks/web-consumer.mjs` | PASS, exit 0 | 같은 fixture, Unicode scalar/emoji, hash, 회전·inverse·rect, 이벤트 11개, 7-byte chunk로 끊은 UTF-8 SSE의 LF/CRLF 두 표현, reconnect dedup, 퀴즈/상태 연결 |
| `swift -module-cache-path /tmp/mnemosyne-swift-cache checks/ipad-consumer.swift` | PASS, exit 0 | 실제 컴파일/실행한 Codable 소비, geometry 4종, main event 11개와 cancel/error stream, 한글 quote, 주석 네 종류, pen physical width, resume와 attempt 연결 |
| `python checks/validate_contracts.py --require-ready` | 예상한 FAIL, exit 1 | `SOURCE GATE: Pumice/DeepTutor sources and real paths are pending`로 제품 작업 시작을 거부한다. 계약 fixture PASS와 source readiness 실패를 따로 출력한다. |
| bundled pypdf extraction/metadata 비교 | PASS | 원본 SHA-256, 두 페이지의 텍스트, MediaBox/CropBox, /Rotate 0/90, PageLabels `1/ii`와 JSON 대응 |
| Poppler로 최신 PDF 두 페이지 PNG 렌더 + 육안 확인 | PASS | 영문/한글 문장·수식의 가독성, crop/회전 출력. 중간 PNG는 임시 디렉터리에 보관하고 배포하지 않음. |
| `git diff --cached --check` | PASS | 커밋 대상의 whitespace 오류 없음 |

80회는 반복/부정 검사에서 성공한 prefix를 포함한 검증 호출 수이며, 80개의 서로 다른 fixture라는 뜻은 아니다. SyncReference는 검사 파일 안의 작은 명세 state machine이며 실제 DB/동기화 서비스가 아니다. Node/Swift는 계약 소비 예제이며 제품 client 코드 생성 또는 실제 renderer 검증이 아니다.

부정 검사는 quote/version/page/parser/text hash/scalar range/rect, 잘못된 회전, kind/payload, mutation 대상 ID, event gap/terminal/Reader geometry, tombstone payload, 설정 output 비밀값, DTO의 OS 경로, 임시 강조의 영구화, 알 수 없는 Reader command를 거부한다. fixture는 수정/재전송/동시 수정·삭제/삭제 후 늦은 수정/같은 ID 복구 금지/새 ID 복구/오래된 receipt/다른 payload 재사용을 검증한다.

## 미검증과 남은 작업

Pumice/DeepTutor URL·SHA·라이선스·기존 AGENTS·build·test·API·streaming·DB 구조를 확인하지 못했다. 따라서 실제 제품 파일 소유권, 기존 transport adapter, 공통 assembly 등록, 실제 client model generator와 여섯 Cloud 작업의 공통 시작 SHA는 미확정이다.

실제 PDFKit/PDF.js 인용/부분 선택/필기 overlay, 실제 iPad Pencil·오프라인·durable local transaction, 진짜 두 기기 sync/cursor expiry/retention, DB atomicity, 실제 LLM 및 각 capability, Windows WSL2/Docker·Tailscale/HTTPS·backup/restore·브라우저 UI는 미검증이다. source gate는 이 상태를 성공으로 표기하지 않는다.

임시 검사 의존성은 제품 backend에 설치하지 않았고 `checks/requirements.txt`만 별도로 기록했다. 최초 PDF 렌더는 fontconfig cache 경로 문제로 중단했고, 쓰기 가능한 임시 cache 설정 후 최신 PDF를 재렌더·검사했다. Git remote가 없어 push/GitHub draft PR은 실행하지 않았으며 저장된 PR 본문은 `docs/REVIEW.md`다. 커밋은 기본 브랜치가 아닌 `codex/mnemosyne-bootstrap`에 명시된 `Codex Bootstrap <codex-bootstrap@localhost>` identity로 기록한다.
