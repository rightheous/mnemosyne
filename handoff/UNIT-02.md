# UNIT-02 인수 경계

현재 제품 소유 경로: 없음 (source audit 대기). 현재 준비 문서 소유: 이 파일만.

담당: Tutor runtime/API, 한국어 prompt, 기존 capability 등록/경량화, Chat/Reading/Quiz/Assessment/Mastery/Deep Solve/Memory/Progress/Review 전체, LearningStateStore 서비스. `register_tutor` 후보와 DTO는 INTEGRATION/계약 참조.

DocumentSearch/CitationVerifier는 UNIT-01 제공. 검증되지 않은 LLM quote를 Reader event로 발행하지 않는다. response_language default ko, content_language 별도, 원문 quote/math/code 보존. 실제 upstream transport를 확인한 후 통합 담당의 단일 외부 transport에 adapter를 제공한다.

UNIT-01에 전달할 persistence 요구: UUID turn/quiz/question/attempt/activity/memory ID, 문서/version 참조, immutable ordered event log 및 terminal, mutation hash/receipt, learning revision optimistic concurrency, 제출/평가/파생 mastery-memory-progress 원자성, provider secret과 공개 metadata 분리. 공통 migration과 DB manifest를 직접 수정하지 않는다.

인수: 모든 필수 capability 등록, quote verification, replay/cancel/error/terminal race, 시도 멱등성과 학습 상태 복구를 실제 runtime/service로 검증한다. 준비 fixture 성공만으로 capability 구현 완료를 보고하지 않는다.
