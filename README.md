# 므네모시네 공통 준비

단일 사용자를 위한 iPad PDF/Pencil Reader, Mac 웹, 개인 서버의 문서 중심 학습 시스템.

**2026-10-08 현재: 소스 확인 대기 중인 준비 초안입니다.** 이 저장소는 처음 확인했을 때 파일·커밋·remote가 없었습니다. 재사용할 Pumice/DeepTutor의 정확한 URL/경로를 요청했습니다. 동명 프로젝트를 선택하지 않았으며 실제 제품 API, 라이선스, 빌드, 스트리밍을 확인했다는 의미가 아닙니다. 여섯 제품 작업을 시작하는 승인된 기준 커밋은 아직 없습니다.

- [요구사항](docs/REQUIREMENTS.md), [소스 감사](docs/UPSTREAM-AUDIT.md)
- [소유 경로](docs/OWNERSHIP.md), [통합과 시작 조건](docs/INTEGRATION.md)
- [UI 방향](docs/UI-DIRECTION.md), [계약 설명](contracts/README.md)
- [검증 결과](docs/VALIDATION.md), [준비 상태](integration/registry.json)

계약 버전 `0.1.0-draft.1`. 계약은 현재 구현을 반영한 확정 외부 API가 아니라 요구사항을 검증하기 위한 후보입니다. 소스 확인 후 실제 구현에 맞춰 같은 버전 묶음을 확정해야 합니다.

```sh
python3 -m venv /tmp/mnemosyne-checks
/tmp/mnemosyne-checks/bin/python -m pip install -r checks/requirements.txt
/tmp/mnemosyne-checks/bin/python checks/validate_contracts.py
node checks/web-consumer.mjs
swift -module-cache-path /tmp/mnemosyne-swift-cache checks/ipad-consumer.swift
/tmp/mnemosyne-checks/bin/python checks/validate_contracts.py --require-ready
```

마지막 명령은 소스 감사가 끝날 때까지 의도적으로 실패합니다. 앞의 성공은 제품 실행이나 실제 Pumice/DeepTutor 통합의 증거가 아닙니다. Python/Node/Swift 소비 예제는 공통 fixture 검사 전용입니다.
