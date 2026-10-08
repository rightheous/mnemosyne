# 공통 소규모 학습 fixture

`study-session.json` 하나가 과목/문서/물리 페이지/검증 인용/Reader context/네 종류 주석/두 기기의 수정·삭제/튜터/퀴즈·시도/학습 상태를 연결한다. 모든 ID는 합성 UUID이며 개인 문서/자격증명을 포함하지 않는다. 원문 문장은 이 fixture를 위해 작성했다. 실제 upstream 출력이라는 주장은 아니다.

- `bilingual-geometry.pdf`: 영문 한 페이지와 한글 한 페이지. 각 페이지 MediaBox 600×800, 서로 다른 CropBox; 둘째 페이지 /Rotate 90. 원본 바이트 hash와 parser text는 JSON에 대응한다. `/Rotate`와 content 방향이 함께 있어 실제 표시 문장은 수평으로 읽힌다. 두 페이지를 렌더링해 가독성을 확인했다.
- `study-session.json`: PDF 원본 hash, pypdf로 확인한 텍스트, 수동 fixture segment 범위. **실제 Pumice/DeepTutor parsing이 만든 geometry가 아니다.** 실제 parser adapter가 부분 선택 rect도 검증해야 한다. `display_label=1/ii`는 fixture PDF의 PageLabels tree와 일치하며 물리 페이지 번호 `1/2`와 구별한다.
- `tutor.sse`: 같은 JSON events의 wire 표현. keepalive comment, 여러 data line, 종료 event를 포함한다. SSE 후보 parser를 검사하며 실제 server transport 선택을 확정하지 않는다.

10 sync step은 수정/재전송/동시 수정/동시 삭제/삭제 후 수정/같은 ID 복구 거부/새 ID 복구/오래된 재전송/ID payload 충돌을 확인한다. opaque cursor의 `fixture:*` 값은 검사 전용이며 제품 cursor codec이 아니다. retention/expiry와 durable transaction은 제품 통합에서 추가 검사한다.

geometry case 네 개는 0/90/180/270, CropBox offset, physical user unit, viewport offset/scale의 forward/inverse 값이다. `unicode_probe`의 emoji는 JS UTF-16과 Unicode scalar의 차이를 검출한다. PDF에 지원되지 않는 emoji glyph를 넣어 렌더링을 손상시키지 않는다.

backend Python 검사, 웹 Node 소비 검사, iPad Swift Codable 소비 검사는 같은 `study-session.json`을 직접 읽는다. 제품 runtime/model adapter 검사나 iPad device test는 별도이며 소스 연결 전에는 실행할 수 없다.
