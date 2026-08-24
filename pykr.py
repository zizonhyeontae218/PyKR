#!/usr/bin/env python3
"""PyKR 공개 명령줄 인터페이스."""

from __future__ import annotations

import argparse
import ast
import os
import sys
import tempfile
from pathlib import Path

from Inverter.pykr_ui import (
    PROJECT_EXTENSION_DIR,
    INSTALLED_DATA_DIR,
    USER_EXTENSION_DIR,
    ConversionError,
    ProfileError,
    decode_source_with_encoding,
    kpy_to_python,
    load_extensions,
    load_profile,
    python_to_kpy,
)
from Printer.printer import run_kpy

VERSION = "1.0.0"
EXIT_DICTIONARY = 3
EXIT_CONVERSION = 4
EXIT_EXECUTION = 5
EXIT_IO = 6


def _extension_dirs(values: list[str] | None) -> list[Path]:
    return (
        [Path(value).expanduser() for value in values]
        if values
        else [
            PROJECT_EXTENSION_DIR
            if PROJECT_EXTENSION_DIR.is_dir()
            else INSTALLED_DATA_DIR / "ExtensionPacks",
            USER_EXTENSION_DIR,
        ]
    )


def _write_output(path: Path, content: str, encoding: str, *, overwrite: bool) -> None:
    data = content.encode(encoding)
    if not overwrite:
        with path.open("xb") as output:
            output.write(data)
        return
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            prefix=f".{path.name}-",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as output:
            output.write(data)
            temporary_path = Path(output.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _convert(args: argparse.Namespace, *, to_python: bool) -> int:
    source_path = args.input.resolve()
    expected = ".kpy" if to_python else ".py"
    target_suffix = ".py" if to_python else ".kpy"
    if source_path.suffix.lower() != expected or not source_path.is_file():
        raise ConversionError(f"{expected} 입력 파일을 찾을 수 없음: {source_path}")
    target = (args.output or source_path.with_suffix(target_suffix)).resolve()
    if target == source_path:
        raise ConversionError("입력과 출력 경로가 같음")

    source, encoding = decode_source_with_encoding(source_path.read_bytes())
    profile = load_profile(args.dictionary)
    forward, reverse, _ = load_extensions(_extension_dirs(args.extension_dir))
    content = (
        kpy_to_python(source, reverse, profile)
        if to_python
        else python_to_kpy(source, forward, profile)
    )
    _write_output(target, content, encoding, overwrite=args.overwrite)
    print(target)
    return 0


def _check(args: argparse.Namespace) -> int:
    path = args.path.resolve()
    if path.suffix.lower() == ".json":
        load_profile(path, template=args.template)
    elif path.suffix.lower() == ".kpy":
        source, _ = decode_source_with_encoding(path.read_bytes())
        profile = load_profile(args.dictionary)
        _, reverse, _ = load_extensions(_extension_dirs(args.extension_dir))
        compile(kpy_to_python(source, reverse, profile), str(path), "exec")
    elif path.suffix.lower() == ".py":
        source, _ = decode_source_with_encoding(path.read_bytes())
        ast.parse(source, filename=str(path))
    else:
        raise ConversionError(f"검사할 수 없는 파일 형식: {path}")
    print(f"정상: {path}")
    return 0


def _run(args: argparse.Namespace) -> int:
    profile = load_profile(args.dictionary)
    _, reverse, _ = load_extensions(_extension_dirs(args.extension_dir))
    result = run_kpy(
        args.input.resolve(),
        profile=profile,
        python_executable=args.python,
        extension_reverse=reverse,
    )
    return 0 if result.returncode == 0 else EXIT_EXECUTION


def _shared(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dictionary", type=Path, help="GenderChange.Json 경로")
    parser.add_argument(
        "--extension-dir",
        action="append",
        help="확장팩 폴더(여러 번 지정 가능)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pykr", description="한국어 Python 방언 변환기")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    to_py = commands.add_parser("to-py", help="KPY를 표준 Python으로 변환")
    to_py.add_argument("input", type=Path)
    to_py.add_argument("-o", "--output", type=Path)
    to_py.add_argument("--overwrite", action="store_true")
    _shared(to_py)
    to_py.set_defaults(handler=lambda args: _convert(args, to_python=True))

    to_kpy = commands.add_parser("to-kpy", help="Python을 KPY로 변환")
    to_kpy.add_argument("input", type=Path)
    to_kpy.add_argument("-o", "--output", type=Path)
    to_kpy.add_argument("--overwrite", action="store_true")
    _shared(to_kpy)
    to_kpy.set_defaults(handler=lambda args: _convert(args, to_python=False))

    run = commands.add_parser("run", help="KPY를 변환한 뒤 실행")
    run.add_argument("input", type=Path)
    run.add_argument("--python", help="사용할 Python 실행 파일")
    _shared(run)
    run.set_defaults(handler=_run)

    check = commands.add_parser("check", help="사전 또는 소스 파일 검사")
    check.add_argument("path", type=Path)
    check.add_argument("--template", action="store_true", help="빈 primary를 허용")
    _shared(check)
    check.set_defaults(handler=_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ProfileError as exc:
        print(f"사전 오류: {exc}", file=sys.stderr)
        return EXIT_DICTIONARY
    except (ConversionError, SyntaxError) as exc:
        print(f"변환 오류: {exc}", file=sys.stderr)
        return EXIT_CONVERSION
    except OSError as exc:
        print(f"파일 오류: {exc}", file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
