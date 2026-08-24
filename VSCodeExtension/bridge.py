#!/usr/bin/env python3
"""VS Code와 PyKR Core 사이의 JSON/실행 브리지."""

from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import re
import sys
import tokenize
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Inverter import pykr_ui as core


TOKEN_TYPES = {
    "keywords": "keyword",
    "softKeywords": "keyword",
    "constants": "enumMember",
    "builtinFunctions": "function",
    "builtinTypes": "type",
    "exceptions": "class",
    "commonMethods": "method",
    "commonParameters": "parameter",
}


def validate_profile(profile: dict) -> None:
    core.validate_profile(profile)


def load_profile(path: str | None) -> dict:
    return core.load_profile(path or PROJECT_ROOT / "GenderChange.Json")


def load_extensions() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    forward, reverse, _ = core.load_extensions(
        [PROJECT_ROOT / "ExtensionPacks", core.USER_EXTENSION_DIR]
    )
    return forward, reverse


def error_location(message: str) -> tuple[int, int]:
    match = re.search(r"\((\d+):(\d+)\)", message)
    if match is None:
        return 0, 0
    return max(0, int(match.group(1)) - 1), max(0, int(match.group(2)) - 1)


def utf16_column(line: str, column: int) -> int:
    return len(line[:column].encode("utf-16-le")) // 2


def token_regions(source: str, base_offset: int = 0):
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    offsets = core._line_offsets(source)
    yield source, tokens, offsets, base_offset
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        token_start = base_offset + core._token_offset(offsets, token.start)
        for start, end in core._fstring_expression_spans(token.string):
            yield from token_regions(token.string[start:end], token_start + start)


def source_position(source: str, offsets: list[int], absolute: int) -> tuple[int, int]:
    line = max(0, bisect.bisect_right(offsets, absolute) - 1)
    column = absolute - offsets[line]
    line_end = offsets[line + 1] if line + 1 < len(offsets) else len(source)
    line_text = source[offsets[line] : line_end].rstrip("\r\n")
    return line, utf16_column(line_text, column)


def semantic_tokens(source: str, profile: dict) -> list[dict]:
    targets: dict[str, str] = {}
    for group, token_type in TOKEN_TYPES.items():
        for entry in profile["translation"][group].values():
            for target in [entry["primary"], *entry["aliases"]]:
                targets[target] = token_type

    source_offsets = core._line_offsets(source)
    result: list[dict] = []
    for _, tokens, offsets, base_offset in token_regions(source):
        previous, following, _, _ = core._token_context(tokens)
        for index, token in enumerate(tokens):
            if token.type != tokenize.NAME:
                continue
            prev_index = previous.get(index)
            next_index = following.get(index)
            prev = tokens[prev_index] if prev_index is not None else None
            next_token = tokens[next_index] if next_index is not None else None
            prefixed = prev is not None and prev.string == "?" and prev.end == token.start
            token_type = "variable" if prefixed else targets.get(token.string)
            if token_type is None and next_token is not None and next_token.string == "(":
                token_type = "method" if prev is not None and prev.string == "." else "function"
            if token_type is None:
                continue
            relative_start = core._token_offset(offsets, prev.start if prefixed else token.start)
            relative_end = core._token_offset(offsets, token.end)
            line, start = source_position(source, source_offsets, base_offset + relative_start)
            _, end = source_position(source, source_offsets, base_offset + relative_end)
            result.append(
                {"line": line, "start": start, "length": end - start, "type": token_type}
            )
    return sorted(result, key=lambda item: (item["line"], item["start"]))


def prefix_diagnostics(source: str, python_source: str, profile: dict) -> list[dict]:
    declared = core._variable_names(ast.parse(python_source))
    function_targets = set()
    for group in ("builtinFunctions", "builtinTypes", "exceptions"):
        for entry in profile["translation"][group].values():
            function_targets.update([entry["primary"], *entry["aliases"]])
    source_offsets = core._line_offsets(source)
    diagnostics: list[dict] = []

    for _, tokens, offsets, base_offset in token_regions(source):
        previous, following, _, call_arguments = core._token_context(tokens)
        for index, token in enumerate(tokens):
            if token.type != tokenize.NAME:
                continue
            prev_index = previous.get(index)
            next_index = following.get(index)
            prev = tokens[prev_index] if prev_index is not None else None
            next_token = tokens[next_index] if next_index is not None else None
            prefixed = prev is not None and prev.string == "?" and prev.end == token.start
            is_call = next_token is not None and next_token.string == "("

            if prefixed and is_call and token.string in function_targets:
                start_position = prev.start if prev is not None else token.start
                message = "번역된 함수에는 ?를 붙이지 않음"
            else:
                is_assignment = (
                    next_token is not None
                    and next_token.string == "="
                    and index not in call_arguments
                    and (prev is None or prev.string != ".")
                )
                excluded = (
                    prefixed
                    or is_call
                    or (
                        prev is not None
                        and prev.string in {".", "def", "class", "import", "from", "as"}
                    )
                    or (
                        next_token is not None
                        and next_token.string == "="
                        and index in call_arguments
                    )
                )
                if excluded or (token.string not in declared and not is_assignment):
                    continue
                start_position = token.start
                message = f"사용자 변수 '{token.string}' 앞에 ?가 필요함"

            relative_start = core._token_offset(offsets, start_position)
            relative_end = core._token_offset(offsets, token.end)
            line, start = source_position(source, source_offsets, base_offset + relative_start)
            _, end = source_position(source, source_offsets, base_offset + relative_end)
            diagnostics.append(
                {
                    "line": line,
                    "start": start,
                    "end": end,
                    "severity": "error",
                    "message": message,
                }
            )
    return diagnostics


def analyze(source: str, profile: dict, extension_reverse: dict) -> dict:
    diagnostics: list[dict] = []
    try:
        python_source = core.kpy_to_python(
            source,
            extension_reverse,
            profile,
            validate_prefix=False,
        )
        diagnostics.extend(prefix_diagnostics(source, python_source, profile))
    except (core.ConversionError, SyntaxError, tokenize.TokenError) as exc:
        line, column = error_location(str(exc))
        diagnostics.append(
            {
                "line": line,
                "start": column,
                "end": column + 1,
                "severity": "error",
                "message": str(exc),
            }
        )
    return {"diagnostics": diagnostics, "tokens": semantic_tokens(source, profile)}


def handle(request: dict) -> dict:
    action = request.get("action")
    profile = load_profile(request.get("dictionaryPath"))
    forward, reverse = load_extensions()
    if action == "analyze":
        return analyze(request.get("source", ""), profile, reverse)
    if action == "to-python":
        return {"content": core.kpy_to_python(request.get("source", ""), reverse, profile)}
    if action == "to-kpy":
        return {"content": core.python_to_kpy(request.get("source", ""), forward, profile)}
    if action == "validate-dictionary":
        return {"message": "GenderChange.Json 정상"}
    raise core.ConversionError(f"알 수 없는 브리지 작업: {action}")


def rpc() -> int:
    try:
        request = json.loads(sys.stdin.read())
        response = {"ok": True, **handle(request)}
    except Exception as exc:
        line, column = error_location(str(exc))
        response = {"ok": False, "error": str(exc), "line": line, "column": column}
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


def run(path: Path, dictionary: str | None) -> int:
    profile = load_profile(dictionary)
    from Printer.printer import run_kpy

    return run_kpy(path.resolve(), profile=profile).returncode


def self_check() -> None:
    request = {
        "action": "analyze",
        "source": '?값 = 정수(입력받기())\n퉤(f"값: {?값}")\n',
    }
    result = handle(request)
    assert not result["diagnostics"]
    assert any(token["type"] == "variable" for token in result["tokens"])
    broken = handle({"action": "analyze", "source": "값 = 1\n퉤(값)\n"})
    assert len(broken["diagnostics"]) == 2
    print("self-check: ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="PyKR VS Code 브리지")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("rpc")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("path", type=Path)
    run_parser.add_argument("--dictionary")
    subparsers.add_parser("self-check")
    args = parser.parse_args()
    if args.command == "rpc":
        return rpc()
    if args.command == "run":
        return run(args.path, args.dictionary)
    if args.command == "self-check":
        self_check()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
