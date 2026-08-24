# PyKR for VS Code 사용설명서

이 문서는 PyKR VS Code 확장의 설치, 사용자 사전 적용, 실행·변환 명령과 문제 해결 방법을 한곳에 정리한 위키형 안내서입니다.

## 1. 요구 사항

- VS Code 1.90 이상
- Python 3.10 이상
- `.kpy` 파일을 저장할 로컬 워크스페이스

확장은 Python으로 PyKR Core를 실행합니다. Microsoft Python 확장이 설치되어 있으면 현재 선택된 인터프리터를 우선 사용하고, 없으면 운영체제의 `python` 또는 `python3`를 사용합니다.

## 2. 설치

### VSIX 설치

터미널에서 설치:

```bash
code --install-extension pykr-1.0.0.vsix
```

VS Code 화면에서 설치:

1. 확장 보기(`Ctrl+Shift+X`)를 엽니다.
2. 우측 상단 `...` 메뉴에서 `VSIX에서 설치...`를 선택합니다.
3. `pykr-1.0.0.vsix`를 선택합니다.
4. 안내가 나오면 창을 다시 불러옵니다.

소스에서 VSIX를 만들려면 저장소 루트에서 다음을 실행합니다.

```bash
npm ci
npm run package:vsix
```

## 3. 첫 실행

1. 워크스페이스에서 `hello.kpy`를 만듭니다.
2. 다음 코드를 입력하고 저장합니다.

```kpy
?이름 = 입력받기("이름: ")
출력(f"안녕, {?이름}!")
```

3. 에디터 우측 상단 실행 버튼을 누르거나 `Ctrl+Alt+R`을 누릅니다.
4. Python 터미널에서 입력하고 결과를 확인합니다.

macOS에서는 `Cmd+Alt+R`을 사용합니다.

## 4. 명령과 단축키

명령 팔레트는 `Ctrl+Shift+P` 또는 `Cmd+Shift+P`로 엽니다.

| 명령 | 동작 | 기본 단축키 |
| --- | --- | --- |
| `PyKR: 현재 KPY 실행` | 현재 파일을 임시 Python으로 변환해 실행 | `Ctrl+Alt+R` / `Cmd+Alt+R` |
| `PyKR: KPY → Python` | 현재 KPY 옆에 새 `.py` 파일 생성 | `Ctrl+Alt+T` / `Cmd+Alt+T` |
| `PyKR: Python → KPY` | 현재 Python 옆에 새 `.kpy` 파일 생성 | `Ctrl+Alt+T` / `Cmd+Alt+T` |
| `PyKR: 기본 사전 열기` | 현재 설정에서 사용하는 사전 열기 | 없음 |
| `PyKR: 사전 다시 불러오기` | 사전을 검사하고 즉시 적용 | 없음 |
| `PyKR: 사전 검사` | 사전 형식·중복·충돌 검사 | 없음 |

변환 대상 파일이 이미 있으면 덮어쓰지 않고 `hello.1.py`, `hello.2.py`처럼 비어 있는 이름을 선택합니다.

## 5. 설정

설정 UI에서 `PyKR`을 검색하거나 워크스페이스의 `.vscode/settings.json`을 편집합니다.

```json
{
  "pykr.pythonPath": "",
  "pykr.dictionaryPath": ".pykr/GenderChange.Json",
  "pykr.diagnosticsDelay": 350
}
```

| 설정 | 기본값 | 설명 |
| --- | --- | --- |
| `pykr.pythonPath` | 빈 값 | VS Code Python 확장의 현재 인터프리터, 이후 PATH의 Python 사용 |
| `pykr.dictionaryPath` | 빈 값 | 비어 있으면 `Documents/PYKR/GenderChange.Json` 사용 |
| `pykr.diagnosticsDelay` | `350` | KPY 편집 후 실시간 검사를 시작할 때까지 기다릴 ms |

사전 경로는 다음처럼 해석합니다.

- 절대 경로: 그대로 사용
- `~/...`: 사용자 홈 기준
- 상대 경로: 해당 파일이 속한 워크스페이스 폴더 기준

`${workspaceFolder}` 같은 VS Code 변수 치환은 현재 지원하지 않습니다. 워크스페이스 상대 경로는 `.pykr/GenderChange.Json`처럼 작성하세요.

## 6. 사용자 사전 적용

### 기본 위치

설정을 비워두면 운영체제 사용자 홈 아래의 다음 파일을 사용합니다.

```text
Documents/PYKR/GenderChange.Json
```

파일이 없으면 확장에 포함된 기본 사전을 최초 한 번 복사합니다. 기존 사전은 덮어쓰지 않습니다.

### 워크스페이스 전용 사전

프로젝트와 사전을 함께 관리하려면 다음처럼 설정합니다.

```json
{
  "pykr.dictionaryPath": ".pykr/GenderChange.Json"
}
```

그 다음 명령 팔레트에서 `PyKR: 기본 사전 열기`를 실행하면 해당 파일을 바로 편집할 수 있습니다.

### 유효한 최소 사전

```json
{
  "schemaVersion": 2,
  "profile": {
    "name": "우리 팀 사전",
    "description": "프로젝트에서 함께 사용하는 PyKR 표현",
    "language": "ko-KR"
  },
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
      "print": {
        "primary": "출력",
        "aliases": ["말해", "퉤"]
      },
      "input": {
        "primary": "입력받기",
        "aliases": []
      }
    },
    "builtinTypes": {},
    "exceptions": {},
    "commonMethods": {},
    "commonParameters": {}
  }
}
```

### `primary`와 `aliases`

```json
"print": {
  "primary": "출력",
  "aliases": ["말해", "퉤"]
}
```

- Python→KPY는 항상 `출력`을 만듭니다.
- KPY→Python은 `출력`, `말해`, `퉤`를 모두 `print`로 읽습니다.
- 같은 번역어를 다른 Python 표현에도 등록하면 충돌 오류가 발생합니다.
- `primary`와 `aliases` 안에서도 중복할 수 없습니다.

### 사전 그룹

| 그룹 | 예 |
| --- | --- |
| `keywords` | `if`, `for`, `return` |
| `softKeywords` | `match`, `case` |
| `constants` | `True`, `False`, `None` |
| `builtinFunctions` | `print`, `input`, `len` |
| `builtinTypes` | `int`, `str`, `list` |
| `exceptions` | `ValueError`, `TypeError` |
| `commonMethods` | `append`, `split`, `read` |
| `commonParameters` | `end`, `sep`, `encoding` |

모든 그룹 키가 존재해야 하며 사용하지 않는 그룹은 빈 객체 `{}`로 둡니다.

## 7. `?` 사용자 변수 규칙

사전 번역어와 같은 이름의 사용자 변수도 안전하게 보존하기 위해 KPY에서는 사용자 변수 앞에 `?`를 붙입니다.

```python
출력 = "값"
print(출력)
```

```kpy
?출력 = "값"
출력(?출력)
```

- bare `출력`: 사전에 등록된 `print`
- `?출력`: 사용자가 만든 변수 `출력`

문자열과 주석 안의 `?`는 변수 접두사로 처리하지 않습니다.

## 8. 사전 변경 감지와 안전한 재로딩

확장은 사전 파일의 생성·수정·삭제를 감시하고 200ms 뒤 다시 검사합니다.

검증에 성공하면:

1. 검증된 사본을 VS Code 확장 전용 저장소에 보관합니다.
2. 열린 KPY 분석 캐시를 비웁니다.
3. 진단과 의미 강조를 새 사전으로 다시 계산합니다.

검증에 실패하면:

- 사전 편집기에 오류를 표시합니다.
- 잘못된 파일은 변환·실행에 적용하지 않습니다.
- 마지막으로 검증된 정상 사전을 계속 사용합니다.

저장 후 즉시 적용되지 않으면 `PyKR: 사전 다시 불러오기`를 실행하세요. 여러 폴더를 한 창에서 연 멀티 루트 워크스페이스에서는 폴더별 사전 변경 후 수동 다시 불러오기가 필요할 수 있습니다.

## 9. 문법 강조와 진단

기본 TextMate 문법은 문자열·주석·숫자·괄호 등 Python 구조를 표시합니다. 사용자 사전의 번역어는 Python Core가 만든 semantic token으로 강조하므로 사전을 바꿔도 확장을 다시 빌드할 필요가 없습니다.

실시간 진단에는 다음이 포함됩니다.

- KPY 변환 문법 오류
- 필수 `?` 접두사 누락
- 잘못된 사전 형식
- 중복·충돌 번역어

진단 위치는 임시 Python 파일이 아니라 원본 KPY 줄과 열을 가리킵니다.

## 10. 실행과 변환

### 실행

`PyKR: 현재 KPY 실행`은 현재 문서를 저장한 후 검증된 사전으로 임시 `.py` 파일을 만들고 선택된 Python 인터프리터로 실행합니다. 임시 파일은 정상 종료와 오류 경로에서 정리됩니다.

실행만 사용자 코드를 실제로 수행합니다. 진단, 사전 검사와 양방향 변환은 코드를 실행하지 않습니다.

### 양방향 변환

- KPY→Python: `primary`와 `aliases`를 인식
- Python→KPY: 항상 `primary`만 출력
- 문자열, 주석, 등록되지 않은 식별자는 보존
- 사용자 변수의 정의와 참조에 `?` 적용

결과는 표준 Python과 의미·실행 결과가 같아야 합니다. 따옴표 종류 같은 모든 서식의 바이트 단위 왕복은 보장하지 않습니다.

## 11. 확장팩

사용자 확장팩 기본 위치:

```text
Documents/PYKR/ExtensionPacks
```

확장 최초 사용 시 공식 확장팩도 이 폴더에 복사됩니다. 확장팩은 `pandas.DataFrame`, `os.path.join`처럼 등록된 정규 API 경로만 번역합니다. import alias는 추적하지만 등록되지 않은 멤버나 동적 속성을 추측하지 않습니다.

## 12. 문제 해결

### `python`을 찾을 수 없음

VS Code에서 Python 인터프리터를 선택하거나 절대 경로를 설정합니다.

```json
{
  "pykr.pythonPath": "C:/Python312/python.exe"
}
```

macOS/Linux 예:

```json
{
  "pykr.pythonPath": "/usr/bin/python3"
}
```

### `지원하지 않는 GenderChange schemaVersion`

최상위 `schemaVersion`을 `2`로 사용하세요. 다른 주요 버전은 추측해서 읽지 않습니다.

### `빈 대표 번역어`

공개 사용자 사전의 모든 항목은 비어 있지 않은 `primary`를 가져야 합니다. 사용하지 않을 항목은 항목 전체를 제거하세요.

### `사전 번역어 충돌`

오류에 표시된 두 Python 원문 중 하나의 `primary` 또는 `aliases`를 바꾸세요. PyKR은 충돌을 임의로 선택하지 않습니다.

### 사전을 고쳤는데 예전 강조가 남음

파일을 저장한 뒤 `PyKR: 사전 다시 불러오기`를 실행하세요. 그래도 남으면 `Developer: Reload Window`로 확장 호스트를 다시 시작하세요.

### 변환 파일이 예상한 이름과 다름

기존 파일 보호가 기본값입니다. 같은 이름의 출력이 있으면 `.1`, `.2` 접미사가 붙습니다.

## 13. 개인정보와 보안

- 사전과 소스는 로컬 Python 프로세스에만 전달됩니다.
- 확장은 사전을 인터넷에서 내려받거나 외부 서버로 전송하지 않습니다.
- 검증된 사전 캐시는 VS Code의 확장 전용 `globalStorage`에 저장됩니다.
- 민감한 문자열이 포함된 소스를 이슈에 첨부하기 전에 반드시 제거하세요.

취약점 신고 절차는 [SECURITY.md](../SECURITY.md)를 따릅니다.

## 14. 개발자용 검증

```bash
npm ci
npm run check
npm run test:vscode
npm run package:vsix
```

`npm run test:vscode`는 실제 VS Code Extension Host에서 언어 등록, 자동 닫기, 진단, 의미 토큰, 양방향 변환과 손상된 사전의 마지막 정상본 유지 동작을 검사합니다.
