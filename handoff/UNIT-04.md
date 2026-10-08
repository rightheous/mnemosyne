# UNIT-04 인수 경계

현재 제품 소유 경로: 없음 (Pumice audit 대기). 현재 준비 문서 소유: 이 파일만.

담당: iPad 한국어 앱 화면/과목/Library/Tutor/학습 화면, API client/pairing, network/sync worker, 앱 진입점, Xcode project/settings. Reader 내부와 local DB는 UNIT-03 facade로만 호출한다.

가로 PDF 옆 Tutor, 세로 sheet. 오프라인 읽기/필기 저장 상태와 network Tutor 상태를 구별한다. actor/직렬 실행 모델은 실제 upstream에 맞춘다. mutation/receipt 순서와 backoff, SSE candidate event dedup/gap/resume, 임시 효과와 영구 제안 승인을 소비한다. URL에 token을 넣지 않는다.

인수: library download/pairing, two-device synchronization, 과목과 학습 화면, 앱 재시작 뒤 outbox/stream 복구, 모든 required event를 facade/화면에 연결. project file과 Reader 파일을 함께 수정하지 않는다.
