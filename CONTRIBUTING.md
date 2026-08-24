# PyKR에 기여하기

버그 수정, 테스트, 문서 개선과 사전·확장팩 품질 개선을 환영합니다. PyKR은 Python의 표기를 변환하는 작은 레이어이며 새로운 언어나 자연어 해석기로 범위를 넓히지 않습니다.

## 시작하기

```bash
python -m venv .venv
python -m pip install -e .
npm ci
```

Windows PowerShell에서는 `.venv/Scripts/Activate.ps1`, macOS/Linux에서는 `source .venv/bin/activate`로 가상환경을 활성화할 수 있습니다.

## 변경 전 확인

- 버그라면 재현 가능한 최소 입력과 기대 결과를 적습니다.
- 공개 동작이나 JSON 형식 변경은 테스트와 문서를 함께 수정합니다.
- 번역 규칙은 Core에 두고 CLI나 VS Code 확장에 복제하지 않습니다.
- 문자열·주석·사용자 식별자를 바꿀 수 있는 전체 문자열 치환을 사용하지 않습니다.
- 새 런타임 의존성은 표준 라이브러리로 해결할 수 없을 때만 제안합니다.

## 검증

Python 변경:

```bash
python -m unittest discover -s tests
python benchmarks/benchmark.py
```

VS Code 변경:

```bash
npm run check
npm run test:vscode
npm run package:vsix
```

전체 공개 패키지 확인:

```bash
python -m pip install .
pykr --version
pykr check GenderChange.Json
```

## Pull Request

PR 설명에는 다음을 포함해 주세요.

- 해결하는 문제와 변경 이유
- 사용자에게 보이는 동작 변화
- 실행한 테스트와 환경
- 호환성 또는 남은 제한

관련 없는 리팩터링과 대규모 이름 변경은 같은 PR에 섞지 마세요. 한 PR이 한 문제를 해결할수록 검토와 롤백이 쉽습니다.

기여된 코드는 프로젝트의 [MIT License](LICENSE)로 배포된다는 데 동의한 것으로 간주합니다.
