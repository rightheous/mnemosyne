# 통합 draft PR 본문

## 요약

`origin/main` (`16130d21410d1b2349ffee0757d44462c899ebbf`)과 준비 커밋
`5715a32927e3a73dc28782d306880e3dd1f62441`에서 만든
`codex/mnemosyne-integration` 브랜치에 확인 가능한 UNIT-01/04/05/06 변경을
통합하고, pairing/session 인증과 보호된 Library router를 실제 서버 수명 주기에
연결했습니다. 계약 0.1.0의 DTO는 바꾸지 않았고 두 upstream 계약 사본의 digest를
갱신했습니다.

## 적용한 정확한 unit refs

- UNIT-01: `c1f1f16b1cf12c9e66da1b3f24755cdb1412550f`, PR #2
- UNIT-04: `ced01afba5138598601c3b25933329d23a41282b`, PR #3
- UNIT-05: `e22a0e9d421adf3020e5359dcbda541e5ba378e0`, branch `codex/unit-05-api-refresh`, Draft PR #4
- UNIT-06: `e14c599cb9977a41f5f17358a9ca17f33bce2327`, PR #1

요청에 처음 포함된 값은 저장소 URL뿐이었으나 이후 UNIT-05 정확한 ref가 제공돼
통합했습니다. 저장소의 정확한 unit ref로 확인된 결과를 적용했습니다. UNIT-03 결과와 UNIT-04 handoff가 참조한
`3a98ac43474722c98eded510ec6428f8329cd3d2`는 원격 ref/object에서 찾지 못했습니다.
UNIT-02의 별도 ref는 제공되지 않았고 기준 `main`에 이미 코드가 있음을 확인했습니다.
UNIT-05는 위의 exact commit으로 통합했습니다.

## 검증

- 계약/source/ownership 검사, 계약 사본 동기화, Python source adapter 및 live
  loopback PDF/annotation/export flow를 실행했습니다. flow는 업로드·파싱·검색·인용
  검증·주석 retry/tombstone·export·SQLite 복구·원본 SHA 보존까지 통과했지만
  `llama_index` 부재로 RAG indexing은 `failed`였습니다.
- UNIT-05를 포함한 Web contract/typecheck, Node 1,310개, unit 656개, UNIT-05
  화면 관련 12개 테스트가 통과했습니다. Google Fonts를 가져오지 못해 Next
  production build는 완료되지 않았습니다.
- Cloud 실행 capability/secrets, Docker daemon, LLM credential, macOS/Xcode/iPadOS
  SDK 및 실제 iPad Pencil 기기는 이 환경에 없습니다. 각각의 통합 검증은 하지 않았습니다.

## 미완료 필수 제품 기능

이 브랜치는 `product_ready=false`입니다. UNIT-03 durable Reader/local store/Pencil
경로가 없고, durable Mnemosyne LearningStateStore와 Tutor/Quiz/Assessment/Memory/
Progress HTTP route가 없습니다. Provider/settings callback도 실제 runtime에 연결되지
않았습니다. 따라서 학습 상태 저장·복구나 웹/iPad 전체 사용자 흐름을 완료로 보고하지
않으며 이 draft PR은 제품 출시 승인용이 아닙니다. Requirement별 구현/검증 상태와
실행 명령은 `docs/handoffs/integration.md`, `docs/VALIDATION.md`에 기록했습니다.
