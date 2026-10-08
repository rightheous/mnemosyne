# 계약 묶음

버전 `0.1.0-draft.1`, 상태 `draft-awaiting-upstream`. 모든 문서/API/event/fixture는 이 버전을 사용한다. `manifest.json`의 SHA-256은 묶음의 정확한 바이트를 고정한다. HTTP header `X-Mnemosyne-Contract-Version`으로 peer 버전을 확인하고 불일치 시 `contract_mismatch`로 거부한다. 버전 호환성이 확정되기 전 임의 fallback은 없다.

`openapi.yaml`은 **JSON으로 직렬화된 OpenAPI 3.1.0**이다. JSON은 YAML의 부분집합이므로 YAML/OpenAPI 도구가 읽을 수 있으며 별도 YAML runtime이 없어도 웹의 JSON parser와 Python stdlib가 같은 파일을 읽는다. JSON Schema는 draft 2020-12이며 외부 `$ref`는 이 묶음 안의 상대 경로만 사용한다. `models.schema.json`에 공통 DTO, `annotations.schema.json`에 주석/mutation, `events.schema.json`에 typed event가 있다. codegen 도구의 3.1 지원은 실제 upstream manifest를 본 후 검증한다.

**이 계약은 기존 구현이 없는 환경에서 작성한 후보다.** 외부 transport는 SSE 한 가지를 후보로 검증하지만 확정 선택은 아니며 registry의 `external_transport`는 null이다. DeepTutor의 실제 transport를 조사한 뒤 하나만 확정한다. 지금 SSE나 WebSocket 제품 서버를 만들지 않는다.

## 문서와 인용

- `document_id`는 UUID, `version_id`는 `sha256:<원본 64자리 소문자 hex>`. ID와 hash는 다른 용도다. 같은 문서의 새 원본은 별도 version이다. 기존 주석은 원래 version에 묶이고 자동 이동하지 않는다.
- 물리 `page_index`는 **0 기반**. API/saved geometry 모두 같은 기준이다. `display_page_number=page_index+1`, `display_label`은 PDF page label이 있으면 그 label, 없으면 숫자 문자열. 파싱 page도 정확히 원본 물리 page에 대응한다. 텍스트 없는 페이지는 비어 있는 page로 남긴다.
- `parse_revision`은 parser 결과의 immutable revision이다. anchor는 document/version/page/parse_revision/text_sha256을 포함한다. 새 parser 출력은 새 revision이며 이전 인용의 anchor를 바꾸지 않는다.
- `page.text`는 parser가 만든 NFC+LF 문자열이다. `start_scalar` 포함, `end_scalar` 제외의 **Unicode scalar** offset이다. Python codepoint, JS `Array.from`, Swift `unicodeScalars`로 읽는다. byte/UTF-16/grapheme offset을 섞지 않는다. quote는 이 구간과 정확히 같아야 한다. hash는 이 UTF-8 문자열의 SHA-256이다. 원문 수식/코드 표시는 별도 원문을 보존하고 parser 정규화는 재작성/번역을 하지 않는다.
- 클라이언트의 anchor/citation은 신뢰하지 않는다. UNIT-01 `verify_citation`이 문서 접근, version, page, parse_revision, text hash, quote offset, page 영역과 parser segment의 rect 대응을 검사한다. 검증된 `verification_id`가 있어도 요청 때 서버 저장 기록과 대조한다. JSON Schema 통과가 인용의 의미 검증을 대신하지 않는다.

## PDF geometry

좌표는 원본 페이지의 **회전 전 default user space**, 원점은 원본 좌표계, x 오른쪽/y 위쪽이다. MediaBox/CropBox는 `[llx,lly,urx,ury]`. x/y를 CropBox 원점으로 미리 옮겨 저장하지 않는다. `user_unit`을 보존하고, `rotation_degrees`는 0/90/180/270의 시계 방향이다. 굵기는 PDF physical point(1/72 inch)이며 content 좌표 굵기는 `width_pt/user_unit`이다. 사각형은 `[x,y,width,height]`, 너비/높이 양수. 텍스트 quad가 필요한 향후 확장은 계약 변경으로 추가한다. crop 밖 stroke는 저장 전 clipping/분할하고 최소 범위를 벗어난 입력은 거부한다.

CropBox의 폭/높이를 `W,H`, 점을 `u=x-llx,v=y-lly`라 할 때, 회전된 crop의 **좌상단 기준** 좌표는 다음이다.

| /Rotate | X,Y | 표시 폭,높이 |
|---|---|---|
| 0 | `u, H-v` | `W,H` |
| 90 | `v, u` | `H,W` |
| 180 | `W-u, v` | `W,H` |
| 270 | `H-v, W-u` | `H,W` |

viewport는 `(offset_x + X*user_unit*scale, offset_y + Y*user_unit*scale)`. `scale`은 physical PDF point당 CSS px 또는 UIKit point이며 devicePixelRatio는 canvas backing에만 추가한다. rect는 네 꼭짓점을 변환한 bounds를 사용한다. invert transform으로 터치/Pencil 점을 저장 좌표로 되돌린다. PDFKit/PDF.js가 제공하는 page conversion이 회전을 이미 적용했다면 다시 적용하지 말고 이 canonical 공간과 대조한다. 특정 upstream 라이브러리 동작은 아직 미확인이다.

fixture의 page 0은 rotation 0/CropBox `[20,30,580,760]`, page 1은 rotation 90/CropBox `[10,20,590,770]`, `user_unit=1`. 나머지 180/270 및 `user_unit=2`, 다른 offset/scale도 geometry 검사에 포함한다. 실제 제품은 PDF.js/PDFKit 화면에서 같은 점을 비교해야 한다.

## 주석과 동기화

`annotation_id` UUID, `document_id`/`version_id`, `page_index`, `kind`, payload를 저장한다. 서버는 document-version 단위 mutation log의 증가 revision을 부여한다. `server_revision`은 해당 주석의 마지막 변경 log revision이고, `base_revision`은 클라이언트가 편집한 주석 revision이다. 새 ID는 base 0. 클라이언트 timestamp는 정보일 뿐 충돌 우선순위가 아니다.

`client_mutation_id`는 계정 전체에서 UUID로 유일해야 한다. 첫 payload의 canonical JSON hash와 응답을 저장한다. 같은 ID/같은 payload 재전송은 **원래 응답**이며 log를 늘리지 않는다. 같은 ID/다른 payload는 `idempotency_mismatch` 409. mutation 묶음은 **순서대로 독립 적용**하며 결과별 applied/conflict/rejected를 반환한다. 전체 batch 원자성을 가정하지 않는다. UUID 저장/검사와 update/log append는 한 DB transaction이다.

payload 동등성은 JSON object key 순서를 무시하고 배열 순서·문자열을 그대로 비교하며, 유한 JSON number는 수학적으로 같은 값(예: 1/1.0)으로 비교한다. 제품 hash 구현은 이 동등성을 보존해야 한다. 검사 전용 state machine은 구조 동등성으로 비교한다. MutationResult의 `server_revision`은 응답 시 log watermark이며, `current.server_revision`은 해당 주석의 마지막 revision이다. 클라이언트는 후자를 다음 base로 사용한다. 재전송은 원래 응답의 watermark를 그대로 돌려준다.

JSON integer는 웹의 안전한 정수 범위 상한 `9007199254740991`을 넘지 않는다. NaN/Infinity는 JSON이 아니므로 허용하지 않는다. revision이 상한에 도달하기 전에 버전 변경이 필요하다. cursor와 원본 hash는 숫자로 변환하지 않는다.

stale base는 409 의미의 `conflict` 결과를 내고 현재 annotation/tombstone을 돌려준다. 편집/편집, 편집/삭제, 삭제/편집 모두 같다. 기기 시간으로 덮어쓰지 않는다. UI가 로컬 초안을 유지하고 사용자 선택을 받는다. 살아 있는 주석은 새 mutation ID와 최신 base로 다시 적용할 수 있다. tombstone은 같은 annotation ID로 복구하지 않는다. 삭제 취소/사용자 복구는 **새 ID** 생성이다. tombstone payload는 null, ID/version/page/kind/revision/삭제 시각은 보존한다.

cursor는 서버가 발급하는 opaque string이며 document+version 범위와 expiry를 검증한다. 초기 snapshot은 transactionally consistent revision과 next cursor를 함께 반환한다. 이후 change feed는 그 시점 다음 log부터 읽어 pagination한다. local DB에서 페이지의 changes+cursor를 함께 commit한 뒤 다음 요청을 한다. cursor 만료는 410 `cursor_expired`: 새 snapshot과 미확인 outbox를 함께 대조하며 보류 중 초안을 버리지 않는다. 삭제 문서는 410 `document_deleted`이고 남은 로컬 필기는 복구/내보내기 대상으로 보존한다. 서버 tombstone/멱등 기록을 기본적으로 영구 보존한다. retention을 도입하면 계약/기기 상태를 함께 바꾼다.

Reader 내부(UNIT-03)가 입력 상태+outbox를 로컬 transaction으로 저장한 뒤 성공을 알린다. UNIT-04 worker는 facade에서 순서를 받아 전송하고 결과+cursor를 facade로 원자 적용한다. worker는 Reader DB 파일을 직접 쓰지 않는다. transient network/429/503은 Retry-After 또는 capped exponential backoff+jitter(예: 1~60초), 401은 token 복구, schema/권한 오류는 사용자 조치, conflict는 사용자 해결로 분리한다. inflight는 앱 재시작 때 같은 ID로 재시도한다. 손필기는 Mac에서 조회만 한다.

## Tutor 이벤트

후보 transport: `POST /v1/tutor/turns`로 turn을 만들고 authenticated `GET /v1/tutor/turns/{turn_id}/events`로 SSE 수신. bearer header를 붙이는 fetch/URLSession consumer를 사용하며 URL query에 token을 넣지 않는다. `Last-Event-ID`로 resume, 최초는 생략. keepalive SSE comment는 event log에 넣지 않는다. 각 data는 `events.schema.json`의 envelope, SSE `id`는 JSON `event_id`와 같고 `event`는 JSON type과 같다.

`event_id=<turn UUID>:<seq>`; seq는 1부터 연속 증가하며 서버가 로그를 저장한 뒤 발행한다. 클라이언트는 turn별 durable last seq로 중복을 무시하고 gap이면 재연결한다. reconnect는 같은 event ID/내용을 되돌린다. retention은 준비 응답의 `event_resume_seconds`(초안 86400) 이상, 유효하지 않거나 만료된 resume은 stream 시작 전 410. 서버 종료 후 진행 turn도 persisted terminal/snapshot에서 복구할 수 있어야 한다.

`turn.started` 다음 delta/근거/Reader/퀴즈 이벤트, 마지막은 `turn.done`, `turn.error`, `turn.cancelled` 중 **정확히 하나**다. terminal 이후 발행하지 않는다. cancel HTTP와 이미 완료의 race는 저장된 terminal을 반환한다. stream 중 오류는 typed terminal `turn.error`; HTTP 시작 전 오류는 공통 ErrorEnvelope. disconnect 자체는 cancel이 아니다. `quiz.show`와 `question.show`는 저장된 quiz/question ID를 가리킨다.

Reader context는 문서 version, page, 읽기 위치, 선택 anchor, response_language를 포함한다. `reader.goto`는 위치 이동, `reader.highlight`/`reader.flash`는 TTL 있는 **일시 효과**다. `reader.annotate`는 확인이 필요한 영구 주석 **제안**이며 즉시 저장하지 않는다. 사용자가 승인하면 event의 안정된 `suggested_mutation_id`로 outbox에 한 번 기록한다. replay로 주석이 중복 생성되지 않는다. 승인된 event ID를 로컬에 저장한다. 문서/version이 현재 Reader와 다르면 명시 전환 후 적용하고 틀린 페이지에 적용하지 않는다.

## 학습 상태

Quiz는 질문 ID, 문제/보기/채점 가능한 공개 정보와 검증된 근거를 포함한다. 정답·비공개 rubric은 제출 전 클라이언트에 노출하지 않는다. attempt ID와 client mutation ID로 제출을 멱등 처리한다. 서버가 평가 결과와 mastery/memory/progress 변화를 transactionally 저장하고 새 `learning_revision`을 반환한다. 학습 저장소 인터페이스는 UNIT-02, 실제 DB/migration은 UNIT-01. memory review 제출도 동일한 ID/base revision 규칙을 사용한다. Deep Solve trace와 Reading/Chat 기록을 learning activity에 저장한다.

`content_language`는 문서의 BCP47/`und` 문자열, `response_language`는 요청별 BCP47 문자열(default `ko`)이다. tutor 답변 본문과 UI label은 한국어가 기본이며 `quote`, math, code는 원문 그대로다. 상태 fixture는 quiz/attempt/mastery/memory/progress/reading/solve를 한 문서와 연결한다.

## 보호와 준비 상태

사설망도 pairing bearer가 필요하다. 개인 서버 console의 일회용 code로 기기를 pair하며 rate limit/expiry/회전·폐기 기능을 둔다. auth code/token/LLM 비밀값은 log/URL에 남기지 않는다. CORS는 설정된 정확한 Origin만 허용한다. 웹 secret은 가능하면 메모리에 두며 XSS 보호를 적용한다. Tailscale은 네트워크 연결, pairing은 앱 권한으로 구별한다. 공용 노출시 HTTPS 필수, 원격 private망도 HTTPS를 기본으로 한다.

업로드는 PDF magic+실제 parser 검사, 제한 용량/페이지/parse 시간, server generated key, symlink/경로 traversal 방지, data root 밖 쓰기 금지. API는 원본 OS 파일 경로를 받지 않는다. 파일 download는 document ID+version을 검증한다. 삭제는 bearer+If-Match 문서 revision+`X-Confirm-Action: document.delete:<document_id>`를 요구하고 명시 UI 확인을 거친다. 설정 변경도 bearer+If-Match 설정 revision+`X-Confirm-Action: settings.update`가 필요하다. 설정 반환은 masked metadata만. provider base URL은 서버 측 allowlist/명시 설정을 사용하고 metadata/private 임의 URL SSRF를 차단한다. 서버 PC의 지정 loopback provider는 서버 console에서 허용한다.

health는 최소 process 상태, readiness는 DB/storage/parser/index/provider capabilities의 준비 상태를 반환한다. raw 예외/파일 경로/키는 노출하지 않는다. ErrorEnvelope는 code/message_ko/request_id/retryable를 포함한다. `pending/running/ready/failed` parse/index 상태를 구별하고 PDF 다운로드 가능 여부를 별도로 표시한다.
