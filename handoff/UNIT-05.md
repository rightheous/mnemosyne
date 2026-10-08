# UNIT-05 인수 경계

현재 제품 소유 경로: 없음 (web upstream audit 대기). 현재 준비 소유: 이 문서와 `checks/web-consumer.mjs`.

담당: Mac 웹 전체, 과목/Library/upload/delete/PDF/highlight/note, iPad ink **표시**, Tutor/Quiz/Mastery/Memory/Progress/Review, model/server settings, web manifest/lockfile. 기존 web framework와 PDF viewer를 재사용한다.

공통 fixture는 exact hash/version, 0-based page, Unicode scalar quote, geometry, event sequence로 소비한다. SSE candidate의 bearer fetch와 last-event ID를 지원하는 consumer가 필요하다. 원본 파일 경로/LLM secret을 다루지 않는다. 삭제와 설정에는 최신 revision+명시 확인을 사용한다.

인수: 실제 브라우저에서 PDF overlay/citation 이동, 한글/영문 인용, stream resume, attempt/학습 기록 저장, ink 편집 제어 없음, accessibility/키보드. Node fixture 검사는 브라우저 rendering/API 검증을 대신하지 않는다.
