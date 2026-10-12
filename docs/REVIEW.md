## 요약

`origin/main` (`16130d21410d1b2349ffee0757d44462c899ebbf`)과 준비 커밋
`5715a32927e3a73dc28782d306880e3dd1f62441`에서 만든
`codex/mnemosyne-integration` 브랜치에 확인 가능한 UNIT-01/04/05/06 변경을
통합하고, pairing/session 인증과 보호된 Library router를 실제 서버 수명 주기에
연결했습니다. 계약 0.1.0의 DTO는 바꾸지 않았고 두 upstream 계약 사본의 digest를
갱신했습니다.

## 적용한 정확한 unit refs

- UNIT-01: `c1f1f16b1cf12c9e66da1b3f24755cdb1412550f`, PR #2
- UNIT-02: baseline `main` commit `16130d21410d1b2349ffee0757d44462c899ebbf`; no separate branch/PR
- UNIT-03: user-supplied branch `codex/unit-03-reader`, commit `ae202f0cf1096d5fcc0ab1ecd325ac20a0d8e4b1`; no PR
- UNIT-04: `ced01afba5138598601c3b25933329d23a41282b`, PR #3
- UNIT-05: `e22a0e9d421adf3020e5359dcbda541e5ba378e0`, branch `codex/unit-05-api-refresh`, Draft PR #4
- UNIT-06: `e14c599cb9977a41f5f17358a9ca17f33bce2327`, PR #1

요청에 처음 포함된 값은 저장소 URL뿐이었으나 이후 UNIT-05 정확한 ref가 제공돼
통합했습니다. UNIT-03의 정확한 식별 정보는 제공됐으나 현재 workspace의 local refs/object DB와 `origin` 어느 쪽에서도
`ae202f0cf1096d5fcc0ab1ecd325ac20a0d8e4b1`를 가져오지 못했습니다. 정확한 branch fetch는 `couldn't find remote ref`, SHA fetch는 `not our ref`, GitHub commit API는 422 `No commit found for SHA`를 반환해 소스 diff는 통합되지 않았습니다. 사용자 보고에 따르면 UNIT-03 별도 PR 생성은 자동 승인 검토의 `429 Too Many Requests`로 중단됐습니다. 이 검토 제한을 우회하는 재시도는 하지 않았습니다. UNIT-02는 별도 결과가 아니라 기준 main의 `16130d21410d1b2349ffee0757d44462c899ebbf`를 사용했습니다. UNIT-01/#2, UNIT-04/#3, UNIT-06/#1은 현재 열린 draft PR이며 main에는 병합되지 않았습니다. UNIT-05는 위 exact commit으로 통합했습니다.

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
