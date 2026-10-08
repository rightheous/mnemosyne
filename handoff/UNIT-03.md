# UNIT-03 인수 경계

현재 제품 소유 경로: 없음 (Pumice audit 대기). 현재 준비 문서 소유: 이 파일만.

담당: 기존 PDF Reader 재사용, 선택/검색/목차/읽기 위치, Pencil pen/highlighter/whole-stroke eraser/undo/redo, canonical geometry, 다운로드된 원본 검증, ReaderFacade, local storage/outbox 원자성. UI network·app entry·Xcode 설정은 UNIT-04.

입력 저장은 network 호출 없이 local transaction. 필기 편집과 outbox를 같이 기록하고 앱 재시작에 보존한다. worker는 facade의 pending/apply 메서드를 사용한다. 영구 주석 제안 승인과 event ID도 저장한다. 실패 시 pending 초안을 버리지 않는다.

인수: 실제 iPad Pencil, 비행기 모드/재시작, 회전과 CropBox/줌, redo/outbox/삭제 복구, 원본 hash 불변과 annotated export. 공통 Swift 소비 검사는 기하 규칙의 증거이며 PDFKit/Pumice 통합 증거가 아니다.
