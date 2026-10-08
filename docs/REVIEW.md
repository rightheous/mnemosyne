# 저장된 PR 본문

제목: feat: prepare source-backed Mnemosyne bootstrap

여섯 독립 구현 작업이 같은 소스·계약·소유 경계에서 출발하도록, 지정한 Pumice와 DeepTutor의 원래 tracked 트리를 각각 a688aae2e6bce069ee256063c2a53afdcfe7de21 / 6cf793bd868ba5ecbe64722936d4be8fab5a01df에 고정했다. 내부 레이아웃·Swift/Python/Next 스택과 라이선스를 유지한다.

계약 0.1.0은 문서 원본 full SHA/물리 페이지/회전·CropBox/주석 sync/Reader·학습 상태를 고정한다. DeepTutor의 native /ws protocol 2.0을 선택해 opaque turn ID와 native seq/replay/cancel을 유지한다. HTTP extension과 제품 ports의 미구현 상태는 명시한다. 동일 bundle을 두 source에 배포하고 파일 단위 소유권/provenance를 검사한다.

실제 ReadingStore/PyMuPDF/SQLite/native wire adapter, Pumice Core geometry/facade와 iPad decoder, 웹 TS/PDF.js consumer와 등록 seam을 추가했다. 기존 파일 수정은 integrator-owned main.py의 lifespan 등록 한 곳이다. 필수 학습·오프라인·불변 원본·한국어·개인 보호 기능은 모두 이번 유닛 구현 범위에 유지했다.

검증: source gate/30 OpenAPI operations/4 schemas/동일 bundle/80 schema instances/19 거부 사례/10 sync steps PASS, 세 소비자와 실제 SQLite 재전송·reopen replay PASS, 원래 DeepTutor focused tests 116 PASS, Core library build/웹 contracts·types·production build/Compose config/architecture/new adapter Ruff PASS. 공식 Pumice test는 CLT Testing 모듈 부재로 FAIL. Full iPad/Pencil/WSL2/실제 LLM·제품 end-to-end는 미검증. 자세한 명령과 한계는 docs/VALIDATION.md.

준비 branch codex/mnemosyne-bootstrap, 시작 tag mnemosyne-bootstrap-v0.1.0. root remote가 없어 GitHub PR은 생성하지 않았다. 기본 브랜치에 직접 통합하지 않았다.
