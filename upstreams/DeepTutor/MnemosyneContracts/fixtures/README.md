# 일관된 공통 학습 fixture

bilingual-geometry.pdf 하나와 study-session.json과 quiz-generation-request.json이다. 원문은 이 fixture용으로 작성했고 모든 ID는 합성 UUID다. 원본 사용자 문서·키·개인 경로를 넣지 않았다.

PDF는 영어/한글 두 물리 페이지, MediaBox 600×800, 다른 CropBox, 두 번째 /Rotate 90, label 1/ii를 갖는다. PNG 두 페이지를 렌더링해 읽을 수 있음을 확인했다. 원본 바이트 SHA는 JSON version과 일치한다.

page.text와 segments는 **실제 DeepTutor extract_material + PyMuPDF 1.28.2**로 만들었다. 전체 text block geometry를 canonical raw PDF 좌표로 변환했다. 수동 사각형은 제거했다. 부분 선택/quad/OCR·다른 parser는 제품 UNIT-01이 확장하고 검사해야 한다. fixture가 해당 기능까지 검증하는 것은 아니다.

JSON 하나가 과목/원본/페이지/검증 인용/Reader context/하이라이트·노트·북마크·ink/10단계 두 기기 sync/튜터/퀴즈·시도/학습 상태를 연결한다. native wire는 같은 파일의 wire.events/cancelled_events/error_events와 wire.commands다. metadata.mnemosyne에 semantic event를 넣으며 확장 없는 native progress가 하나 있어 semantic seq의 빈 번호를 검출한다. cancel/error는 native done.status에 대응한다. 별도 SSE fixture/서버는 없다.

sync reference는 재전송/동시 수정·삭제/tombstone 복구/ID payload 불일치를 검사한다. fixture:* cursor는 검사 전용이다. 실제 durable transaction·retention/cursor expiry·두 실제 기기 동기화는 제품 통합 검사로 남는다. 0/90/180/270·user_unit·offset/scale geometry와 Unicode scalar emoji probe도 포함한다. quiz-generation-request.json은 문서 version의 특정 페이지에서 생성 요청을 만드는 입력 fixture다.

progress-mutation.json은 클라이언트 mutation ID, 읽은 물리 페이지, 측정한 초, learning revision을 묶는다. 서버는 재전송된 같은 mutation을 한 번만 더하고 실제 파싱된 문서 페이지인지 확인한다.

Python contract 검사, 실제 ReadingStore/native protocol adapter, 웹 source-owned TS consumer, iPad Swift Codable와 실제 신규 geometry가 동일 JSON을 소비한다. 제품 UI/Pencil/Windows 인수를 대신하지 않는다.
