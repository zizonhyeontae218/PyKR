# 변경 기록

주요 변경 사항은 이 파일에 기록합니다. 버전은 [Semantic Versioning](https://semver.org/)을 따릅니다.

## [1.0.0] - 2026-08-16

### 추가

- `run`, `to-py`, `to-kpy`, `check` CLI
- 사용자 `GenderChange.Json` 기반 양방향 변환
- `primary`, `aliases`, 충돌 및 스키마 검증
- `?` 사용자 변수 이스케이프
- 등록형 외부 API 확장팩과 import alias 추적
- VS Code 문법 강조, 의미 토큰, 진단, 실행과 양방향 변환
- 사전 변경 감지와 마지막 정상 사전 캐시
- Python 3.10~3.13 및 3개 운영체제 CI 매트릭스
- VS Code Extension Host 통합 테스트와 VSIX 패키징

### 성능

- 대표 36,729바이트 입력의 Windows/Python 3.12 측정에서 변환 중앙값을 538.20ms에서 348.00ms로 개선
- 같은 측정에서 최대 추적 메모리를 17.59MiB에서 14.31MiB로 절감
