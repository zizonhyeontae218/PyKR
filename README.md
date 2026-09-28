[ILCX 6H grade](https://github.com/zizonhyeontae218/ILCX_H-grade-system)

# PyKR

> 내 Python을, 내가 정한 한국어로.

PyKR은 사용자 정의 한국어 Python 방언(`.kpy`)과 표준 Python(`.py`)을 양방향으로 변환하는 도구입니다. 새로운 언어나 런타임을 만들지 않습니다. 변환 결과는 일반 Python 코드이며 기존 Python 도구와 그대로 함께 사용할 수 있습니다.

```kpy
?이름 = 입력받기("이름: ")
만약 ?이름:
    출력(f"안녕, {?이름}!")
```

```python
이름 = input("이름: ")
if 이름:
    print(f"안녕, {이름}!")
```

## 주요 기능

- `.kpy → .py`, `.py → .kpy` 결정적 변환
- `GenderChange.Json`으로 키워드·기본 함수·자료형·예외·메서드 번역어 변경
- Python→KPY에는 `primary`만 사용하고 KPY→Python에는 `aliases`도 인식
- `?변수`로 사용자 식별자와 사전 번역어를 명확하게 구분
- 문자열·주석·사용자 함수명·클래스명 보존
- 등록된 정규 API 경로만 처리하는 확장팩
- CLI와 VS Code 확장 모두 동일한 Python Core 사용
- UTF-8 BOM과 원본 개행 보존, 기본 덮어쓰기 방지

## 요구 사항

- Python 3.10 이상
- VS Code 확장 사용 시 VS Code 1.90 이상
- Node.js는 소스에서 VS Code 확장을 개발하거나 패키징할 때만 필요

## 설치

PyPI 공개 후에는 다음 명령으로 설치합니다.

```bash
python -m pip install pykr-dialect
```

현재 소스에서 설치하려면 저장소 루트에서 실행합니다.

```bash
python -m pip install .
pykr --version
```

VS Code 확장은 빌드된 VSIX를 직접 설치할 수 있습니다.

```bash
code --install-extension pykr-1.0.0.vsix
```

상세 설정, 사용자 사전 적용, 명령과 문제 해결 방법은 [VS Code 확장 사용설명서](docs/vscode-extension.md)를 참고하세요.

## 빠른 시작

```bash
# KPY를 표준 Python으로 변환
pykr to-py Examples/Hello_World.kpy

# Python을 KPY로 변환
pykr to-kpy Examples/Hello_World.py

# KPY를 임시 Python 파일로 변환해 실행
pykr run Examples/Hello_World.kpy

# 사전 또는 소스 검사
pykr check GenderChange.Json
pykr check Examples/Hello_World.kpy
```

변환은 기본적으로 입력 옆에 새 파일을 만들며 기존 파일을 덮어쓰지 않습니다. 출력 위치를 직접 정하거나 기존 출력을 명시적으로 교체할 수 있습니다.

```bash
pykr to-py hello.kpy -o build/hello.py
pykr to-py hello.kpy --overwrite
pykr to-kpy hello.py --dictionary ./profiles/team/GenderChange.Json
pykr run hello.kpy --python /path/to/python
```

공통 옵션:

- `--dictionary PATH`: 사용할 `GenderChange.Json`
- `--extension-dir PATH`: 확장팩 폴더, 여러 번 지정 가능
- `-o`, `--output PATH`: 변환 출력 경로
- `--overwrite`: 기존 출력 파일을 원자적으로 교체

종료 코드:

| 코드 | 의미 |
| ---: | --- |
| 0 | 성공 |
| 2 | 명령 사용 오류 |
| 3 | 사전 또는 확장팩 오류 |
| 4 | 변환 또는 문법 오류 |
| 5 | 변환된 프로그램 실행 오류 |
| 6 | 파일 입출력 오류 |

## 사용자 사전

실제 번역어는 소스 코드가 아니라 `GenderChange.Json`에서만 읽습니다. 다음은 유효한 최소 사전 예시입니다.

```json
{
  "schemaVersion": 2,
  "profile": { "name": "My Korean" },
  "syntax": {
    "sourceExtension": ".kpy",
    "targetExtension": ".py",
    "variablePrefix": "?",
    "variablePrefixMode": "required"
  },
  "translation": {
    "keywords": {},
    "softKeywords": {},
    "constants": {},
    "builtinFunctions": {
      "print": { "primary": "출력", "aliases": ["말해", "퉤"] }
    },
    "builtinTypes": {},
    "exceptions": {},
    "commonMethods": {},
    "commonParameters": {}
  }
}
```

규칙은 단순합니다.

- `primary`: Python→KPY에서 출력할 유일한 대표 표현
- `aliases`: KPY→Python에서만 추가로 인식할 표현
- 서로 다른 Python 표현이 같은 번역어를 가질 수 없음
- 공개 사전의 `primary`는 비울 수 없음
- 번역어는 유효한 Python 식별자여야 함
- 사용자 변수는 `?이름`처럼 작성하며 Python으로 변환할 때 `?`만 제거됨

기본 사전은 [GenderChange.Json](GenderChange.Json), 형식 정의는 [JSON Schema](VSCodeExtension/gender-change.schema.json)에 있습니다.

## 확장팩

확장팩은 외부 라이브러리 전체를 추측해서 번역하지 않습니다. JSON에 등록된 정규 Python API 경로만 변환하고 import alias를 추적합니다.

```python
import pandas as pd
frame = pd.DataFrame(data)
```

위 코드는 확장팩의 `pandas.DataFrame` 등록 항목을 기준으로 처리합니다. 기본 팩은 [OfficialExtensionPack.Json](ExtensionPacks/OfficialExtensionPack.Json)에 있으며, 개인 팩은 기본적으로 `Documents/PYKR/ExtensionPacks`에서 읽습니다.

## VS Code

확장은 다음 기능을 제공합니다.

- `.kpy` 언어 등록과 Python 기반 문법 강조
- 사용자 사전 기반 의미 강조와 실시간 진단
- 현재 KPY 실행
- KPY→Python, Python→KPY 새 파일 변환
- `GenderChange.Json` 스키마 및 충돌 검사
- 사전 변경 자동 감지와 마지막 정상 사전 유지

VS Code 구현과 사용법은 [별도 사용설명서](docs/vscode-extension.md)에 정리되어 있습니다.

## 안전성과 호환성

- `to-py`, `to-kpy`, `check`는 대상 코드를 실행하지 않습니다.
- `run`만 사용자가 지정한 KPY를 변환한 뒤 선택한 Python으로 실행합니다.
- 변환 결과는 표준 Python이며 별도 PyKR 런타임을 요구하지 않습니다.
- 문자열, 주석, 숫자와 등록되지 않은 식별자는 번역하지 않습니다.
- 변환은 의미와 실행 결과 보존을 우선하며 따옴표 등 모든 바이트의 완전한 왕복을 보장하지는 않습니다.

## 개발과 검증

```bash
python -m unittest discover -s tests
python benchmarks/benchmark.py
npm ci
npm run check
npm run test:vscode
npm run package:vsix
```

테스트에는 토큰 안전성, 사전 충돌, `?` 변수, import alias, 인코딩·개행, 덮어쓰기 보호, 임시 파일 정리, 실행 의미와 1,000개 생성 구문의 AST 왕복이 포함됩니다. GitHub Actions는 Python 3.10~3.13과 Windows·macOS·Linux 조합 및 VS Code Extension Host 통합 테스트를 실행하도록 구성되어 있습니다.

2026-08-16 Windows/Python 3.12의 36,729바이트 대표 입력에서 양방향 변환 중앙값은 최적화 전 538.20ms에서 348.00ms로, 최대 추적 메모리는 17.59MiB에서 14.31MiB로 줄었습니다. 환경에 따라 달라지므로 같은 기준은 `benchmarks/benchmark.py`로 다시 측정할 수 있습니다.

## 프로젝트 구조

| 경로 | 역할 |
| --- | --- |
| `Inverter/` | 사전 검증, 토큰 처리, 양방향 변환 Core |
| `Printer/` | KPY 임시 변환 및 Python 실행 어댑터 |
| `pykr.py` | 공개 CLI |
| `VSCodeExtension/` | VS Code UI와 Python Core 브리지 |
| `ExtensionPacks/` | 등록형 외부 API 번역팩 |
| `tests/` | Core·CLI 회귀 테스트 |
| `benchmarks/` | 시간·최대 추적 메모리 측정 |

## 기여와 공개 정책

- 버그 신고와 변경 제안 전 [CONTRIBUTING.md](CONTRIBUTING.md)를 확인하세요.
- 모든 참여자는 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)를 따릅니다.
- 보안 취약점은 공개 이슈 대신 [SECURITY.md](SECURITY.md)의 비공개 절차로 신고하세요.
- 릴리스 변경점은 [CHANGELOG.md](CHANGELOG.md)에 기록합니다.
- PyKR은 [MIT License](LICENSE)로 공개됩니다.

GitHub 저장소: [zizonhyeontae218/PyKR](https://github.com/zizonhyeontae218/PyKR)
