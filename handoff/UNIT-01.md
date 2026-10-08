# UNIT-01 인수 경계

현재 제품 소유 경로: 없음 (source audit 대기). 현재 준비 문서 소유: 이 파일만.

담당: 과목/문서 Library, 원본·파싱·그림·임베딩 저장, ingest/index 재사용 연결, 문서 검색/인용 검증, 주석/필기 snapshot/change/mutation, DB/migration 전체. `register_library` 후보와 port는 INTEGRATION 참조.

제공: DocumentRepository, DocumentSearch, CitationVerifier, AnnotationSync와 DB UoW. UNIT-02에 page mapping과 검증된 citation만 제공한다. cursor와 revision은 DB transaction에서 발급한다. 파일 path 대신 server key를 쓴다. 원본을 수정하지 않는다.

UNIT-02가 요청할 DB 명세: turn/event log+idempotency receipt, quiz/question/attempt, activity/mastery/memory/progress 상태, learning revision. 실제 table/ORM 이름은 upstream 확인 후 결정한다. 기존 DB 관례를 유지한다.

인수: 공통 fixture의 quote/hash/page/rect 거부, 주석 충돌/멱등/tombstone/cursor 복구를 **실제 repository**로 재검사한다. SQLite 등 임의 DB를 준비 단계에서 도입하지 않는다.
