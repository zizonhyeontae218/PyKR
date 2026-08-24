#!/usr/bin/env python3
"""PyKR의 내장 사전 기반 Python↔KPY 드래그앤드롭 UI."""

from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import keyword
import sys
import threading
import tokenize
import unicodedata
import webbrowser
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections.abc import Iterable
from urllib.parse import parse_qs, urlparse

MAX_SOURCE_BYTES = 5 * 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_EXTENSION_DIR = PROJECT_ROOT / "ExtensionPacks"
USER_EXTENSION_DIR = Path.home() / "Documents" / "PYKR" / "ExtensionPacks"
INSTALLED_DATA_DIR = Path(sys.prefix) / "share" / "pykr"


class ConversionError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 변환 오류."""


class ProfileError(ConversionError):
    """사전 또는 확장팩 형식 오류."""


TRANSLATION_GROUPS = (
    "keywords",
    "softKeywords",
    "constants",
    "builtinFunctions",
    "builtinTypes",
    "exceptions",
    "commonMethods",
    "commonParameters",
)


def validate_profile(profile: dict, *, template: bool = False) -> None:
    if not isinstance(profile, dict) or profile.get("schemaVersion") != 2:
        raise ProfileError("지원하지 않는 GenderChange schemaVersion")
    syntax = profile.get("syntax")
    if not isinstance(syntax, dict):
        raise ProfileError("syntax 객체가 없음")
    prefix = syntax.get("variablePrefix")
    if prefix != "?":
        raise ProfileError("지원하지 않는 syntax.variablePrefix")
    if syntax.get("variablePrefixMode") not in {"required", "optional"}:
        raise ProfileError("지원하지 않는 syntax.variablePrefixMode")
    translation = profile.get("translation")
    if not isinstance(translation, dict):
        raise ProfileError("translation 객체가 없음")

    owners: dict[str, str] = {}
    for group in TRANSLATION_GROUPS:
        entries = translation.get(group)
        if not isinstance(entries, dict):
            raise ProfileError(f"translation.{group} 객체가 없음")
        for source, entry in entries.items():
            if not isinstance(source, str) or not source:
                raise ProfileError(f"잘못된 사전 원문: {group}.{source}")
            if not isinstance(entry, dict):
                raise ProfileError(f"잘못된 사전 항목: {group}.{source}")
            primary = entry.get("primary")
            aliases = entry.get("aliases")
            if not isinstance(primary, str) or (not primary and not template):
                raise ProfileError(f"빈 대표 번역어: {group}.{source}")
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) and alias for alias in aliases
            ):
                raise ProfileError(f"잘못된 aliases: {group}.{source}")
            values = ([primary] if primary else []) + aliases
            if any(not value.isidentifier() for value in values):
                raise ProfileError(f"식별자가 아닌 번역어: {group}.{source}")
            normalized = [unicodedata.normalize("NFC", value) for value in values]
            if len(normalized) != len(set(normalized)):
                raise ProfileError(f"항목 내부 번역어 중복: {group}.{source}")
            for target in normalized:
                previous = owners.get(target)
                if previous is not None and previous != source:
                    raise ProfileError(f"사전 번역어 충돌: {target}: {previous} / {source}")
                owners[target] = source


@lru_cache(maxsize=16)
def _load_profile_file(path: str, modified_ns: int, size: int, template: bool) -> dict:
    del modified_ns, size
    try:
        profile = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"GenderChange.Json을 읽을 수 없음: {path}: {exc}") from exc
    validate_profile(profile, template=template)
    return profile


def load_profile(path: str | Path | None = None, *, template: bool = False) -> dict:
    if path is None:
        candidates = (
            PROJECT_ROOT / "GenderChange.Json",
            INSTALLED_DATA_DIR / "GenderChange.Json",
        )
        profile_path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if profile_path is None:
            raise ProfileError("기본 GenderChange.Json을 찾을 수 없음")
    else:
        profile_path = Path(path).expanduser()
    try:
        stat = profile_path.stat()
    except OSError as exc:
        raise ProfileError(f"GenderChange.Json을 읽을 수 없음: {profile_path}: {exc}") from exc
    return _load_profile_file(str(profile_path.resolve()), stat.st_mtime_ns, stat.st_size, template)


def embedded_gender_change() -> dict:
    """기존 호출자를 위한 기본 profile 접근점."""
    return load_profile()


def _primary_map(profile: dict, group: str) -> dict[str, str]:
    entries = profile["translation"][group]
    return {source: entry["primary"] for source, entry in entries.items()}


def _reverse_map(profile: dict, group: str) -> dict[str, str]:
    reverse: dict[str, str] = {}
    for source, entry in profile["translation"][group].items():
        for target in [entry["primary"], *entry["aliases"]]:
            previous = reverse.get(target)
            if previous is not None and previous != source:
                raise ConversionError(f"내장 사전 역방향 충돌: {target}: {previous} / {source}")
            reverse[target] = source
    return reverse


def _profile_indexes(profile: dict) -> dict[str, dict]:
    builtins: dict[str, str] = {}
    builtin_reverse: dict[str, str] = {}
    for group in ("builtinFunctions", "builtinTypes", "exceptions"):
        builtins.update(_primary_map(profile, group))
        for target, original in _reverse_map(profile, group).items():
            previous = builtin_reverse.get(target)
            if previous is not None and previous != original:
                raise ProfileError(f"내장 사전 역방향 충돌: {target}: {previous} / {original}")
            builtin_reverse[target] = original
    return {
        "keywords": _primary_map(profile, "keywords"),
        "soft_keywords": _primary_map(profile, "softKeywords"),
        "constants": _primary_map(profile, "constants"),
        "builtins": builtins,
        "methods": _primary_map(profile, "commonMethods"),
        "parameters": _primary_map(profile, "commonParameters"),
        "keyword_reverse": _reverse_map(profile, "keywords"),
        "soft_reverse": _reverse_map(profile, "softKeywords"),
        "constant_reverse": _reverse_map(profile, "constants"),
        "builtin_reverse": builtin_reverse,
        "method_reverse": _reverse_map(profile, "commonMethods"),
        "parameter_reverse": _reverse_map(profile, "commonParameters"),
    }


_LAST_PROFILE_INDEXES: tuple[dict, dict[str, dict]] | None = None


def _cached_profile_indexes(profile: dict) -> dict[str, dict]:
    global _LAST_PROFILE_INDEXES
    if _LAST_PROFILE_INDEXES is not None and _LAST_PROFILE_INDEXES[0] is profile:
        return _LAST_PROFILE_INDEXES[1]
    validate_profile(profile)
    indexes = _profile_indexes(profile)
    _LAST_PROFILE_INDEXES = (profile, indexes)
    return indexes


def load_extensions(
    directory: str | Path | Iterable[str | Path] | None = None,
) -> tuple[dict[str, str], dict[tuple[str, str], str], list[str]]:
    """확장팩의 정방향·역방향 API 번역표를 읽는다."""
    if directory is None:
        bundled = (
            PROJECT_EXTENSION_DIR
            if PROJECT_EXTENSION_DIR.is_dir()
            else INSTALLED_DATA_DIR / "ExtensionPacks"
        )
        directories = [bundled, USER_EXTENSION_DIR]
    else:
        directories = (
            [Path(directory)]
            if isinstance(directory, (str, Path))
            else [Path(item) for item in directory]
        )
    records: dict[str, tuple[dict, str, bool]] = {}
    loaded: list[str] = []
    for extension_dir in directories:
        if not extension_dir.exists():
            continue
        paths = sorted(
            (item for item in extension_dir.iterdir() if item.is_file() and item.suffix.lower() == ".json"),
            key=lambda item: item.name.casefold(),
        )
        for path in paths:
            try:
                pack = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ProfileError(f"확장팩을 읽을 수 없음: {path.name}: {exc}") from exc
            if not isinstance(pack, dict) or pack.get("schemaVersion") != 1:
                raise ProfileError(f"지원하지 않는 확장팩 schemaVersion: {path.name}")
            metadata = pack.get("pack")
            resolution = pack.get("resolution")
            modules = pack.get("modules")
            if not isinstance(metadata, dict) or not isinstance(modules, dict):
                raise ProfileError(f"확장팩 형식이 잘못됨: {path.name}")
            if not all(
                isinstance(metadata.get(field), str) and metadata[field]
                for field in ("id", "name", "version")
            ):
                raise ProfileError(f"확장팩 메타데이터가 잘못됨: {path.name}")
            allow_override = metadata.get("allowPersonalOverride")
            if not isinstance(allow_override, bool):
                raise ProfileError(f"allowPersonalOverride 형식이 잘못됨: {path.name}")
            if (
                not isinstance(resolution, dict)
                or resolution.get("translateByCanonicalPath") is not True
                or resolution.get("trackImportAliases") is not True
            ):
                raise ProfileError(f"지원하지 않는 확장팩 경로 정책: {path.name}")

            for tier in modules.values():
                if not isinstance(tier, dict):
                    raise ProfileError(f"확장팩 modules 형식이 잘못됨: {path.name}")
                for module in tier.values():
                    members = module.get("members") if isinstance(module, dict) else None
                    if not isinstance(members, dict):
                        raise ProfileError(f"확장팩 members 형식이 잘못됨: {path.name}")
                    for canonical, entry in members.items():
                        if not isinstance(canonical, str) or "." not in canonical or not isinstance(entry, dict):
                            raise ProfileError(f"잘못된 확장팩 항목: {path.name}: {canonical}")
                        primary = entry.get("primary")
                        aliases = entry.get("aliases")
                        if not isinstance(primary, str) or not primary:
                            raise ProfileError(f"빈 대표 번역어: {path.name}: {canonical}")
                        if not isinstance(aliases, list) or not all(
                            isinstance(alias, str) and alias for alias in aliases
                        ):
                            raise ProfileError(f"잘못된 aliases: {path.name}: {canonical}")
                        normalized = [unicodedata.normalize("NFC", value) for value in [primary, *aliases]]
                        if any(not value.isidentifier() for value in normalized):
                            raise ProfileError(f"식별자가 아닌 확장팩 번역어: {path.name}: {canonical}")
                        if len(normalized) != len(set(normalized)):
                            raise ProfileError(f"확장팩 항목 내부 중복: {path.name}: {canonical}")
                        previous = records.get(canonical)
                        if previous is not None and previous[0] != entry and not previous[2]:
                            raise ProfileError(f"확장팩 충돌: {canonical}: {previous[1]} / {path.name}")
                        records[canonical] = (entry, path.name, allow_override)
            loaded.append(path.name)

    forward: dict[str, str] = {}
    reverse: dict[tuple[str, str], str] = {}
    for canonical, (entry, owner, _) in records.items():
        primary = entry["primary"]
        forward[canonical] = primary
        parent, source_name = canonical.rsplit(".", 1)
        for target in [primary, *entry["aliases"]]:
            key = (parent, unicodedata.normalize("NFC", target))
            previous_source = reverse.get(key)
            if previous_source is not None and previous_source != source_name:
                raise ProfileError(f"확장팩 역방향 충돌: {owner}: {parent}.{target}")
            reverse[key] = source_name
    return forward, reverse, loaded


def _import_bindings(tree: ast.AST) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                binding = item.asname or item.name.split(".", 1)[0]
                bindings[binding] = item.name if item.asname else binding
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name == "*":
                    continue
                bindings[item.asname or item.name] = f"{node.module}.{item.name}"
    return bindings


def _scope_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    bound: set[str] = set()
    variables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
            variables.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
            variables.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            bound.update(item.asname or item.name.split(".", 1)[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            bound.update(item.asname or item.name for item in node.names if item.name != "*")
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
            variables.add(node.name)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            bound.add(node.name)
            variables.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bound.add(node.rest)
            variables.add(node.rest)
    return bound, variables


def _bound_names(tree: ast.AST) -> set[str]:
    return _scope_names(tree)[0]


def _variable_names(tree: ast.AST) -> set[str]:
    return _scope_names(tree)[1]


_IGNORED_TOKEN_TYPES = {
    tokenize.ENCODING,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.COMMENT,
    tokenize.ENDMARKER,
}


def _token_context(
    tokens: list[tokenize.TokenInfo],
    additionally_ignored: set[int] | None = None,
) -> tuple[dict[int, int], dict[int, int], dict[int, str], set[int]]:
    ignored = additionally_ignored or set()
    significant = [
        index
        for index, token in enumerate(tokens)
        if token.type not in _IGNORED_TOKEN_TYPES and index not in ignored
    ]
    previous = {
        index: significant[position - 1]
        for position, index in enumerate(significant)
        if position
    }
    following = {
        index: significant[position + 1]
        for position, index in enumerate(significant)
        if position + 1 < len(significant)
    }
    first_on_line: dict[int, str] = {}
    for index in significant:
        first_on_line.setdefault(tokens[index].start[0], tokens[index].string)

    call_arguments: set[int] = set()
    delimiters: list[tuple[str, bool]] = []
    for index in significant:
        token = tokens[index]
        if token.type == tokenize.NAME and delimiters and delimiters[-1] == ("(", True):
            call_arguments.add(index)
        if token.string in "([{":
            is_call = False
            if token.string == "(":
                prev_index = previous.get(index)
                if prev_index is not None:
                    prev = tokens[prev_index]
                    prev_prev_index = previous.get(prev_index)
                    prev_prev = tokens[prev_prev_index].string if prev_prev_index is not None else ""
                    is_call = (
                        (
                            prev.type == tokenize.NAME
                            and prev.string not in keyword.kwlist
                            and prev_prev not in {"def", "class"}
                        )
                        or prev.string in {")", "]"}
                    )
            delimiters.append((token.string, is_call))
        elif token.string in ")]}":
            if delimiters:
                delimiters.pop()
    return previous, following, first_on_line, call_arguments


def _attribute_canonical(
    tokens: list[tokenize.TokenInfo],
    index: int,
    previous_significant: dict[int, int],
    imports: dict[str, str],
) -> str | None:
    # ponytail: 정적 import 경로만 추적한다. 인스턴스 타입 번역이 필요해지면 AST 심볼 추론을 붙인다.
    chain = [index]
    cursor = index
    while True:
        dot_index = previous_significant.get(cursor)
        if dot_index is None or tokens[dot_index].string != ".":
            break
        name_index = previous_significant.get(dot_index)
        if name_index is None or tokens[name_index].type != tokenize.NAME:
            break
        chain.insert(0, name_index)
        cursor = name_index

    first = tokens[chain[0]].string
    base = imports.get(first)
    if base is None:
        return None
    if len(chain) == 1:
        return base
    return ".".join([base, *(tokens[item].string for item in chain[1:])])


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _mapped_syntax_location(
    original: str,
    transformed: str,
    mapping: list[int],
    error: SyntaxError,
) -> tuple[int, int]:
    if error.lineno is None or error.offset is None:
        return 0, 0
    transformed_offsets = _line_offsets(transformed)
    absolute = transformed_offsets[error.lineno - 1] + max(0, error.offset - 1)
    return _mapped_offset_location(original, mapping, absolute)


def _mapped_offset_location(
    original: str,
    mapping: list[int],
    absolute: int,
) -> tuple[int, int]:
    original_absolute = mapping[min(absolute, len(mapping) - 1)]
    original_offsets = _line_offsets(original)
    line = min(
        max(1, bisect.bisect_right(original_offsets, original_absolute)),
        max(1, len(original_offsets) - 1),
    )
    column = original_absolute - original_offsets[line - 1] + 1
    return line, column


def _fstring_parts(literal: str) -> tuple[str, str, str] | None:
    prefix_end = 0
    while prefix_end < len(literal) and literal[prefix_end] in "rRuUbBfF":
        prefix_end += 1
    if "f" not in literal[:prefix_end].lower() or prefix_end >= len(literal):
        return None
    if literal[prefix_end] not in {'"', "'"}:
        return None
    quote = literal[prefix_end : prefix_end + 3]
    if quote not in {'"""', "'''"}:
        quote = literal[prefix_end]
    if not literal.endswith(quote):
        return None
    body_start = prefix_end + len(quote)
    return literal[:body_start], literal[body_start : -len(quote)], quote


def _token_offset(offsets: list[int], position: tuple[int, int]) -> int:
    return offsets[position[0] - 1] + position[1]


def _field_expression_end(text: str, start: int) -> tuple[int, str | None]:
    fragment = text[start:]
    offsets = _line_offsets(fragment)
    delimiters: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(fragment).readline)
        for token in tokens:
            value = token.string
            position = start + _token_offset(offsets, token.start)
            if value in "([{":
                delimiters.append(value)
            elif value in ")]}":
                if value == "}" and not delimiters:
                    return position, None
                if delimiters:
                    delimiters.pop()
            elif not delimiters and value in {"!", ":", "="}:
                return position, value
    except (tokenize.TokenError, IndentationError):
        pass
    raise ConversionError("닫히지 않은 f-string 치환 필드")


def _collect_format_expressions(
    text: str,
    start: int,
    spans: list[tuple[int, int]],
) -> int:
    index = start
    while index < len(text):
        if text[index] == "}":
            return index
        if text.startswith("{{", index):
            index += 2
            continue
        if text[index] == "{":
            index = _collect_field_expressions(text, index, spans) + 1
            continue
        index += 1
    raise ConversionError("닫히지 않은 f-string 포맷 지정자")


def _collect_field_expressions(
    text: str,
    opening: int,
    spans: list[tuple[int, int]],
) -> int:
    expression_start = opening + 1
    expression_end, delimiter = _field_expression_end(text, expression_start)
    expression = text[expression_start:expression_end]
    leading = len(expression) - len(expression.lstrip())
    trailing = len(expression) - len(expression.rstrip())
    core_end = len(expression) - trailing if trailing else len(expression)
    if leading < core_end:
        spans.append((expression_start + leading, expression_start + core_end))
    if delimiter is None:
        return expression_end

    index = expression_end
    while index < len(text):
        if text[index] == "}":
            return index
        if text[index] == ":":
            return _collect_format_expressions(text, index + 1, spans)
        index += 1
    raise ConversionError("닫히지 않은 f-string 치환 필드")


def _fstring_expression_spans(literal: str) -> list[tuple[int, int]]:
    parts = _fstring_parts(literal)
    if parts is None:
        return []
    head, body, _ = parts
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(body):
        if body.startswith("{{", index) or body.startswith("}}", index):
            index += 2
            continue
        if body[index] == "{":
            index = _collect_field_expressions(body, index, spans) + 1
            continue
        index += 1
    return [(len(head) + start, len(head) + end) for start, end in spans]


def _rewrite_fstring_literal(literal: str, transform) -> str:
    replacements = [
        (start, end, transform(literal[start:end]))
        for start, end in _fstring_expression_spans(literal)
    ]
    return _apply_replacements(literal, replacements)


def _fstring_replacements(source: str, tokens: list[tokenize.TokenInfo], transform):
    offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        rewritten = _rewrite_fstring_literal(token.string, transform)
        if rewritten == token.string:
            continue
        start = _token_offset(offsets, token.start)
        end = _token_offset(offsets, token.end)
        replacements.append((start, end, rewritten))
    return replacements


def _mask_fstrings(source: str) -> str:
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []
    for token in tokens:
        if token.type != tokenize.STRING or _fstring_parts(token.string) is None:
            continue
        masked = '"""' + "\n" * token.string.count("\n") + '"""'
        replacements.append(
            (_token_offset(offsets, token.start), _token_offset(offsets, token.end), masked)
        )
    return _apply_replacements(source, replacements)


def _python_to_kpy(
    source: str,
    extension_primaries: dict[str, str],
    inherited_imports: dict[str, str],
    inherited_bound: set[str],
    inherited_variables: set[str],
    profile: dict,
    indexes: dict[str, dict],
    parse_context: bool = True,
) -> str:
    tree: ast.AST | None = None
    if parse_context:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            where = f"{exc.lineno}:{exc.offset}" if exc.lineno else "알 수 없는 위치"
            raise ConversionError(f"Python 문법 오류 ({where}): {exc.msg}") from exc

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        raise ConversionError(f"토큰 분석 오류: {exc}") from exc

    keywords = indexes["keywords"]
    soft_keywords = indexes["soft_keywords"]
    constants = indexes["constants"]
    builtins = indexes["builtins"]
    methods = indexes["methods"]
    parameters = indexes["parameters"]
    local_bound, local_variables = _scope_names(tree) if tree is not None else (set(), set())
    imports = (
        {**inherited_imports, **_import_bindings(tree)}
        if tree is not None
        else inherited_imports
    )
    bound = inherited_bound | local_bound
    variables = inherited_variables | local_variables
    previous_significant, next_significant, first_on_line, call_argument_context = (
        _token_context(tokens)
    )

    replacements: list[tuple[int, int, str]] = []
    line_offsets = _line_offsets(source)
    replacements.extend(
        _fstring_replacements(
            source,
            tokens,
            lambda expression: _python_to_kpy(
                expression,
                extension_primaries,
                imports,
                bound,
                variables,
                profile,
                indexes,
                False,
            ),
        )
    )

    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME:
            continue

        name = token.string
        replacement: str | None = None
        canonical = _attribute_canonical(tokens, index, previous_significant, imports)
        if canonical is not None:
            replacement = extension_primaries.get(canonical)

        prev_index = previous_significant.get(index)
        next_index = next_significant.get(index)
        prev_text = tokens[prev_index].string if prev_index is not None else ""
        next_text = tokens[next_index].string if next_index is not None else ""

        if replacement is None and name in keywords:
            replacement = keywords[name]
        elif replacement is None and name in constants:
            replacement = constants[name]
        elif replacement is None and name in soft_keywords:
            line_first = first_on_line.get(token.start[0])
            if name in {"match", "case"} and line_first == name:
                replacement = soft_keywords[name]
            elif name == "_" and line_first == "case":
                replacement = soft_keywords[name]
            elif name == "type" and name not in bound:
                replacement = soft_keywords[name]
        if replacement is None and prev_text == "." and name in methods:
            replacement = methods[name]
        if (
            replacement is None
            and name in parameters
            and next_text == "="
            and index in call_argument_context
        ):
            replacement = parameters[name]
        if replacement is None and name in builtins and name not in bound:
            replacement = builtins[name]

        output_name = replacement or name
        is_keyword_argument = next_text == "=" and index in call_argument_context
        if (
            name in variables
            and prev_text != "."
            and prev_text not in {"def", "class", "import", "from"}
            and not is_keyword_argument
        ):
            output_name = profile["syntax"]["variablePrefix"] + name

        if output_name != name:
            start = line_offsets[token.start[0] - 1] + token.start[1]
            end = line_offsets[token.end[0] - 1] + token.end[1]
            replacements.append((start, end, output_name))

    return _apply_replacements(source, replacements)


def python_to_kpy(
    source: str,
    extension_primaries: dict[str, str] | None = None,
    profile: dict | None = None,
) -> str:
    """표준 Python을 profile의 primary 값으로 변환한다."""
    active_profile = profile if profile is not None else embedded_gender_change()
    indexes = _cached_profile_indexes(active_profile)
    return _python_to_kpy(
        source,
        extension_primaries or {},
        {},
        set(),
        set(),
        active_profile,
        indexes,
    )


def _apply_replacements(source: str, replacements: list[tuple[int, int, str]]) -> str:
    return _apply_replacements_mapped(source, replacements)[0]


def _apply_replacements_mapped(
    source: str,
    replacements: list[tuple[int, int, str]],
    source_map: list[int] | None = None,
) -> tuple[str, list[int]]:
    """치환 결과와 각 출력 경계가 가리키는 원본 오프셋을 함께 만든다."""
    mapping = source_map or list(range(len(source) + 1))
    pieces: list[str] = []
    result_map: list[int] = []
    cursor = 0
    for start, end, text in sorted(replacements):
        if start < cursor:
            raise ConversionError("겹치는 내부 치환")
        pieces.append(source[cursor:start])
        result_map.extend(mapping[cursor:start])
        pieces.append(text)
        width = max(1, len(text))
        span = end - start
        result_map.extend(
            mapping[min(end, start + (offset * span // width))]
            for offset in range(len(text))
        )
        cursor = end
    pieces.append(source[cursor:])
    result_map.extend(mapping[cursor:len(source)])
    result_map.append(mapping[len(source)])
    return "".join(pieces), result_map


def _protect_variables(
    source: str,
    prefix: str,
    source_map: list[int] | None = None,
) -> tuple[str, dict[str, str], list[int]]:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        raise ConversionError(f"KPY 토큰 분석 오류: {exc}") from exc

    offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []
    variables: dict[str, str] = {}
    placeholder_index = 0
    for index, token in enumerate(tokens[:-1]):
        following = tokens[index + 1]
        if (
            token.string != prefix
            or following.type != tokenize.NAME
            or token.end != following.start
        ):
            continue
        placeholder = f"__PYKR_VARIABLE_{placeholder_index}__"
        while placeholder in source:
            placeholder_index += 1
            placeholder = f"__PYKR_VARIABLE_{placeholder_index}__"
        variables[placeholder] = following.string
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[following.end[0] - 1] + following.end[1]
        replacements.append((start, end, placeholder))
        placeholder_index += 1
    if source_map is None:
        return _apply_replacements(source, replacements), variables, []
    protected, mapped = _apply_replacements_mapped(source, replacements, source_map)
    return protected, variables, mapped


def _restore_variables(source: str, variables: dict[str, str]) -> str:
    if not variables:
        return source
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []
    for token in tokens:
        replacement = variables.get(token.string) if token.type == tokenize.NAME else None
        if replacement is None:
            continue
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        replacements.append((start, end, replacement))
    return _apply_replacements(source, replacements)


def _validate_required_prefix(
    original: str,
    source: str,
    source_map: list[int] | None,
    variable_names: set[str],
    variables: dict[str, str],
    prefix: str,
    translated_names: set[str],
) -> None:
    placeholders = set(variables)
    bare_variables = variable_names - placeholders
    protected_names = set(variables.values())
    if not bare_variables and not protected_names:
        return

    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    previous, following, _, call_arguments = _token_context(tokens)
    offsets = _line_offsets(source)
    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME:
            continue
        prev_index = previous.get(index)
        next_index = following.get(index)
        prev = tokens[prev_index] if prev_index is not None else None
        next_token = tokens[next_index] if next_index is not None else None
        prefixed = prev is not None and prev.string == prefix and prev.end == token.start
        keyword_argument = (
            next_token is not None
            and next_token.string == "="
            and index in call_arguments
        )
        if (
            prefixed
            or keyword_argument
            or (prev is not None and prev.string == ".")
            or token.string in translated_names
            or token.string not in bare_variables | protected_names
        ):
            continue
        absolute = _token_offset(offsets, token.start)
        if source_map is None:
            line, column = token.start
            column += 1
        else:
            line, column = _mapped_offset_location(original, source_map, absolute)
        raise ConversionError(
            f"사용자 변수 '{token.string}' 앞에 {prefix}가 필요함 ({line}:{column})"
        )


def _reverse_syntax(
    source: str,
    indexes: dict[str, dict],
    source_map: list[int] | None = None,
) -> tuple[str, list[int]]:
    """보호된 변수는 건드리지 않고 KPY 문법 토큰만 복원한다."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError) as exc:
        raise ConversionError(f"KPY 토큰 분석 오류: {exc}") from exc

    _, _, first_on_line, _ = _token_context(tokens)
    keyword_reverse = indexes["keyword_reverse"]
    soft_reverse = indexes["soft_reverse"]
    constant_reverse = indexes["constant_reverse"]
    offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []

    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME:
            continue
        replacement = keyword_reverse.get(token.string) or constant_reverse.get(token.string)
        soft_source = soft_reverse.get(token.string)
        if replacement is None and soft_source in {"match", "case"}:
            if first_on_line.get(token.start[0]) == token.string:
                replacement = soft_source
        elif replacement is None and soft_source == "_":
            line_first = first_on_line.get(token.start[0], "")
            if soft_reverse.get(line_first) == "case":
                replacement = "_"
        elif replacement is None and soft_source == "type":
            if first_on_line.get(token.start[0]) == token.string:
                replacement = "type"
        if replacement is None:
            continue
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        replacements.append((start, end, replacement))
    if source_map is None:
        return _apply_replacements(source, replacements), []
    return _apply_replacements_mapped(source, replacements, source_map)


def _kpy_import_bindings(
    tree: ast.AST,
    extension_reverse: dict[tuple[str, str], str],
) -> tuple[dict[str, str], dict[str, str]]:
    bindings: dict[str, str] = {}
    direct_replacements: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                binding = item.asname or item.name.split(".", 1)[0]
                bindings[binding] = item.name if item.asname else binding
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                if item.name == "*":
                    continue
                source_name = extension_reverse.get((node.module, item.name), item.name)
                binding = item.asname or item.name
                bindings[binding] = f"{node.module}.{source_name}"
                if item.asname is None and source_name != item.name:
                    direct_replacements[binding] = source_name
    return bindings, direct_replacements


def _reverse_extension_name(
    tokens: list[tokenize.TokenInfo],
    index: int,
    previous: dict[int, int],
    imports: dict[str, str],
    direct_imports: dict[str, str],
    extension_reverse: dict[tuple[str, str], str],
) -> str | None:
    chain = [index]
    cursor = index
    while True:
        dot_index = previous.get(cursor)
        if dot_index is None or tokens[dot_index].string != ".":
            break
        name_index = previous.get(dot_index)
        if name_index is None or tokens[name_index].type != tokenize.NAME:
            break
        chain.insert(0, name_index)
        cursor = name_index

    first = tokens[chain[0]].string
    parent = imports.get(first)
    if parent is None:
        return None
    if len(chain) == 1:
        return direct_imports.get(first)

    for name_index in chain[1:]:
        target_name = tokens[name_index].string
        source_name = extension_reverse.get((parent, target_name))
        if source_name is None:
            source_name = target_name
        if name_index == index and source_name != target_name:
            return source_name
        parent = f"{parent}.{source_name}"
    return None


def _kpy_import_context(
    source: str,
    profile: dict,
    indexes: dict[str, dict],
    extension_reverse: dict[tuple[str, str], str],
) -> tuple[dict[str, str], dict[str, str], set[str]]:
    if hasattr(tokenize, "FSTRING_START"):
        return {}, {}, set()
    scaffold = _mask_fstrings(source)
    protected, _, _ = _protect_variables(
        scaffold,
        profile["syntax"]["variablePrefix"],
    )
    try:
        intermediate, _ = _reverse_syntax(protected, indexes)
        tree = ast.parse(intermediate)
    except SyntaxError:
        return {}, {}, set()
    imports, direct_imports = _kpy_import_bindings(tree, extension_reverse)
    return imports, direct_imports, _scope_names(tree)[0]


def _kpy_to_python(
    source: str,
    extension_reverse: dict[tuple[str, str], str],
    inherited_imports: dict[str, str],
    inherited_direct_imports: dict[str, str],
    profile: dict,
    indexes: dict[str, dict],
    validate_prefix: bool,
    inherited_bound: set[str],
    parse_result: bool = True,
) -> str:
    original_source = source
    if hasattr(tokenize, "FSTRING_START"):
        fstring_replacements = []
    else:
        try:
            source_tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (tokenize.TokenError, IndentationError) as exc:
            raise ConversionError(f"KPY 토큰 분석 오류: {exc}") from exc
        fstring_replacements = _fstring_replacements(
            source,
            source_tokens,
            lambda expression: _kpy_to_python(
                expression,
                extension_reverse,
                inherited_imports,
                inherited_direct_imports,
                profile,
                indexes,
                validate_prefix,
                inherited_bound,
                False,
            ),
        )
    source = _apply_replacements(source, fstring_replacements)
    protected, variables, _ = _protect_variables(
        source,
        profile["syntax"]["variablePrefix"],
    )
    intermediate, _ = _reverse_syntax(protected, indexes)
    binding_tokens = {"for", "lambda", "as"}
    needs_tree = parse_result or any(
        token.string in binding_tokens or token.string == ":="
        for token in tokenize.generate_tokens(io.StringIO(intermediate).readline)
    )
    tree: ast.AST | None = None
    try:
        if needs_tree:
            tree = ast.parse(intermediate)
    except SyntaxError as exc:
        mapped_source, source_map = _apply_replacements_mapped(
            original_source,
            fstring_replacements,
        )
        mapped_protected, _, mapping = _protect_variables(
            mapped_source,
            profile["syntax"]["variablePrefix"],
            source_map,
        )
        mapped_intermediate, mapping = _reverse_syntax(
            mapped_protected,
            indexes,
            mapping,
        )
        if mapped_intermediate != intermediate:
            raise ConversionError("내부 위치 매핑 불일치") from exc
        line, column = _mapped_syntax_location(original_source, intermediate, mapping, exc)
        where = f"{line}:{column}" if line else "알 수 없는 위치"
        raise ConversionError(f"KPY 문법 오류 ({where}): {exc.msg}") from exc
    local_bound, local_variables = _scope_names(tree) if tree is not None else (set(), set())
    if validate_prefix and profile["syntax"]["variablePrefixMode"] == "required":
        _validate_required_prefix(
            original_source,
            original_source,
            None,
            local_variables,
            variables,
            profile["syntax"]["variablePrefix"],
            set(indexes["builtin_reverse"]),
        )

    tokens = list(tokenize.generate_tokens(io.StringIO(intermediate).readline))
    previous, following, _, call_arguments = _token_context(tokens)
    bound = inherited_bound | local_bound
    local_imports, local_direct_imports = (
        _kpy_import_bindings(tree, extension_reverse)
        if tree is not None
        else ({}, {})
    )
    imports = {**inherited_imports, **local_imports}
    direct_imports = {**inherited_direct_imports, **local_direct_imports}

    builtin_reverse = indexes["builtin_reverse"]
    method_reverse = indexes["method_reverse"]
    parameter_reverse = indexes["parameter_reverse"]
    offsets = _line_offsets(intermediate)
    replacements: list[tuple[int, int, str]] = []

    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME:
            continue
        prev_index = previous.get(index)
        next_index = following.get(index)
        prev_text = tokens[prev_index].string if prev_index is not None else ""
        next_text = tokens[next_index].string if next_index is not None else ""

        replacement = _reverse_extension_name(
            tokens,
            index,
            previous,
            imports,
            direct_imports,
            extension_reverse,
        )
        if replacement is None and prev_text == ".":
            replacement = method_reverse.get(token.string)
        if (
            replacement is None
            and next_text == "="
            and index in call_arguments
        ):
            replacement = parameter_reverse.get(token.string)
        if replacement is None and prev_text != "." and token.string not in bound:
            replacement = builtin_reverse.get(token.string)
        if replacement is None or replacement == token.string:
            continue
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        replacements.append((start, end, replacement))

    result = _restore_variables(_apply_replacements(intermediate, replacements), variables)
    if parse_result:
        try:
            ast.parse(result)
        except SyntaxError as exc:
            where = f"{exc.lineno}:{exc.offset}" if exc.lineno else "알 수 없는 위치"
            raise ConversionError(f"복원된 Python 문법 오류 ({where}): {exc.msg}") from exc
    return result


def kpy_to_python(
    source: str,
    extension_reverse: dict[tuple[str, str], str] | None = None,
    profile: dict | None = None,
    *,
    validate_prefix: bool = True,
) -> str:
    """KPY를 표준 Python으로 되돌린다."""
    extension_reverse = extension_reverse or {}
    active_profile = profile if profile is not None else embedded_gender_change()
    indexes = _cached_profile_indexes(active_profile)
    imports, direct_imports, bound = _kpy_import_context(
        source,
        active_profile,
        indexes,
        extension_reverse,
    )
    return _kpy_to_python(
        source,
        extension_reverse,
        imports,
        direct_imports,
        active_profile,
        indexes,
        validate_prefix,
        bound,
    )


def decode_source_with_encoding(data: bytes) -> tuple[str, str]:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        return data.decode(encoding), encoding
    except (SyntaxError, UnicodeError) as exc:
        raise ConversionError(f"파일 인코딩을 읽을 수 없음: {exc}") from exc


def decode_source(data: bytes) -> str:
    return decode_source_with_encoding(data)[0]


HTML = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PyKR 변환기</title>
<style>
:root { color-scheme: dark; font-family: Inter, Pretendard, system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: #101114; color: #f3f4f6; display: grid; place-items: center; }
main { width: min(920px, calc(100% - 32px)); margin: 32px auto; }
h1 { margin: 0 0 8px; font-size: clamp(28px, 5vw, 48px); }
.sub { color: #aeb3bd; margin: 0 0 24px; }
#drop { border: 2px dashed #596172; border-radius: 18px; padding: 52px 24px; text-align: center; cursor: pointer; background: #181b20; transition: .15s ease; }
#drop.over, #drop:hover, #drop:focus { border-color: #70e1b1; background: #19231f; outline: none; }
#drop strong { display: block; font-size: 20px; margin-bottom: 8px; }
input[type=file] { display: none; }
#status { min-height: 24px; color: #8ee7bf; }
#error { color: #ff9292; white-space: pre-wrap; }
.result { display: none; margin-top: 18px; }
.result.show { display: block; }
.toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 10px; }
button { border: 0; border-radius: 10px; padding: 10px 16px; font-weight: 700; cursor: pointer; background: #70e1b1; color: #092117; }
pre { max-height: 52vh; overflow: auto; margin: 0; padding: 18px; border-radius: 14px; background: #08090b; border: 1px solid #272b33; line-height: 1.55; tab-size: 4; }
small { color: #8d94a1; }
</style>
</head>
<body>
<main>
  <h1>PyKR</h1>
  <p class="sub">Python과 네 한국어 방언을 양방향으로 바꾼다. 사용자 변수에는 <code>?</code>가 붙는다.</p>
  <label id="drop" tabindex="0">
    <strong>.py 또는 .kpy 파일을 여기에 드롭</strong>
    <span>또는 눌러서 파일 선택</span>
    <input id="file" type="file" accept=".py,.kpy,text/x-python,text/plain">
  </label>
  <div id="status" aria-live="polite"></div>
  <div id="error" role="alert"></div>
  <section id="result" class="result">
    <div class="toolbar"><div><strong id="name"></strong><br><small id="packs"></small></div><button id="download">결과 다운로드</button></div>
    <pre><code id="preview"></code></pre>
  </section>
</main>
<script>
const drop = document.querySelector("#drop");
const fileInput = document.querySelector("#file");
const statusBox = document.querySelector("#status");
const errorBox = document.querySelector("#error");
const result = document.querySelector("#result");
const preview = document.querySelector("#preview");
const nameBox = document.querySelector("#name");
const packsBox = document.querySelector("#packs");
const downloadButton = document.querySelector("#download");
let converted = "";
let outputName = "";

async function convert(file) {
  errorBox.textContent = "";
  result.classList.remove("show");
  const lowerName = file ? file.name.toLowerCase() : "";
  if (!file || (!lowerName.endsWith(".py") && !lowerName.endsWith(".kpy"))) {
    errorBox.textContent = ".py 또는 .kpy 파일만 넣어줘.";
    return;
  }
  statusBox.textContent = "변환 중...";
  const query = new URLSearchParams({filename: file.name});
  try {
    const response = await fetch("/convert?" + query.toString(), {method: "POST", body: file});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "변환 실패");
    converted = data.content;
    outputName = data.filename;
    preview.textContent = converted;
    nameBox.textContent = outputName;
    downloadButton.textContent = outputName.endsWith(".kpy") ? ".kpy 다운로드" : ".py 다운로드";
    packsBox.textContent = data.extensionPacks.length ? "확장팩: " + data.extensionPacks.join(", ") : "읽은 확장팩 없음";
    result.classList.add("show");
    statusBox.textContent = "변환 완료";
  } catch (error) {
    statusBox.textContent = "";
    errorBox.textContent = error.message;
  }
}

for (const eventName of ["dragenter", "dragover"]) {
  drop.addEventListener(eventName, event => { event.preventDefault(); drop.classList.add("over"); });
}
for (const eventName of ["dragleave", "drop"]) {
  drop.addEventListener(eventName, event => { event.preventDefault(); drop.classList.remove("over"); });
}
drop.addEventListener("drop", event => convert(event.dataTransfer.files[0]));
drop.addEventListener("keydown", event => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => convert(fileInput.files[0]));
downloadButton.addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([converted], {type: "text/plain;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = outputName;
  link.click();
  URL.revokeObjectURL(url);
});
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "PyKR/0.1"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/":
            self._json(404, {"error": "없는 경로"})
            return
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/convert":
            self._json(404, {"error": "없는 경로"})
            return
        query = parse_qs(parsed.query)
        filename = query.get("filename", [""])[0]
        suffix = Path(filename).suffix.lower()
        if suffix not in {".py", ".kpy"}:
            self._json(400, {"error": ".py 또는 .kpy 파일만 변환할 수 있음"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_SOURCE_BYTES:
            self._json(400, {"error": "파일이 비었거나 5MB보다 큼"})
            return

        try:
            source = decode_source(self.rfile.read(length))
            extension_forward, extension_reverse, packs = load_extensions()
            if suffix == ".py":
                converted = python_to_kpy(source, extension_forward)
                output_suffix = ".kpy"
            else:
                converted = kpy_to_python(source, extension_reverse)
                output_suffix = ".py"
        except ConversionError as exc:
            self._json(400, {"error": str(exc)})
            return
        except Exception as exc:
            self._json(500, {"error": f"내부 오류: {exc}"})
            return

        self._json(
            200,
            {
                "filename": str(Path(filename).with_suffix(output_suffix).name),
                "content": converted,
                "extensionPacks": packs,
            },
        )

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[PyKR] {self.address_string()} - {fmt % args}")


def self_check() -> None:
    extension_forward, extension_reverse, packs = load_extensions(PROJECT_EXTENSION_DIR)
    source = (
        "import random\n"
        "for 숫자 in range(3):\n"
        "    print(random.randint(1, 3), end='!')  # print는 문자열\n"
        "값 = int(input())\n"
        "helper()\n"
        "문자 = 'range print random.randint'\n"
    )
    converted = python_to_kpy(source, extension_forward)
    restored = kpy_to_python(converted, extension_reverse)
    profile = embedded_gender_change()
    assert profile["profile"]["name"] == "Plain"
    assert "입력 random" in converted
    assert "반복 ?숫자 안쪽에 범위(3):" in converted
    assert "출력(random.무작위정수(1, 3), 끝값='!')" in converted
    assert "?값 = 정수(입력받기())" in converted
    assert "helper()" in converted
    assert "# print는 문자열" in converted
    assert "'range print random.randint'" in converted
    assert restored == source
    conflict = '퉤 = "Hello World"\nprint(퉤)\n'
    converted_conflict = python_to_kpy(conflict, extension_forward)
    assert converted_conflict == '?퉤 = "Hello World"\n출력(?퉤)\n'
    assert kpy_to_python(converted_conflict, extension_reverse) == conflict
    alias_example = '?퉤 = "Hello World"\n퉤(?퉤)\n'
    assert kpy_to_python(alias_example, extension_reverse) == conflict
    fstring_source = (
        "import random\n"
        "값 = 3\n"
        "폭 = 8\n"
        "문자 = f'{값!r:>{폭}} {random.randint(1, 값)} "
        "{[숫자 for 숫자 in range(값)]} {{literal}} {값=}'\n"
    )
    converted_fstring = python_to_kpy(fstring_source, extension_forward)
    assert "{?값!r:>{?폭}}" in converted_fstring
    assert "{random.무작위정수(1, ?값)}" in converted_fstring
    assert "{[?숫자 반복 ?숫자 안쪽에 범위(?값)]}" in converted_fstring
    assert kpy_to_python(converted_fstring, extension_reverse) == fstring_source
    kpy_fstring = '?연도 = 2026\n퉤(f"오늘은 {?연도}년")\n'
    assert kpy_to_python(kpy_fstring, extension_reverse) == (
        '연도 = 2026\nprint(f"오늘은 {연도}년")\n'
    )
    assert "OfficialExtensionPack.Json" in packs
    print("self-check: ok")


def serve(port: int = 0, open_browser: bool = True) -> None:
    USER_EXTENSION_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"PyKR UI: {url}")
    print(f"확장팩 폴더: {USER_EXTENSION_DIR}")
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Python과 KPY를 양방향으로 바꾸는 로컬 UI")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        serve(args.port, not args.no_browser)


if __name__ == "__main__":
    main()
