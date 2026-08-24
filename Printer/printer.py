#!/usr/bin/env python3
"""입력받은 KPY 파일을 표준 Python으로 변환해 실행한다."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Inverter.pykr_ui import (
    USER_EXTENSION_DIR,
    ConversionError,
    decode_source,
    kpy_to_python,
    load_extensions,
)


RUNNER = """\
import sys
from pathlib import Path
source_path, path = sys.argv[1:]
sys.argv = [path]
scope = {"__name__": "__main__", "__file__": path, "__package__": None}
exec(compile(Path(source_path).read_text(encoding="utf-8"), path, "exec"), scope)
"""


def run_kpy(
    path: Path,
    *,
    capture_output: bool = False,
    profile: dict | None = None,
    python_executable: str | None = None,
    extension_reverse: dict[tuple[str, str], str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if path.suffix.lower() != ".kpy" or not path.is_file():
        raise ConversionError(f"KPY 파일을 찾을 수 없음: {path}")

    if extension_reverse is None:
        _, extension_reverse, _ = load_extensions(
            [PROJECT_ROOT / "ExtensionPacks", USER_EXTENSION_DIR]
        )
    source = decode_source(path.read_bytes())
    python_source = kpy_to_python(source, extension_reverse, profile)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".py",
            prefix=f".{path.stem}-",
            delete=False,
        ) as temporary:
            temporary.write(python_source)
            temporary_path = Path(temporary.name)
        return subprocess.run(
            [python_executable or sys.executable, "-X", "utf8", "-c", RUNNER, str(temporary_path), str(path)],
            cwd=path.parent,
            capture_output=capture_output,
            encoding="utf-8",
            check=False,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def self_check() -> None:
    with tempfile.TemporaryDirectory() as directory:
        example = Path(directory) / "example.kpy"
        example.write_text('퉤("PRINTER_OK")\n', encoding="utf-8")
        result = run_kpy(example, capture_output=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "PRINTER_OK"
    print("self-check: ok")


def main() -> int:
    if sys.argv[1:] == ["--self-check"]:
        self_check()
        return 0

    try:
        entered = input("실행할 .kpy 파일 경로: ").strip().strip('"')
        return run_kpy(Path(entered).expanduser().resolve()).returncode
    except (ConversionError, OSError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
