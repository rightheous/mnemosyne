# 통합 검토 요약

`codex/mnemosyne-integration`은 PR 기준 `main`
`16130d21410d1b2349ffee0757d44462c899ebbf`와 준비 commit
`5715a32927e3a73dc28782d306880e3dd1f62441`에서 분기한 별도 통합 브랜치다.
UNIT-01~06의 사용자가 지정한 모든 결과 SHA를 실제 diff로 합쳤고,
기본 브랜치에는 직접 반영하지 않았다. 계약 버전은 `0.2.0`이다.

## 적용한 정확한 unit refs

- UNIT-01: `c1f1f16b1cf12c9e66da1b3f24755cdb1412550f`, [Draft PR #2](https://github.com/rightheous/mnemosyne/pull/2)
- UNIT-02: `e024f81209a15b81630a5ab169013bdb868320d9`, PR 없음
- UNIT-03: `ae202f0cf1096d5fcc0ab1ecd325ac20a0d8e4b1`, PR 없음(사용자 요청)
- UNIT-04: `ced01afba5138598601c3b25933329d23a41282b`, [Draft PR #3](https://github.com/rightheous/mnemosyne/pull/3)
- UNIT-05: `e22a0e9d421adf3020e5359dcbda541e5ba378e0`, [Draft PR #4](https://github.com/rightheous/mnemosyne/pull/4)
- UNIT-06: `e14c599cb9977a41f5f17358a9ca17f33bce2327`, [Draft PR #1](https://github.com/rightheous/mnemosyne/pull/1)

UNIT-02는 제공된 전용 branch 결과로 포함했으며 별도 PR 링크는 제공되지 않았다.
UNIT-03은 제공된 branch/SHA를 fetch해 포함했고 요청에 따라 PR을 만들지 않았다.
통합 검토 PR은 [Draft PR #5](https://github.com/rightheous/mnemosyne/pull/5)다.

## 구현 및 검증

서버 lifespan은 Library, Tutor, SQLite 학습 저장소, provider runtime 및 quiz
generator를 등록한다. 웹/iPad Tutor 재접속용 receipt route를 실제 mount하고,
native turn event 계약 버전을 `0.2.0`으로 맞췄다. SQLite는 Quiz/채점 입력,
attempt/assessment, mastery, Memory, progress와 activity를 보존하며 web/iPad
mutation ID 재전송은 멱등 처리한다. PDF/Reader/Pencil, 웹, compose/CI 변경도
각 실제 앱 조립 및 route에 연결했다.

검증의 정확한 범위와 제한은 [docs/VALIDATION.md](VALIDATION.md), 필수 요구사항별
상태는 [통합 handoff](handoffs/integration.md)에 기록했다. 계약/source validator,
contract sync, adapter check, 일부 통합 tests, web static checks와 loopback PDF
HTTP 흐름이 통과했다. PDF 흐름은 업로드·파싱·검색·검증 인용·annotation
retry/tombstone·export·원본 SHA 보존까지 확인했지만 `llama_index` 부재로 실제
RAG index는 `failed`였다. 전체 targeted pytest의 최신 재실행은 executor에서
완료되지 않아 이전 통과 결과 및 별도 quiz idempotency test와 구분해 기록했다.

이 브랜치는 `product_ready=false`다. live LLM credential, vector index dependency,
Cloud execution capability/secrets, Docker daemon socket, Google Fonts build
network, macOS/Xcode/iPadOS SDK, Simulator 및 실제 Pencil device가 없어 해당
검증은 미완료다. 실제 browser end-to-end도 실행하지 않았다.
