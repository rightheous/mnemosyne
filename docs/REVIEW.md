# 검토용 변경 설명

## 문제와 결과

여섯 제품 작업이 공유할 문서/version/좌표/주석 동기화/Tutor/학습 상태 계약과 수정 범위가 없었다. 빈 저장소에 요구사항, source audit 기록, UI 방향, 단독 소유 경로, 후보 schema/API, 일관된 bilingual PDF/학습 fixture, Python/Node/Swift 소비 검사를 추가한다.

정확한 Pumice/DeepTutor 소스와 remote가 없어 실제 경로/라이선스/API/transport를 확인할 수 없다. `0.1.0-draft.1`을 확정 구현 계약으로 주장하지 않고, source gate가 여섯 제품 작업 시작을 차단한다. 신규 제품 구현/프레임워크/DB/Docker 구성을 임의로 도입하지 않는다.

## 검증

실행 결과는 `docs/VALIDATION.md`를 참조한다. OpenAPI/JSON Schema/주석 state machine/인용·geometry·이벤트 불변식, Node incremental SSE 소비, Swift Codable 모델/geometry, PDF 2-page extraction/rendering을 확인한다. 실제 upstream/기기/WSL2 통합은 미검증이다.

## 검토 시 확인할 점

소스 URL/ref가 제공되면 감사와 실제 ownership/registration 연결을 먼저 완료해야 한다. SSE는 단일 외부 transport의 후보이며 실제 upstream 확인 전 확정하지 않는다. remote가 없어 이 문서는 저장된 초안 PR 본문이다. GitHub PR은 아직 생성되지 않았다.
