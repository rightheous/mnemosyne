# Mnemosyne 작업 지침

- 먼저 `docs/REQUIREMENTS.md`, `docs/UPSTREAM-AUDIT.md`, `docs/OWNERSHIP.md`, `docs/INTEGRATION.md`를 읽는다. 현재 준비 상태는 `integration/registry.json`을 확인한다.
- 이 프로젝트는 개인용이다. iPad는 지정된 Pumice, 서버는 지정된 DeepTutor를 재사용한다. 정확한 소스가 없으면 URL/경로를 요청하고 미확인으로 보고한다. 동명 저장소, 클래스, API, 라이선스를 추정하지 않는다.
- 지정 소스는 upstreams/Pumice와 upstreams/DeepTutor에 원래 레이아웃으로 고정했다. integration/upstreams.json의 SHA/라이선스/수정 예외를 따른다. 공통 준비 gate와 제품 구현 완료를 구별하고 planned HTTP/facade를 완료된 기능으로 보고하지 않는다. Cloud 게시 여부도 별도로 보고한다.
- 담당 유닛은 소유 경로만 수정한다. 공유 서버 조립, 계약, 루트 지침은 통합 담당만 수정한다. DB/migration은 UNIT-01, backend 의존성 파일은 UNIT-06, 웹 의존성 파일은 UNIT-05, Xcode 설정은 UNIT-04 담당이다. 다른 담당에게는 명세를 전달한다.
- 계약 변경은 통합 담당에게 소비자 영향·버전·fixture·검증 변경을 포함해 제안한다. 유닛별 계약 복사본을 임의로 수정하지 않는다. 등록 함수와 facade를 통해 연결하고 공통 시작 파일을 함께 편집하지 않는다.
- 필수 학습 기능, 오프라인 읽기·필기, 원본 불변, 한국어 기본, 인용 검증은 이번 범위다. 선택 기능과 혼동해 후속 단계로 미루지 않는다. 제품화·가입·결제·협업·Rust 재작성은 추가하지 않는다.
- 실제 실행한 검사와 미검증 항목을 나눠 보고한다. fixture 검사, 제품 빌드, 기기 검증을 구별한다. 실패·차단·출처·commit SHA를 숨기지 않는다. 자격증명·원본 사용자 문서·개인 경로를 fixture나 로그에 넣지 않는다.
- 기본 브랜치에 직접 통합하지 않는다. `codex/` 작업 브랜치에서 검토 가능한 커밋을 만든다. PR을 만들면 이 채팅에 첨부한다. 사용자 요청 없이 다른 채팅에 작업 지시를 보내지 않는다.

- 정확한 파일 소유권은 integration/ownership.json이다. 서버 main/container/bootstrap/공유 ports는 통합 담당만 수정한다. 각 snapshot의 MnemosyneContracts는 루트 계약의 생성 복사본이며 직접 수정하지 않는다.
- Pumice의 iPadOS-only/Catalyst NO, 로컬 서명값 제외를 유지한다. 원래 LICENSE/NOTICE와 upstream 지침을 보존하고 커밋 메시지는 Conventional Commits를 사용한다.
