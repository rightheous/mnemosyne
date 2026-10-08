# Mnemosyne · 므네모시네

개인 문서 중심 학습 시스템의 **공통 소스 기반 시작점**이다. 사용자가 지정한 Pumice(iPad)와 DeepTutor(서버·웹)의 원래 tracked source를 pinned snapshot으로 보존했다. 제품 구현을 넓게 시작하지 않고 여섯 유닛을 위한 소유권·계약·등록 seam·검사를 준비했다.

먼저 docs/REQUIREMENTS.md, UPSTREAM-AUDIT.md, OWNERSHIP.md, INTEGRATION.md와 integration/registry.json을 읽는다. 정확한 파일별 소유권은 integration/ownership.json, 원래 소스 provenance는 integration/upstreams.json이다.

- upstreams/Pumice/: Swift 6 · SwiftUI/UIKit/PDFKit · iPadOS 18+, MIT.
- upstreams/DeepTutor/: Python/FastAPI · 기존 학습 runtime · Next/React 웹, Apache-2.0 및 third-party notices.
- contracts/: 계약 0.1.0, 실제 parser 기반 영문/한글 PDF fixture와 native WebSocket 2.0 확장. 두 source의 MnemosyneContracts/에 동일 bundle 제공.
- handoff/: 여섯 작업의 실제 경로·호출 경계·필수 인수 조건.
- checks/: schema/fixture/소유권/source gate, 실제 backend/웹/Swift adapter 검사.

기준 tag는 mnemosyne-bootstrap-v0.1.0. 로컬 Git branch는 codex/mnemosyne-bootstrap이다. 아직 GitHub remote가 없어 Cloud 게시/PR 생성은 완료되지 않았다. 제품 준비 상태는 false이며 필수 학습·오프라인·불변 원본·개인 서버 보호를 각 유닛이 이번 범위에서 완성한다. 실행 결과와 기기/Windows 미검증 항목은 docs/VALIDATION.md를 본다.
