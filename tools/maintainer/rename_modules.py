#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""
``rename_modules.py`` -- codemod that rewrites module names.

Usage: rename_modules.py [--root DIR] [--table FILE] [--scope S[,S...]]
                         [--only N[,N...]] [--apply | --check | --survey]

The script reads a mapping table (``kaine/legacy_names.py`` by default) and
replaces tokens, paths and prose text according to that table.  It never spells
a concrete module name; every identifier, class name, key and prose string is
taken from the table at runtime.

Scope overview:

- prose          docstrings, comments, markdown prose and text strings.
- identifiers    class/function/variable names and dotted Python identifiers.
- keys           config keys, stream names, TOML keys and table headers.
- operator       CLI flags, env vars, compose/quadlet/dashboard wiring.
- persisted      file paths, database keys, persisted literals.

Exit codes:

- 0 success / dry-run finished.
- 1 ``--check`` found planned changes.
- 2 table validation error, unknown scope/name, or ``--apply`` blocked by a
  collision or move conflict.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import fnmatch
import importlib.util
import io
import os
import posixpath
import re
import subprocess
import sys
import tokenize
import types
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------------- #
# Public data types
# --------------------------------------------------------------------------- #


class TableError(Exception):
    """Raised when the mapping table fails validation."""


class RootError(Exception):
    """Raised when the repository root cannot be read by git."""


@dataclasses.dataclass(frozen=True)
class Change:
    path: str
    line: int
    scope: str
    rule: str
    name: str
    old: str
    new: str


@dataclasses.dataclass(frozen=True)
class Queued:
    path: str
    line: int
    name: str
    rule: str
    excerpt: str


@dataclasses.dataclass
class FileResult:
    new_text: str
    changes: list[Change]
    queued: list[Queued]
    kept: dict[str, int]
    collisions: list[tuple[str, str, str]]
    skipped: str | None


@dataclasses.dataclass
class Plan:
    scopes: tuple[str, ...]
    only: tuple[str, ...] | None
    moves: list[tuple[str, str, str]]
    results: dict[str, FileResult]
    collisions: list[tuple[str, str, str]]
    accepted: list[tuple[str, str, str]] = dataclasses.field(default_factory=list)
    table_modules: dict[str, dict] = dataclasses.field(default_factory=dict)
    table_developmental: dict[str, dict] = dataclasses.field(default_factory=dict)
    path_queued: list[Queued] = dataclasses.field(default_factory=list)


# --------------------------------------------------------------------------- #
# Table loading and validation
# --------------------------------------------------------------------------- #


def load_table(path: Path) -> types.ModuleType:
    """Load ``kaine/legacy_names.py`` and validate it."""
    spec = importlib.util.spec_from_file_location("legacy_names", path)
    if spec is None or spec.loader is None:
        raise TableError(f"cannot load table from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validate_table(module)
    return module


def _require_tuple_of_str(obj, name: str) -> None:
    if not isinstance(obj, tuple):
        raise TableError(f"{name} must be a tuple")
    for item in obj:
        if not isinstance(item, str):
            raise TableError(f"{name} items must be str")


def _require_tuple_of_2_str(obj, name: str) -> None:
    if not isinstance(obj, tuple):
        raise TableError(f"{name} must be a tuple")
    for item in obj:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
        ):
            raise TableError(f"{name} items must be (str, str)")


def _require_str_dict(obj, name: str) -> None:
    if not isinstance(obj, dict):
        raise TableError(f"{name} must be a dict")
    for key, value in obj.items():
        if not isinstance(key, str):
            raise TableError(f"{name} keys must be str")
        if not isinstance(value, str):
            raise TableError(f"{name} values must be str")


def _require_rule(rule: dict, where: str) -> None:
    action = rule.get("action")
    if action not in {"rename", "keep", "queue"}:
        raise TableError(f"{where}: action must be rename/keep/queue")
    if "pattern" in rule:
        try:
            re.compile(rule["pattern"])
        except re.error as exc:
            raise TableError(f"{where}: invalid pattern: {exc}") from None


def validate_table(table) -> None:
    """Validate a table object (module or SimpleNamespace) against the schema."""
    scopes = getattr(table, "SCOPES", None)
    if not isinstance(scopes, tuple) or set(scopes) != {
        "prose",
        "identifiers",
        "keys",
        "operator",
        "persisted",
    }:
        raise TableError("SCOPES must be exactly the five scope names")

    status = getattr(table, "SCOPE_STATUS", None)
    if not isinstance(status, dict) or set(status.keys()) != set(scopes):
        raise TableError("SCOPE_STATUS keys must match SCOPES")
    for value in status.values():
        if value not in {"pending", "done"}:
            raise TableError("SCOPE_STATUS values must be pending or done")

    modules = getattr(table, "MODULES", None)
    developmental = getattr(table, "DEVELOPMENTAL", None)
    if not isinstance(modules, dict) or not isinstance(developmental, dict):
        raise TableError("MODULES and DEVELOPMENTAL must be dicts")

    new_keys: set[str] = set()
    new_classes: set[str] = set()

    for source in (modules, developmental):
        for old_key, entry in source.items():
            if not isinstance(old_key, str):
                raise TableError("module keys must be strings")
            if not isinstance(entry, dict):
                raise TableError("module entries must be dicts")
            for field in ("old_class", "new_class", "new_key", "new_prose", "layer"):
                if field not in entry:
                    raise TableError(f"{old_key}: missing {field}")
            new_key = entry["new_key"]
            new_class = entry["new_class"]
            if new_key in new_keys:
                raise TableError(f"duplicate new_key {new_key}")
            if new_class in new_classes:
                raise TableError(f"duplicate new_class {new_class}")
            new_keys.add(new_key)
            new_classes.add(new_class)

    all_old = set(modules.keys()) | set(developmental.keys())
    all_new_keys = new_keys

    for old in all_old:
        if old in all_new_keys:
            raise TableError(f"old key {old!r} equals a new key")
        for new_key in all_new_keys:
            parts = new_key.lower().split("_")
            if old.lower() in parts:
                raise TableError(f"old key {old!r} appears in new key {new_key!r}")
        for new_class in new_classes:
            parts = _split_camel(new_class)
            if old.lower() in parts:
                raise TableError(f"old key {old!r} appears in new class {new_class!r}")

    guarded = getattr(table, "GUARDED", None)
    if not isinstance(guarded, dict):
        raise TableError("GUARDED must be a dict")
    for name, entry in guarded.items():
        if not isinstance(entry, dict):
            raise TableError(f"GUARDED[{name!r}] must be a dict")
        rules = entry.get("rules", [])
        if not isinstance(rules, list):
            raise TableError(f"GUARDED[{name!r}].rules must be a list")
        for rule in rules:
            _require_rule(rule, f"GUARDED[{name!r}]")
        default = entry.get("default")
        if default not in {"rename", "keep", "queue"}:
            raise TableError(f"GUARDED[{name!r}].default must be rename/keep/queue")

    resolutions = getattr(table, "RESOLUTIONS", None)
    if not isinstance(resolutions, list):
        raise TableError("RESOLUTIONS must be a list")
    for rule in resolutions:
        if "name" not in rule:
            raise TableError("RESOLUTIONS rule missing name")
        _require_rule(rule, f"RESOLUTIONS[{rule.get('name')}]")

    key_overrides = getattr(table, "KEY_OVERRIDES", None)
    if not isinstance(key_overrides, tuple):
        raise TableError("KEY_OVERRIDES must be a tuple")
    phrases = getattr(table, "PHRASES", None)
    if not isinstance(phrases, tuple):
        raise TableError("PHRASES must be a tuple")
    path_overrides = getattr(table, "PATH_OVERRIDES", None)
    if not isinstance(path_overrides, dict):
        raise TableError("PATH_OVERRIDES must be a dict")
    _require_str_dict(path_overrides, "PATH_OVERRIDES")
    persisted_exact = getattr(table, "PERSISTED_EXACT", None)
    if not isinstance(persisted_exact, dict):
        raise TableError("PERSISTED_EXACT must be a dict")
    _require_str_dict(persisted_exact, "PERSISTED_EXACT")

    operator_exact = getattr(table, "OPERATOR_EXACT", ())
    if not isinstance(operator_exact, tuple) or not all(
        isinstance(x, str) for x in operator_exact
    ):
        raise TableError("OPERATOR_EXACT must be a tuple of strings")

    for attr_name in (
        "REPO_TOP_DIRS",
        "UI_GLOBS",
        "MODULE_LIST_FILES",
        "EXCLUDED_GLOBS",
        "GUARD_NAMES",
        "SURVEY_UI_PREFIXES",
        "SURVEY_THIRD_PARTY_PREFIXES",
    ):
        obj = getattr(table, attr_name, None)
        _require_tuple_of_str(obj, attr_name)

    _require_tuple_of_2_str(getattr(table, "SURVEY_EXTRA", None), "SURVEY_EXTRA")

    excluded_toml = getattr(table, "EXCLUDED_TOML_KEYS", None)
    if not isinstance(excluded_toml, tuple):
        raise TableError("EXCLUDED_TOML_KEYS must be a tuple")
    for item in excluded_toml:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
        ):
            raise TableError("EXCLUDED_TOML_KEYS items must be (str, str)")

    accepted = getattr(table, "ACCEPTED_COLLISIONS", None)
    if not isinstance(accepted, list):
        raise TableError("ACCEPTED_COLLISIONS must be a list")
    for item in accepted:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
        ):
            raise TableError("ACCEPTED_COLLISIONS items must be (str, str)")

    for env_attr in ("ENV_VARS", "COMPOSE_VARS"):
        obj = getattr(table, env_attr, None)
        if not isinstance(obj, tuple):
            raise TableError(f"{env_attr} must be a tuple")
        for item in obj:
            if not isinstance(item, dict) or "old" not in item:
                raise TableError(f"{env_attr} items must be dicts with 'old'")


def _split_camel(name: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for ch in name:
        if ch.isupper():
            if current:
                parts.append("".join(current).lower())
                current = []
        current.append(ch)
    if current:
        parts.append("".join(current).lower())
    return parts


# --------------------------------------------------------------------------- #
# Name tables and compiled regex
# --------------------------------------------------------------------------- #


def _all_entries(table) -> dict[str, dict]:
    """Return merged MODULES + DEVELOPMENTAL, in table order."""
    merged: dict[str, dict] = {}
    for source in (getattr(table, "MODULES", {}), getattr(table, "DEVELOPMENTAL", {})):
        for key, value in source.items():
            merged[key] = value
    return merged


def _name_regex(table) -> tuple[re.Pattern[str], dict[int, tuple[str, bool]]]:
    """
    Build a single compiled regex for every old form.

    Returns the pattern and a mapping from group index to
    ``(old_key, is_plural)``.
    """
    entries = _all_entries(table)
    variants: list[tuple[str, str, bool]] = []
    for old_key, entry in entries.items():
        old_class = entry["old_class"]
        variants.append((old_key, old_key, False))
        variants.append((old_class, old_key, False))
        variants.append((old_key.upper(), old_key, False))
        plural_key = entry.get("old_plural")
        if plural_key:
            variants.append((plural_key, old_key, True))
            variants.append(
                (
                    plural_key[0].upper() + plural_key[1:],
                    old_key,
                    True,
                )
            )
            variants.append((plural_key.upper(), old_key, True))

    def sort_key(item: tuple[str, str, bool]) -> tuple[int, int]:
        text, _, plural = item
        return (-len(text), 0 if plural else 1)

    variants.sort(key=sort_key)

    parts: list[str] = []
    group_map: dict[int, tuple[str, bool]] = {}
    for idx, (text, old_key, plural) in enumerate(variants):
        lower = re.escape(text.lower())
        capital = re.escape(text[0].upper() + text[1:]) if text else ""
        upper = re.escape(text.upper())
        capital_alt = f"|(?<![A-Z]){capital}(?![a-z])" if capital != upper else ""
        part = (
            f"(?P<g{idx}>(?:(?<![A-Za-z]){lower}(?![a-z])"
            f"|(?<![A-Za-z]){upper}(?![A-Za-z])"
            f"{capital_alt}))"
        )
        parts.append(part)
        group_map[idx] = (old_key, plural)

    pattern = "(?:" + "|".join(parts) + ")"
    return re.compile(pattern), group_map


def _first_old_key_in(
    text: str, regex: re.Pattern[str], group_map: dict[int, tuple[str, bool]]
) -> str:
    """Return the old key of the first candidate match in ``text``, or ``""``."""
    m = regex.search(text)
    if not m:
        return ""
    gkey = _matched_group(m, group_map)
    return gkey[0] if gkey else ""


def _new_forms(entry: dict, plural: bool) -> dict[str, str]:
    """Derive all replacement forms from a table entry."""
    if plural:
        key = entry.get("new_plural", entry["new_key"])
        prose = entry.get("new_plural", entry["new_key"]).replace("_", " ")
        class_name = _plural_class(key)
    else:
        key = entry["new_key"]
        prose = entry["new_prose"]
        class_name = entry["new_class"]
    return {
        "class": class_name,
        "key": key,
        "upper": key.upper(),
        "kebab": key.replace("_", "-"),
        "lower_camel": class_name[0].lower() + class_name[1:] if class_name else key,
        "prose": prose,
    }


def _plural_class(key: str) -> str:
    """Best-effort plural class form from an underscore key."""
    return "".join(part[0].upper() + part[1:] for part in key.split("_") if part)


# --------------------------------------------------------------------------- #
# Context detection
# --------------------------------------------------------------------------- #


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            starts.append(idx + 1)
    return starts


def _offset(starts: list[int], line: int, col: int) -> int:
    return starts[line - 1] + col


def _file_kind(rel_path: str, text: str) -> str:
    lower = rel_path.lower()
    if lower.endswith(".py"):
        return "python"
    if lower.endswith(".toml"):
        return "toml"
    if lower.endswith(".md"):
        return "markdown"
    if lower.endswith((".sh", ".bash")):
        return "shell"
    if text.startswith(("#!/bin/bash", "#!/bin/sh", "#!/usr/bin/env bash", "#!/usr/bin/env sh")):
        return "shell"
    return "other"


def _is_prose_like(ctx: str | None) -> bool:
    return ctx in {
        "md_prose",
        "comment",
        "docstring",
        "toml_comment",
        "py_text",
        "toml_text",
    }


def _is_prose_compound(token: str, capabilities: frozenset[str]) -> bool:
    if not re.fullmatch(r"^[A-Za-z]+(?:[-/][A-Za-z]+)+$", token):
        return False
    if token in capabilities:
        return False
    for segment in re.split(r"[-/]", token):
        if not (
            re.fullmatch(r"^[a-z]+$", segment)
            or re.fullmatch(r"^[A-Z][a-z]+$", segment)
        ):
            return False
    return True


def _is_code_reference(text: str, start: int, end: int, ctx: str | None) -> bool:
    """Return True when a prose-context match is actually a code/config reference."""
    if ctx not in {"md_prose", "comment", "docstring", "toml_comment"}:
        return False

    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    rel_start = start - line_start
    rel_end = end - line_start

    if ctx in {"comment", "docstring", "toml_comment"}:
        # a) inline backtick span on the same line (`x` or ``x``)
        i = 0
        while i < len(line):
            if line[i] == "`":
                j = i
                while j < len(line) and line[j] == "`":
                    j += 1
                run = j - i
                close = line.find("`" * run, j)
                if close != -1:
                    if i + run <= rel_start and rel_end <= close:
                        return True
                    i = close + run
                    continue
                break
            i += 1

        # b) single- or double-quoted string with no whitespace in its content
        i = 0
        while i < len(line):
            ch = line[i]
            if ch in "'\"":
                j = i
                while j < len(line) and line[j] == ch:
                    j += 1
                run = j - i
                if run >= 3:
                    i = j
                    continue
                close = -1
                k = j
                while True:
                    k = line.find(ch, k)
                    if k == -1:
                        break
                    rlen = 1
                    while k + rlen < len(line) and line[k + rlen] == ch:
                        rlen += 1
                    if rlen == run and (k + run >= len(line) or line[k + run] != ch):
                        close = k
                        break
                    k += rlen
                if close != -1:
                    content_start = i + run
                    content_end = close
                    if content_start <= rel_start and rel_end <= content_end:
                        if not any(c.isspace() for c in line[content_start:content_end]):
                            return True
                    i = close + run
                    continue
            i += 1

    # c) bracketed reference, but not Markdown link text
    def _pair_close(open_idx: int) -> int | None:
        balance = 1
        for k in range(open_idx + 1, line_end):
            if text[k] == "[":
                balance += 1
            elif text[k] == "]":
                balance -= 1
                if balance == 0:
                    return k
        return None

    def _pair_open(close_idx: int) -> int | None:
        balance = 1
        for k in range(close_idx - 1, line_start - 1, -1):
            if text[k] == "]":
                balance += 1
            elif text[k] == "[":
                balance -= 1
                if balance == 0:
                    return k
        return None

    if start > line_start and text[start - 1] == "[":
        close = _pair_close(start - 1)
        if close is not None:
            if text[close + 1 : close + 2] == "(":
                return False
            return True

    if end < line_end and text[end] == "]":
        open_b = _pair_open(end)
        if open_b is not None:
            if text[end + 1 : end + 2] == "(":
                return False
            return True

    # d) dotted reference on the same line (e.g. embodiment.<adapter> or episodic_memory.replay)
    if end < line_end and text[end] == ".":
        if end + 1 < line_end and not text[end + 1].isspace():
            return True

    return False


def _context_intervals(rel_path: str, text: str) -> list[tuple[int, int, str]]:
    kind = _file_kind(rel_path, text)
    if kind == "python":
        return _python_contexts(text)
    if kind == "toml":
        return _toml_contexts(text)
    if kind == "markdown":
        return _markdown_contexts(text)
    if kind == "shell":
        return _shell_contexts(rel_path, text)
    return [(0, len(text), "other")]


def _python_contexts(text: str) -> list[tuple[int, int, str]]:
    intervals: list[tuple[int, int, str]] = []
    starts = _line_starts(text)

    fstring_start = getattr(tokenize, "FSTRING_START", None)
    fstring_end = getattr(tokenize, "FSTRING_END", None)

    readline = io.StringIO(text).readline
    try:
        tokens = list(tokenize.generate_tokens(readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []

    token_infos = []
    for tok in tokens:
        start = _offset(starts, tok.start[0], tok.start[1])
        end = _offset(starts, tok.end[0], tok.end[1])
        token_infos.append(
            {
                "type": tok.type,
                "string": tok.string,
                "start": start,
                "end": end,
            }
        )

    docstring_prev_ok = {
        tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING
    }
    skip_back = {tokenize.NL, tokenize.COMMENT}
    for idx, tok in enumerate(token_infos):
        if tok["type"] != tokenize.STRING:
            continue
        j = idx - 1
        while j >= 0 and token_infos[j]["type"] in skip_back:
            j -= 1
        prev_ok = j < 0 or token_infos[j]["type"] in docstring_prev_ok
        if not prev_ok:
            continue
        next_ok = False
        for nxt in token_infos[idx + 1 :]:
            if nxt["type"] in (tokenize.NL,):
                continue
            next_ok = nxt["type"] in (tokenize.NEWLINE, tokenize.ENDMARKER)
            break
        tok["_is_docstring"] = next_ok

    fstring_depth = 0
    fstring_base: str | None = None
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    for idx, tok in enumerate(token_infos):
        ttype = tok["type"]
        start, end = tok["start"], tok["end"]
        if ttype == fstring_start:
            if fstring_depth == 0:
                contains_space = False
                nested = 1
                for inner in token_infos[idx + 1 :]:
                    if inner["type"] == fstring_start:
                        nested += 1
                    elif inner["type"] == fstring_end:
                        nested -= 1
                        if nested == 0:
                            break
                    elif (
                        inner["type"] == fstring_middle
                        and nested == 1
                        and " " in inner["string"]
                    ):
                        contains_space = True
                fstring_base = "py_text" if contains_space else "py_string"
            intervals.append((start, end, fstring_base))
            fstring_depth += 1
            continue
        if ttype == fstring_end:
            if fstring_base:
                intervals.append((start, end, fstring_base))
            fstring_depth = max(0, fstring_depth - 1)
            if fstring_depth == 0:
                fstring_base = None
            continue
        if fstring_depth > 0 and fstring_base:
            if ttype in (tokenize.NAME, tokenize.STRING, tokenize.COMMENT):
                ctx = _python_token_context(tok, fstring_base)
                intervals.append((start, end, ctx))
                continue
            intervals.append((start, end, fstring_base))
            continue
        if ttype in (tokenize.NAME, tokenize.STRING, tokenize.COMMENT):
            ctx = _python_token_context(tok, None)
            intervals.append((start, end, ctx))
            continue
    return intervals


def _python_token_context(tok: dict, inside_fstring: str | None) -> str:
    ttype = tok["type"]
    if ttype == tokenize.NAME:
        return "py_name"
    if ttype == tokenize.COMMENT:
        return "comment"
    if ttype == tokenize.STRING:
        if tok.get("_is_docstring"):
            return "docstring"
        if " " in tok["string"]:
            return "py_text"
        return "py_string"
    if ttype == getattr(tokenize, "STRING", None):
        if " " in tok["string"]:
            return "py_text"
        return "py_string"
    return inside_fstring or "other"


def _python_token_analysis(text: str) -> list[dict]:
    """
    Return token records for the file.
    """
    starts = _line_starts(text)

    readline = io.StringIO(text).readline
    try:
        tokens = list(tokenize.generate_tokens(readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []

    token_infos: list[dict] = []
    for tok in tokens:
        start = _offset(starts, tok.start[0], tok.start[1])
        end = _offset(starts, tok.end[0], tok.end[1])
        token_infos.append(
            {
                "type": tok.type,
                "string": tok.string,
                "start": start,
                "end": end,
            }
        )

    return token_infos


def _sequence_imports(
    tokens: list[dict], sequence_old_class: str
) -> tuple[bool, set[tuple[int, int]]]:
    """Find whether ``Sequence`` is imported and where the old class is imported."""
    bound = False
    kaine_imports: set[tuple[int, int]] = set()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok["type"] == tokenize.NAME and tok["string"] == "from":
            module_parts: list[str] = []
            j = i + 1
            while j < len(tokens) and not (
                tokens[j]["type"] == tokenize.NAME and tokens[j]["string"] == "import"
            ):
                module_parts.append(tokens[j]["string"])
                j += 1
            module_name = "".join(module_parts)
            if j < len(tokens):
                j += 1
                imported: list[int] = []
                while j < len(tokens) and tokens[j]["type"] not in (
                    tokenize.NEWLINE,
                    tokenize.ENDMARKER,
                ):
                    if tokens[j]["type"] == tokenize.NAME:
                        imported.append(j)
                    j += 1
                for idx in imported:
                    name_tok = tokens[idx]
                    if name_tok["string"] == "Sequence" and (
                        module_name.startswith("typing")
                        or module_name.startswith("collections")
                    ):
                        bound = True
                    if name_tok["string"] == sequence_old_class and module_name.startswith(
                        "kaine"
                    ):
                        kaine_imports.add((name_tok["start"], name_tok["end"]))
            i = j
            continue
        i += 1
    return bound, kaine_imports


def _sequence_class_defs(
    tokens: list[dict], sequence_old_class: str
) -> set[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for idx, tok in enumerate(tokens):
        if tok["type"] == tokenize.NAME and tok["string"] == "class":
            nxt = tokens[idx + 1] if idx + 1 < len(tokens) else None
            if nxt and nxt["type"] == tokenize.NAME and nxt["string"] == sequence_old_class:
                result.add((nxt["start"], nxt["end"]))
    return result


def _aligned_name_token(
    tokens: list[dict], start: int, end: int
) -> dict | None:
    for tok in tokens:
        if tok["type"] == tokenize.NAME and tok["start"] == start and tok["end"] == end:
            return tok
    return None


def _toml_contexts(text: str) -> list[tuple[int, int, str]]:
    intervals: list[tuple[int, int, str]] = []
    lines = text.split("\n")
    starts = _line_starts(text)
    multiline = False
    ml_kind = ""
    ml_quote = ""
    array_depth = 0

    def add(start: int, end: int, ctx: str) -> None:
        intervals.append((start, end, ctx))

    def ctx_for(has_space) -> str:
        return "toml_text" if has_space else "toml_string"

    def scan_value(line: str, line_start: int, line_end: int, start: int, depth: int) -> int:
        i = start
        in_string = False
        quote = ""
        string_start = 0
        is_literal = False

        while i < len(line):
            ch = line[i]
            if not in_string:
                if ch == "#":
                    add(line_start + i, line_end, "toml_comment")
                    break
                if ch == "[":
                    depth += 1
                    i += 1
                    continue
                if ch == "]":
                    depth = max(0, depth - 1)
                    i += 1
                    continue
                if ch in "\"'":
                    if line.startswith('"""', i):
                        quote = '"""'
                        is_literal = False
                        q_len = 3
                    elif line.startswith("'''", i):
                        quote = "'''"
                        is_literal = True
                        q_len = 3
                    elif ch == '"':
                        quote = '"'
                        is_literal = False
                        q_len = 1
                    else:
                        quote = "'"
                        is_literal = True
                        q_len = 1
                    in_string = True
                    string_start = i
                    i += q_len
                    continue
                i += 1
                continue

            if quote in ('"""', "'''"):
                close = line.find(quote, i)
                if close == -1:
                    add(line_start + string_start, line_end, ctx_for(" " in line[i:]))
                    break
                add(line_start + string_start, line_start + close + 3, ctx_for(" " in line[i:close]))
                i = close + 3
                in_string = False
                continue

            if is_literal:
                close = line.find(quote, i)
                if close == -1:
                    add(line_start + string_start, line_end, ctx_for(" " in line[i:]))
                    break
                add(line_start + string_start, line_start + close + 1, ctx_for(" " in line[i:close]))
                i = close + 1
                in_string = False
                continue

            rel_end = _find_quote_end(line[i:], quote)
            close_abs = i + rel_end
            add(line_start + string_start, line_start + close_abs, ctx_for(" " in line[i:close_abs - 1]))
            i = close_abs
            in_string = False
            continue

        return depth

    for lno, raw_line in enumerate(lines, start=1):
        line_start = starts[lno - 1]
        line_end = line_start + len(raw_line)

        if multiline:
            close_idx = raw_line.find(ml_quote)
            if close_idx != -1:
                close_abs = line_start + close_idx + len(ml_quote)
                add(line_start, close_abs, "toml_text" if ml_kind == "text" else "toml_string")
                multiline = False
                comment_pos = raw_line.find("#", close_idx + len(ml_quote))
                if comment_pos != -1:
                    add(line_start + comment_pos, line_end, "toml_comment")
            else:
                add(line_start, line_end, "toml_text" if ml_kind == "text" else "toml_string")
            continue

        stripped = raw_line.lstrip()

        if array_depth > 0:
            array_depth = scan_value(raw_line, line_start, line_end, 0, array_depth)
            continue

        if stripped.startswith("[") and stripped.endswith("]"):
            bracket_start = line_start + raw_line.index("[")
            add(bracket_start, line_end, "toml_header")
            continue

        eq_pos = _find_unquoted_equal(raw_line)
        if eq_pos != -1:
            key_end = line_start + eq_pos
            add(line_start, key_end, "toml_key")
            value_start = line_start + eq_pos + 1
            value = raw_line[eq_pos + 1 :]
            voff = value_start
            s = value.lstrip()
            prefix = value[: len(value) - len(s)]
            voff += len(prefix)
            if s.startswith('"""') or s.startswith("'''"):
                quote = s[:3]
                close = s[3:].find(quote)
                if close == -1:
                    multiline = True
                    ml_quote = quote
                    ml_kind = "text" if " " in s else "string"
                    add(voff, line_end, "toml_text" if ml_kind == "text" else "toml_string")
                else:
                    close_abs = voff + 3 + close + 3
                    has_space = " " in s[: close + 3]
                    add(voff, min(close_abs, line_end), ctx_for(has_space))
                    comment_pos = raw_line.find("#", eq_pos + 1 + close + 6)
                    if comment_pos != -1:
                        add(line_start + comment_pos, line_end, "toml_comment")
            elif s.startswith('"') or s.startswith("'"):
                quote = s[0]
                end_idx = _find_quote_end(s, quote)
                has_space = " " in s[:end_idx]
                add(voff, voff + end_idx, ctx_for(has_space))
                comment_pos = raw_line.find("#", eq_pos + 1 + end_idx)
                if comment_pos != -1:
                    add(line_start + comment_pos, line_end, "toml_comment")
            else:
                array_depth = scan_value(raw_line, line_start, line_end, eq_pos + 1, array_depth)
            continue

        if stripped.startswith("#"):
            hash_pos = line_start + raw_line.index("#")
            add(hash_pos, line_end, "toml_comment")

    return intervals


def _find_unquoted_equal(line: str) -> int:
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "=" and not in_single and not in_double:
            return idx
    return -1


def _find_quote_end(s: str, quote: str) -> int:
    escaped = False
    for idx, ch in enumerate(s[1:], start=1):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == quote:
            return idx + 1
    return len(s)


def _markdown_contexts(text: str) -> list[tuple[int, int, str]]:
    intervals: list[tuple[int, int, str]] = []
    fence_re = re.compile(r"^( {0,3})(`{3,}|~{3,})([^\n]*)\n?", re.MULTILINE)
    pos = 0
    while True:
        m = fence_re.search(text, pos)
        if not m:
            break
        fence_char = m.group(2)[0]
        fence_len = len(m.group(2))
        info = m.group(3).strip().split()[0] if m.group(3).strip() else ""
        start = m.start()
        close_re = re.compile(
            rf"^(?: {{0,3}})({re.escape(fence_char)}{{{fence_len},}})\s*\n?$",
            re.MULTILINE,
        )
        close = close_re.search(text, m.end())
        if not close:
            end = len(text)
        else:
            end = close.end()
        ctx = "shell" if info in {"sh", "bash", "shell", "console", "zsh"} else "md_code"
        intervals.append((start, end, ctx))
        pos = end

    inline_re = re.compile(r"`+")
    for m in inline_re.finditer(text):
        start = m.start()
        end = m.end()
        ticks = m.group(0)
        inside = any(a <= start < b for a, b, _ in intervals)
        if inside:
            continue
        close = re.search(re.escape(ticks), text[end:])
        if not close:
            continue
        span_end = end + close.end()
        if not any(a <= start < b for a, b, _ in intervals):
            intervals.append((start, span_end, "md_code"))

    intervals.sort()
    result: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end, ctx in intervals:
        if start > cursor:
            result.append((cursor, start, "md_prose"))
        result.append((start, end, ctx))
        cursor = max(cursor, end)
    if cursor < len(text):
        result.append((cursor, len(text), "md_prose"))
    return result


def _shell_contexts(rel_path: str, text: str) -> list[tuple[int, int, str]]:
    lower = rel_path.lower()
    if lower.endswith((".sh", ".bash")):
        return [(0, len(text), "shell")]
    base = os.path.basename(lower)
    if base.startswith("dockerfile"):
        intervals = []
        for m in re.finditer(r"^ExecStart=.*$", text, re.MULTILINE):
            intervals.append((m.start(), m.end(), "shell"))
        return intervals if intervals else [(0, len(text), "other")]
    if "quadlet/" in lower.replace("\\", "/"):
        intervals = []
        for m in re.finditer(r"^ExecStart=.*$", text, re.MULTILINE):
            intervals.append((m.start(), m.end(), "shell"))
        return intervals if intervals else [(0, len(text), "other")]
    return [(0, len(text), "other")]


# --------------------------------------------------------------------------- #
# Matching helpers
# --------------------------------------------------------------------------- #


def _context_at(offset: int, intervals: list[tuple[int, int, str]]) -> str | None:
    for start, end, ctx in intervals:
        if offset < start:
            return None
        if offset < end:
            return ctx
    return None


def _same_context(start: int, end: int, intervals: list[tuple[int, int, str]]) -> bool:
    ctx = _context_at(start, intervals)
    if ctx is None:
        return False
    for a, b, c in intervals:
        if b <= start or a >= end:
            continue
        if c != ctx:
            return False
    return True


def _blocked(start: int, end: int, blocked: list[tuple[int, int]]) -> bool:
    for a, b in blocked:
        if b <= start or a >= end:
            continue
        return True
    return False


def _expand_word(text: str, start: int, end: int) -> tuple[int, int]:
    left = start
    while left > 0 and _is_word_char(text[left - 1]):
        left -= 1
    right = end
    while right < len(text) and _is_word_char(text[right]):
        right += 1
    return left, right


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _expand_token(text: str, start: int, end: int) -> tuple[int, int]:
    left = start
    while left > 0 and _is_token_char(text[left - 1]):
        left -= 1
    right = end
    while right < len(text) and _is_token_char(text[right]):
        right += 1
    if right > left and text[right - 1] == ".":
        right -= 1
    return left, right


def _is_token_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_.-/"


def _classify_shape(text: str, start: int, end: int) -> tuple[str, int, int, int, int]:
    w_start, w_end = _expand_word(text, start, end)
    t_start, t_end = _expand_token(text, start, end)
    matched = text[start:end]
    W = text[w_start:w_end]

    is_bare = (
        t_start == w_start
        and t_end == w_end
        and (W == matched or W == matched + "'s" or W == matched + "’s")
    )
    is_segment = (
        not is_bare and w_start == start and w_end == end and W == matched
    )
    is_camel_lower = (
        matched
        and matched[0].islower()
        and w_start == start
        and any(ch.isupper() for ch in W)
    )
    if is_bare:
        shape = "bare"
    elif is_segment:
        shape = "segment"
    elif is_camel_lower:
        shape = "camel_lower"
    else:
        shape = "component"
    return shape, w_start, w_end, t_start, t_end


def _line_number(starts: list[int], offset: int) -> int:
    lo, hi = 0, len(starts)
    while lo < hi:
        mid = (lo + hi) // 2
        if starts[mid] <= offset:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _line_bounds(text: str, starts: list[int], offset: int) -> tuple[int, int]:
    line_no = _line_number(starts, offset)
    line_start = starts[line_no - 1]
    line_end = text.find("\n", line_start)
    if line_end == -1:
        line_end = len(text)
    return line_start, line_end


def _excerpt(text: str, starts: list[int], offset: int) -> str:
    line_no = _line_number(starts, offset)
    if line_no <= len(starts):
        begin = starts[line_no - 1]
        end = text.find("\n", begin)
        if end == -1:
            end = len(text)
        line = text[begin:end].strip()
    else:
        line = ""
    if len(line) > 120:
        line = line[:120]
    return line


# --------------------------------------------------------------------------- #
# Scope resolution
# --------------------------------------------------------------------------- #


def _env_var_set(table) -> set[str]:
    result: set[str] = set()
    for item in getattr(table, "ENV_VARS", ()):
        if isinstance(item, dict):
            result.add(item.get("old", ""))
    for item in getattr(table, "COMPOSE_VARS", ()):
        if isinstance(item, dict):
            result.add(item.get("old", ""))
    return result - {""}


def _repo_top_prefixes(table) -> tuple[str, ...]:
    dirs = getattr(table, "REPO_TOP_DIRS", ())
    return tuple(f"{d}/" for d in dirs)


def _link_target(rel_path: str, T: str, table, *, in_link: bool = False) -> str | None:
    """Resolve a markdown link target to a repo-relative path if it names a .md file, or a directory (ends in /) when ``in_link`` says the term is a Markdown link target."""
    target = T.rsplit("#", 1)[0]
    if not (target.endswith(".md") or (in_link and target.endswith("/"))):
        return None
    top_dirs = set(getattr(table, "REPO_TOP_DIRS", ()))
    parts = target.split("/")
    if parts and parts[0] in top_dirs:
        resolved = target
    else:
        base_dir = posixpath.dirname(rel_path.replace("\\", "/"))
        joined = posixpath.join(base_dir, target)
        resolved = posixpath.normpath(joined)
    if resolved.startswith(".."):
        return None
    return resolved


def _in_markdown_link_target(text: str, start: int) -> bool:
    """True when the term containing ``start`` directly follows ``](``, the start of a Markdown link target."""
    pos = start
    while pos > 0 and _is_token_char(text[pos - 1]):
        pos -= 1
    return text[pos - 2:pos] == "]("


def _in_pip_extra(text: str, start: int, end: int) -> bool:
    """Return True when ``text[start:end]`` lies inside a ``kaine[...]`` pip extra."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    rel_start = start - line_start
    rel_end = end - line_start
    for m in re.finditer(r"kaine\[[^\]\n]*\]", line):
        if m.start() <= rel_start and m.end() >= rel_end:
            return True
    return False


def _is_dotted_python_path(term: str) -> bool:
    """True for a dotted Python path into this repository, e.g. kaine.modules.x.y."""
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", term
    ):
        return False
    return term.startswith("kaine.") or term.startswith("tests.")


def _enclosing_string_content(
    text: str, offset: int, ctx: str | None, tokens: list[dict]
) -> str | None:
    """The literal content of the Python or TOML string that contains ``offset``."""
    if ctx in {"py_string", "py_text"}:
        for tok in tokens:
            if (
                tok.get("type") == tokenize.STRING
                and tok.get("start", 0) <= offset < tok.get("end", 0)
            ):
                try:
                    value = ast.literal_eval(tok.get("string", ""))
                except Exception:
                    return None
                if isinstance(value, str):
                    return value
                return None
        return None
    if ctx in {"toml_string", "toml_text"}:
        line_start = text.rfind("\n", 0, offset) + 1
        line_end = text.find("\n", offset)
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end]
        pos_in_line = offset - line_start
        q_single = line.rfind("'", 0, pos_in_line)
        q_double = line.rfind('"', 0, pos_in_line)
        quote = max(q_single, q_double)
        if quote == -1:
            return None
        quote_char = line[quote]
        end_quote = line.find(quote_char, pos_in_line)
        if end_quote == -1:
            return None
        return line[quote + 1:end_quote]
    return None


def _name_token_at(tokens: list[dict], offset: int) -> str | None:
    """The NAME token string that contains ``offset``, or None."""
    for tok in tokens:
        if (
            tok.get("type") == tokenize.NAME
            and tok.get("start", 0) <= offset < tok.get("end", 0)
        ):
            return tok.get("string")
    return None


def _in_repo_dotted_chain(tokens: list[dict], offset: int) -> bool:
    """Return True when ``offset`` is inside a dotted NAME chain rooted at kaine or tests."""
    for i, tok in enumerate(tokens):
        if (
            tok.get("type") == tokenize.NAME
            and tok.get("start", 0) <= offset < tok.get("end", 0)
        ):
            break
    else:
        return False

    dot_count = 0
    while (
        i >= 2
        and tokens[i - 1].get("type") == tokenize.OP
        and tokens[i - 1].get("string") == "."
        and tokens[i - 2].get("type") == tokenize.NAME
    ):
        i -= 2
        dot_count += 1

    return tokens[i].get("string") in {"kaine", "tests"} and dot_count > 0


def _file_chain_path(tokens: list[dict], start: int, rel_path: str, parts: list[str]) -> str | None:
    """The repository path a `__file__`-relative `/` chain points at, or None."""
    from pathlib import PurePosixPath

    idx = None
    for i, tok in enumerate(tokens):
        if tok.get("start", 0) <= start < tok.get("end", 0):
            idx = i
            break
    if idx is None:
        return None

    file_idx = None
    for i in range(idx, -1, -1):
        tok = tokens[i]
        if tok.get("type") == tokenize.NAME and tok.get("string") == "__file__":
            file_idx = i
            break
        if tok.get("type") == tokenize.NEWLINE:
            break
    if file_idx is None:
        return None

    levels = 0
    i = file_idx + 1
    while i < idx:
        tok = tokens[i]
        if tok.get("type") == tokenize.NAME:
            name = tok.get("string", "")
            if name == "parent":
                levels += 1
                i += 1
                continue
            if name == "parents":
                i += 1
                if i < idx and tokens[i].get("string") == "[":
                    i += 1
                    if i < idx and tokens[i].get("type") == tokenize.NUMBER:
                        try:
                            n = int(tokens[i].get("string", "0"))
                        except ValueError:
                            return None
                        levels += n + 1
                        i += 1
                        if i < idx and tokens[i].get("string") == "]":
                            i += 1
                            continue
                return None
            i += 1
            continue
        if tok.get("type") == tokenize.OP and tok.get("string") == "/":
            break
        i += 1

    if levels < 1:
        return None

    try:
        base = PurePosixPath(rel_path).parents[levels - 1]
    except IndexError:
        return None

    joined = base.joinpath(*parts)
    import posixpath

    normalized = posixpath.normpath(joined.as_posix())
    if normalized.startswith("..") or normalized.startswith("/"):
        return None
    return normalized


def _statement_uses_file(tokens: list[dict], start: int) -> bool:
    """Return True if the logical statement uses ``__file__``."""
    idx = None
    for i, tok in enumerate(tokens):
        if tok.get("start", 0) <= start < tok.get("end", 0):
            idx = i
            break
    if idx is None:
        return False
    for i in range(idx, -1, -1):
        tok = tokens[i]
        if tok.get("type") == tokenize.NAME and tok.get("string") == "__file__":
            return True
        if tok.get("type") == tokenize.NEWLINE:
            break
    return False


def _ui_wire_name(text: str, start: int, end: int) -> bool:
    """True when a UI-file match is a bus wire name: a dotted name in quotes, or a source comparison."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    match_start = start - line_start
    match_end = end - line_start
    for quote in ('"', "'", "`"):
        open_quote = -1
        for pos in range(match_start - 1, -1, -1):
            if line[pos] == quote:
                open_quote = pos
                break
        if open_quote == -1:
            continue
        close_quote = line.find(quote, match_end)
        if close_quote == -1:
            continue
        literal = line[open_quote + 1 : close_quote]
        if re.fullmatch(r"[A-Za-z_]+(?:\.[A-Za-z_*]+)+", literal):
            return True
        before = line[:open_quote]
        if re.search(r"source\s*[!=]==?\s*$", before):
            return True
    return False


def _assign_scope(
    rel_path: str,
    ctx: str | None,
    text: str,
    start: int,
    end: int,
    W: str,
    T: str,
    shape: str,
    toml_table: str | None,
    tokens: list[dict],
    table,
    capabilities: frozenset[str] = frozenset(),
) -> str:
    """Assign a scope to a candidate match using the rules from the spec."""
    lower_path = rel_path.lower().replace("\\", "/")

    if ctx in {"py_string", "py_text", "toml_string", "toml_text"}:
        if re.fullmatch(r"[\w./-]*\.(?:html|js|css|jinja|j2|py)", T):
            return "identifiers"
        full_content = _enclosing_string_content(text, start, ctx, tokens)
        if full_content is not None:
            persisted = getattr(table, "PERSISTED_EXACT", {})
            if full_content in persisted:
                return "persisted"
            operator_exact = getattr(table, "OPERATOR_EXACT", ())
            if full_content in operator_exact:
                return "operator"
            event_types = getattr(table, "EVENT_TYPES", ())
            for event_type in event_types:
                if full_content == event_type["old"]:
                    return "keys"
        if ctx in {"py_string", "py_text"} and _names_python_symbol(tokens, start):
            return "identifiers"
        if ctx.startswith("py"):
            if _operand_of_div(tokens, start, end):
                parts = _div_chain_strings(tokens, start)
                top_dirs = getattr(table, "REPO_TOP_DIRS", ())
                if parts and parts[0] in top_dirs:
                    return _path_move_scope("/".join(parts))
                if _statement_uses_file(tokens, start):
                    resolved = _file_chain_path(tokens, start, rel_path, parts)
                    return _path_move_scope(resolved) if resolved else "identifiers"
                return "persisted"
        if ("/" in T) or any(
            T.endswith(ext)
            for ext in (
                ".json",
                ".jsonl",
                ".db",
                ".log",
                ".gguf",
                ".ckpt",
                ".pt",
                ".npz",
                ".sqlite",
            )
        ):
            first_seg = T.split("/")[0]
            if first_seg not in getattr(table, "REPO_TOP_DIRS", ()):

                return "persisted"

    env_vars = _env_var_set(table)
    if re.fullmatch(r"^[A-Z][A-Z0-9_]*$", T) and (
        T.startswith("KAINE_") or T in env_vars
    ):
        return "operator"
    if T.startswith("--"):
        return "operator"
    if lower_path.startswith("quadlet/") or lower_path.startswith("compose/"):
        return "operator"
    if re.fullmatch(r"[\w./-]*\.(?:html|js|css|jinja|j2)", T):
        return "identifiers"
    ui_globs = getattr(table, "UI_GLOBS", ())
    if any(fnmatch.fnmatch(rel_path, g) for g in ui_globs):
        if ctx != "comment":
            if _ui_wire_name(text, start, end):
                return "keys"
            return "operator"
    if os.path.basename(rel_path) == "pyproject.toml":
        if toml_table == "project.optional-dependencies" and ctx == "toml_key":
            return "operator"

    if _in_pip_extra(text, start, end):
        return "operator"

    if ctx in {"py_string", "py_text"}:
        content = _enclosing_string_content(text, start, ctx, tokens)
        if (
            text[start - 1 : start] == "-"
            or text[end : end + 1] == "-"
            or (content is not None and '="' in content)
        ):
            return "operator"
    if ctx in {"py_text", "toml_text"} and _is_dotted_python_path(T):
        return "identifiers"
    if ctx == "py_text" and any(
        T.startswith(d + "/") for d in getattr(table, "REPO_TOP_DIRS", ())
    ):
        return _path_move_scope(T)
    if ctx in {"py_text", "toml_text"}:
        w_start, w_end = _expand_word(text, start, end)
        if (
            (
                text[start - 1 : start] == "["
                and text[start].islower()
            )
            or "." in T
            or (
                text[end : end + 1] == ":"
                and text[end + 1 : end + 2].isalnum()
            )
            or (
                text[start].islower()
                and re.match(r"[ \t]*=(?!=)", text[w_end:])
                and (
                    text[w_start - 1 : w_start] in {'"', "'", "\n"}
                    or text[w_start - 2 : w_start] == "\\n"
                )
            )
        ):
            return "keys"
        return "operator"

    if ctx in {"md_prose", "comment", "docstring", "toml_comment"}:
        if not _is_code_reference(text, start, end, ctx):
            if shape == "bare":
                return "prose"
            if _is_prose_compound(T, capabilities):
                top_dirs = getattr(table, "REPO_TOP_DIRS", ())
                if not any(T.startswith(d + "/") for d in top_dirs):
                    return "prose"
    target = _link_target(rel_path, T, table, in_link=_in_markdown_link_target(text, start))
    if target is not None:
        return _path_move_scope(target)
    if T.startswith("docs/"):
        return "prose"

    if (
        ctx == "py_name"
        and _name_token_at(tokens, start) in getattr(table, "PERSISTED_EXACT", {})
        and not _in_repo_dotted_chain(tokens, start)
    ):
        return "persisted"
    if ctx == "py_name":
        return "identifiers"
    if ctx == "toml_key":
        operator_exact = getattr(table, "OPERATOR_EXACT", ())
        if T in operator_exact:
            return "operator"
        persisted = getattr(table, "PERSISTED_EXACT", {})
        if T in persisted:
            return "persisted"
    for prefix in ("kaine.", "tests."):
        if T.startswith(prefix):
            return "identifiers"
    for prefix in _repo_top_prefixes(table):
        if T.startswith(prefix):
            return "identifiers"
    if T.endswith(".py"):
        return "identifiers"
    if ctx in {"py_string", "py_text"} and _is_label_kwarg_value(tokens, start):
        return "operator"
    if ctx in {"py_string", "py_text"}:
        full = _enclosing_string_content(text, start, ctx, tokens)
        if full is not None and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", full
        ) and any(ch.isupper() for ch in full.split(".")[0]):
            return "identifiers"
    if ctx == "md_code" and any(ch.isupper() for ch in W):
        return "identifiers"
    if ctx == "path":
        return "identifiers"
    if (_is_prose_like(ctx) or ctx == "md_code") and shape == "component" and any(
        ch.isupper() for ch in W
    ):
        return "identifiers"

    return "keys"


def _string_content_at(text: str, start: int, end: int, ctx: str | None) -> str | None:
    """Return the literal content of a Python or TOML string at this span."""
    if ctx in {"py_string", "py_text"}:
        raw = text[start:end]
        try:
            return ast.literal_eval(raw)
        except Exception:
            return _strip_quotes(raw)
    if ctx in {"toml_string", "toml_text"}:
        return _strip_quotes(text[start:end])
    return None


def _strip_quotes(raw: str) -> str | None:
    raw = raw.strip()
    if raw.startswith('"""') and raw.endswith('"""'):
        return raw[3:-3]
    if raw.startswith("'''") and raw.endswith("'''"):
        return raw[3:-3]
    if len(raw) >= 2:
        if raw[0] in "\"'" and raw[-1] == raw[0]:
            return raw[1:-1]
    return None


def _div_chain_strings(tokens: list[dict], start: int) -> list[str]:
    """The string operands of the ``/`` chain around the string token at ``start``."""
    if not tokens:
        return []
    fstring_start = getattr(tokenize, "FSTRING_START", None)
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    fstring_end = getattr(tokenize, "FSTRING_END", None)
    fstring_types = tuple(
        t for t in (fstring_start, fstring_middle, fstring_end) if t is not None
    )
    skip = {
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.COMMENT,
        tokenize.INDENT,
        tokenize.DEDENT,
    }

    containing = None
    for idx, tok in enumerate(tokens):
        if tok["start"] <= start < tok["end"]:
            containing = idx
            break
    if containing is None:
        return []
    if fstring_types and tokens[containing]["type"] in fstring_types:
        return []
    if tokens[containing]["type"] != tokenize.STRING:
        return []

    def _prev_sig(idx: int) -> int | None:
        for j in range(idx - 1, -1, -1):
            if tokens[j]["type"] not in skip:
                return j
        return None

    def _next_sig(idx: int) -> int | None:
        for j in range(idx + 1, len(tokens)):
            if tokens[j]["type"] not in skip:
                return j
        return None

    string_indices: list[int] = [containing]

    current = containing
    while True:
        prev = _prev_sig(current)
        if prev is None or not (
            tokens[prev]["type"] == tokenize.OP and tokens[prev]["string"] == "/"
        ):
            break
        before = _prev_sig(prev)
        if before is None:
            break
        btype = tokens[before]["type"]
        if btype == tokenize.STRING:
            string_indices.append(before)
            current = before
        elif btype == tokenize.NAME or (
            btype == tokenize.OP and tokens[before]["string"] == ")"
        ):
            current = before
        else:
            break

    current = containing
    while True:
        nxt = _next_sig(current)
        if nxt is None or not (
            tokens[nxt]["type"] == tokenize.OP and tokens[nxt]["string"] == "/"
        ):
            break
        after = _next_sig(nxt)
        if after is None:
            break
        atype = tokens[after]["type"]
        if atype == tokenize.STRING:
            string_indices.append(after)
            current = after
        elif atype == tokenize.NAME or (
            atype == tokenize.OP and tokens[after]["string"] == ")"
        ):
            current = after
        else:
            break

    result: list[str] = []
    for idx in sorted(string_indices):
        try:
            val = ast.literal_eval(tokens[idx]["string"])
        except Exception:
            continue
        if isinstance(val, str):
            result.append(val)
    return result


# These keyword arguments carry operator-facing labels, which the operator scope renames.
LABEL_KWARGS = ("role", "title", "label")


def _is_label_kwarg_value(tokens: list[dict], start: int) -> bool:
    """Return True when the string at ``start`` is the value of a label keyword argument."""
    if not tokens:
        return False

    string_index = -1
    for i, tok in enumerate(tokens):
        if tok["type"] == tokenize.STRING and tok["start"] <= start < tok["end"]:
            string_index = i
            break
    if string_index == -1:
        return False

    def _prev_significant(idx: int):
        while idx >= 0:
            if tokens[idx]["type"] not in {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT}:
                return idx
            idx -= 1
        return None

    prev = _prev_significant(string_index - 1)
    if prev is None or tokens[prev]["type"] != tokenize.OP or tokens[prev]["string"] != "=":
        return False
    prev = _prev_significant(prev - 1)
    if prev is None or tokens[prev]["type"] != tokenize.NAME or tokens[prev]["string"] not in LABEL_KWARGS:
        return False
    prev = _prev_significant(prev - 1)
    if prev is None or tokens[prev]["type"] != tokenize.OP or tokens[prev]["string"] not in {"(", ","}:
        return False
    return True


def _names_python_symbol(tokens: list[dict], start: int) -> bool:
    """True when the string at ``start`` is a parametrize argnames string or the
    attribute-name argument of getattr, hasattr, setattr or delattr,
    or an entry in an ``__all__`` list/tuple."""
    if not tokens:
        return False
    skip = {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT}

    containing = None
    for idx, tok in enumerate(tokens):
        if tok["start"] <= start < tok["end"]:
            containing = idx
            break
    if containing is None or tokens[containing]["type"] != tokenize.STRING:
        return False

    def _prev_sig(idx: int) -> int | None:
        for j in range(idx - 1, -1, -1):
            if tokens[j]["type"] not in skip:
                return j
        return None

    prev = _prev_sig(containing)
    if prev is None:
        return False

    if tokens[prev]["type"] == tokenize.OP and tokens[prev]["string"] == "(":
        before = _prev_sig(prev)
        if (
            before is not None
            and tokens[before]["type"] == tokenize.NAME
            and tokens[before]["string"] == "parametrize"
        ):
            return True

    if tokens[prev]["type"] == tokenize.OP and tokens[prev]["string"] == ",":
        depth = 0
        comma_count = 0
        for j in range(prev, -1, -1):
            ttype = tokens[j]["type"]
            tstring = tokens[j]["string"]
            if ttype == tokenize.OP:
                if tstring in (")", "]", "}"):
                    depth += 1
                elif tstring in ("(", "[", "{"):
                    if depth == 0:
                        if comma_count == 1:
                            before = _prev_sig(j)
                            if (
                                before is not None
                                and tokens[before]["type"] == tokenize.NAME
                                and tokens[before]["string"]
                                in {"getattr", "hasattr", "setattr", "delattr"}
                            ):
                                return True
                        break
                    depth -= 1
                elif depth == 0 and tstring == ",":
                    comma_count += 1

    # An __all__ entry names a Python symbol.
    depth = 0
    for j in range(containing - 1, -1, -1):
        ttype = tokens[j]["type"]
        tstring = tokens[j]["string"]
        if ttype == tokenize.OP:
            if tstring in (")", "]", "}"):
                depth += 1
            elif tstring in ("(", "[", "{"):
                if depth == 0:
                    if tstring in ("(", "["):
                        before = _prev_sig(j)
                        if (
                            before is not None
                            and tokens[before]["type"] == tokenize.OP
                            and tokens[before]["string"] in ("=", "+=")
                        ):
                            before2 = _prev_sig(before)
                            if (
                                before2 is not None
                                and tokens[before2]["type"] == tokenize.NAME
                                and tokens[before2]["string"] == "__all__"
                            ):
                                return True
                    return False
                depth -= 1
    return False


def _operand_of_div(tokens: list[dict], start: int, end: int) -> bool:
    """Return True when the match is a Python string operand of ``/``."""
    if not tokens:
        return False

    fstring_start = getattr(tokenize, "FSTRING_START", None)
    fstring_middle = getattr(tokenize, "FSTRING_MIDDLE", None)
    fstring_end = getattr(tokenize, "FSTRING_END", None)
    fstring_types = tuple(
        t for t in (fstring_start, fstring_middle, fstring_end) if t is not None
    )

    skip = {
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.COMMENT,
        tokenize.INDENT,
        tokenize.DEDENT,
    }

    containing = None
    for idx, tok in enumerate(tokens):
        if tok["start"] <= start < tok["end"]:
            containing = idx
            break
    if containing is None:
        return False

    start_idx = containing
    end_idx = containing

    if fstring_types and tokens[containing]["type"] in fstring_types:
        depth = 0
        for j in range(containing - 1, -1, -1):
            ttype = tokens[j]["type"]
            if ttype == fstring_end:
                depth += 1
            elif ttype == fstring_start:
                if depth == 0:
                    start_idx = j
                    break
                depth -= 1

        depth = 0
        for j in range(start_idx + 1, len(tokens)):
            ttype = tokens[j]["type"]
            if ttype == fstring_start:
                depth += 1
            elif ttype == fstring_end:
                if depth == 0:
                    end_idx = j
                    break
                depth -= 1

    prev_tok = None
    for j in range(start_idx - 1, -1, -1):
        if tokens[j]["type"] not in skip:
            prev_tok = tokens[j]
            break

    next_tok = None
    for j in range(end_idx + 1, len(tokens)):
        if tokens[j]["type"] not in skip:
            next_tok = tokens[j]
            break

    return (
        (prev_tok is not None and prev_tok["type"] == tokenize.OP and prev_tok["string"] == "/")
        or (next_tok is not None and next_tok["type"] == tokenize.OP and next_tok["string"] == "/")
    )


def _pattern_covers(
    pattern: str, container: str, rel_start: int, rel_end: int
) -> bool:
    for m in re.finditer(pattern, container):
        if m.start() <= rel_start and m.end() >= rel_end:
            return True
    return False


def _resolve_guarded(
    old_key: str,
    shape: str,
    ctx: str | None,
    rel_path: str,
    start: int,
    end: int,
    text: str,
    T: str,
    toml_table: str | None,
    starts: list[int] | None,
    table,
) -> tuple[str, str] | None:
    """Return (action, rule_text) for a guarded name, or None if not guarded."""
    del T
    guarded = getattr(table, "GUARDED", {})
    if old_key not in guarded:
        return None
    entry = guarded[old_key]
    rules = entry.get("rules", [])
    full_path = rel_path.replace("\\", "/")

    for rule in rules:
        ok = True
        if "contexts" in rule:
            if ctx not in rule["contexts"]:
                ok = False
        if ok and "files" in rule:
            if not any(fnmatch.fnmatch(rel_path, pat) for pat in rule["files"]):
                ok = False
        if ok and "shapes" in rule:
            if shape not in rule["shapes"]:
                ok = False
        if ok and "toml_table" in rule:
            if toml_table != rule["toml_table"]:
                ok = False
        if ok and "pattern" in rule:
            if ctx == "path":
                container = full_path
                rel_start = start
                rel_end = end
            else:
                if starts is None:
                    ok = False
                else:
                    line_start, line_end = _line_bounds(text, starts, start)
                    container = text[line_start:line_end]
                    rel_start = start - line_start
                    rel_end = end - line_start
            if ok and not _pattern_covers(
                rule["pattern"], container, rel_start, rel_end
            ):
                ok = False
        if ok:
            why = rule.get("why", "guarded rule")
            return (rule["action"], f"guarded:{why}")
    default = entry.get("default", "queue")
    return (default, "guarded:default")


def _resolve_resolutions(
    old_key: str,
    shape: str,
    ctx: str | None,
    rel_path: str,
    start: int,
    end: int,
    text: str,
    toml_table: str | None,
    starts: list[int] | None,
    table,
) -> tuple[str, str] | None:
    for rule in getattr(table, "RESOLUTIONS", []):
        if rule.get("name") != old_key:
            continue
        ok = True
        if "contexts" in rule and ctx not in rule["contexts"]:
            ok = False
        if ok and "files" in rule:
            if not any(fnmatch.fnmatch(rel_path, pat) for pat in rule["files"]):
                ok = False
        if ok and "shapes" in rule:
            if shape not in rule["shapes"]:
                ok = False
        if ok and "toml_table" in rule:
            if toml_table != rule["toml_table"]:
                ok = False
        if ok and "pattern" in rule:
            if ctx == "path" or starts is None:
                container = text
                rel_start = start
                rel_end = end
            else:
                line_start, line_end = _line_bounds(text, starts, start)
                container = text[line_start:line_end]
                rel_start = start - line_start
                rel_end = end - line_start
            if not _pattern_covers(
                rule["pattern"], container, rel_start, rel_end
            ):
                ok = False
        if ok:
            why = rule.get("why", "resolution")
            return (rule["action"], f"resolution:{why}")
    return None


def _resolve_non_guarded(
    ctx: str | None,
    T: str,
    rel_path: str,
    text: str,
    start: int,
    end: int,
    table,
) -> tuple[bool, str]:
    """Return (rename, rule) for a non-guarded name."""
    if ctx in {"shell", "other"}:
        if any(
            fnmatch.fnmatch(rel_path, g) for g in getattr(table, "UI_GLOBS", ())
        ) and _ui_wire_name(text, start, end):
            return (True, "unlisted")
        if _in_pip_extra(text, start, end):
            return (True, "unlisted")
        env_vars = _env_var_set(table)
        if re.fullmatch(r"^[A-Z][A-Z0-9_]*$", T) and (
            T.startswith("KAINE_") or T in env_vars
        ):
            return (True, "unlisted")
        if T.startswith("--"):
            return (True, "unlisted")
        for prefix in _repo_top_prefixes(table):
            if T.startswith(prefix):
                return (True, "unlisted")
        for prefix in ("kaine.", "tests."):
            if T.startswith(prefix):
                return (True, "unlisted")
        if "." in T and T.islower():
            return (True, "unlisted")
        return (False, "unlisted")
    return (True, "word")


def _adjust_possessive(
    text: str, start: int, end: int, new_sub: str, ctx: str | None
) -> tuple[int, str]:
    """
    Extend a replacement through a bare apostrophe when the old name ended in
    ``s`` but the new name does not.

    Only in prose-like contexts, when the old text ends in ``s``/``S``, the
    match is not a code reference, the character before the match is not a
    quote/apostrophe, and the character after the apostrophe is not a
    letter or digit. Path segments never extend.
    """
    old_sub = text[start:end]
    if not old_sub or old_sub[-1] not in ("s", "S"):
        return end, new_sub
    if not new_sub or new_sub[-1].lower() == "s":
        return end, new_sub
    if ctx not in {"md_prose", "comment", "docstring", "toml_comment"}:
        return end, new_sub
    if _is_code_reference(text, start, end, ctx):
        return end, new_sub
    if start > 0 and text[start - 1] in ("'", '"'):
        return end, new_sub
    if end >= len(text) or text[end] != "'":
        return end, new_sub
    if end + 1 < len(text) and text[end + 1].isalnum():
        return end, new_sub
    return end + 1, new_sub + "'s"


def _replacement_for(
    text: str,
    start: int,
    end: int,
    scope: str,
    shape: str,
    old_key: str,
    plural: bool,
    table,
    ctx: str | None,
    T: str,
    rel_path: str,
    capabilities: frozenset[str] = frozenset(),
) -> str:
    entry = _all_entries(table)[old_key]
    forms = _new_forms(entry, plural)
    matched = text[start:end]

    code_like = _is_code_reference(text, start, end, ctx)

    if (
        _is_prose_compound(T, capabilities)
        and ctx in {"md_prose", "comment", "docstring", "toml_comment"}
        and not code_like
    ):
        sep = "-" if "-" in T else "/"
        if matched[0].isupper():
            if sep == "-":
                kebab = forms["kebab"]
                if kebab and kebab[0].islower():
                    return kebab[0].upper() + kebab[1:]
                return kebab
            prose = forms["prose"]
            if prose and prose[0].islower():
                return prose[0].upper() + prose[1:]
            return prose
        if sep == "-":
            return forms["kebab"]
        prose = forms["prose"]
        if prose and prose[0].isupper():
            return prose[0].lower() + prose[1:]
        return prose

    kebab = False
    if start > 0 and text[start - 1] == "-":
        kebab = True
    if end < len(text) and text[end] == "-":
        kebab = True

    if matched[0].islower():
        force_kebab = False
        if T.endswith(".md") or "docs/" in T:
            link_target = _link_target(rel_path, T, table)
            if link_target is not None and (
                link_target.startswith("docs/")
                or link_target.startswith("openspec/specs/")
                or re.match(r"openspec/changes/[^/]+/specs/", link_target)
            ):
                force_kebab = True
        if kebab or force_kebab:
            return forms["kebab"]
        if shape == "camel_lower":
            return forms["lower_camel"]
        if not code_like and scope != "keys" and _is_prose_like(ctx) and shape == "bare":
            if forms["prose"][0].isupper():
                return forms["prose"][0].lower() + forms["prose"][1:]
            return forms["prose"]
        return forms["key"]

    if matched[0].isupper() and (
        (len(matched) > 1 and matched[1:].isupper()) or len(matched) == 1
    ):
        return forms["upper"]

    if matched[0].isupper():
        if not code_like and scope != "keys" and _is_prose_like(ctx) and shape == "bare":
            prose = forms["prose"]
            if prose and prose[0].islower():
                return prose[0].upper() + prose[1:]
            return prose
        return forms["class"]

    if not code_like and scope != "keys" and _is_prose_like(ctx) and shape == "bare":
        return forms["prose"]
    return forms["key"]


# --------------------------------------------------------------------------- #
# Rewriting passes
# --------------------------------------------------------------------------- #


def marked_old_name_lines(text: str, markers: tuple[str, ...], line_marker: str) -> set[int]:
    """Return 1-based line numbers allowed to contain old module names.

    A Markdown section started by a level-1 to level-3 heading is allowed
    when its heading contains one of *markers* (case-insensitive).  Lines
    inside fenced code blocks do not start sections.  In addition, any
    line whose stripped text ends with *line_marker* is allowed.
    """
    lower_markers = tuple(marker.lower() for marker in markers)
    allowed: set[int] = set()
    in_fence = False
    section_marked = False
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            if re.match(r"^#{1,3}\s", raw_line):
                section_marked = any(marker in raw_line.lower() for marker in lower_markers)
        if section_marked:
            allowed.add(line_no)
        if line_marker and stripped.endswith(line_marker):
            allowed.add(line_no)
    return allowed


def _mask_excluded_regions(rel_path: str, text: str, table) -> list[tuple[int, int]]:
    blocked: list[tuple[int, int]] = []
    if os.path.basename(rel_path) == "CHANGELOG.md":
        unreleased = re.search(r"^## \[Unreleased\].*$", text, re.MULTILINE)
        if unreleased:
            next_heading = re.search(r"^## \[", text[unreleased.end() :], re.MULTILINE)
            if next_heading:
                blocked.append((unreleased.end() + next_heading.start(), len(text)))

    if rel_path.lower().endswith(".toml"):
        blocked.extend(_excluded_toml_values(text, table))

    section_files = getattr(table, "OLD_NAME_SECTION_FILES", ())
    if rel_path in section_files:
        markers = getattr(table, "OLD_NAME_SECTION_MARKERS", ())
        line_marker = getattr(table, "OLD_NAME_LINE_MARKER", "")
        allowed_lines = marked_old_name_lines(text, markers, line_marker)
        if allowed_lines:
            line_start = 0
            line_no = 1
            while line_start < len(text):
                line_end = text.find("\n", line_start)
                if line_end == -1:
                    line_end = len(text)
                if line_no in allowed_lines:
                    blocked.append((line_start, line_end))
                line_no += 1
                if line_end == len(text):
                    break
                line_start = line_end + 1

    return blocked


def _parse_toml_table_name(header: str) -> str | None:
    """Return the full dotted table name from a TOML header line."""
    header = header.strip()
    if not (header.startswith("[") and header.endswith("]")):
        return None
    inner = header[1:-1].strip()
    inner = inner.lstrip("[").rstrip("]").strip()
    if not inner:
        return ""
    segments: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        while i < n and inner[i].isspace():
            i += 1
        if i >= n:
            break
        ch = inner[i]
        if ch in "'\"":
            i += 1
            start = i
            while i < n:
                if inner[i] == "\\" and i + 1 < n and inner[i + 1] == ch:
                    i += 2
                    continue
                if inner[i] == ch:
                    break
                i += 1
            seg = inner[start:i]
            if i < n and inner[i] == ch:
                i += 1
            segments.append(seg)
        else:
            start = i
            while i < n and inner[i] != ".":
                i += 1
            seg = inner[start:i].strip()
            if seg:
                segments.append(seg)
        while i < n and inner[i].isspace():
            i += 1
        if i < n and inner[i] == ".":
            i += 1
    return ".".join(segments)


def _excluded_toml_values(text: str, table) -> list[tuple[int, int]]:
    blocked: list[tuple[int, int]] = []
    excluded = set(getattr(table, "EXCLUDED_TOML_KEYS", ()))
    if not excluded:
        return blocked

    lines = text.split("\n")
    starts = _line_starts(text)
    current_table = ""
    in_multiline = False

    for lno, raw_line in enumerate(lines, start=1):
        line_start = starts[lno - 1]
        line_end = line_start + len(raw_line)
        stripped = raw_line.lstrip()
        if stripped.startswith("[") and stripped.endswith("]"):
            parsed = _parse_toml_table_name(stripped)
            if parsed is not None:
                current_table = parsed
            continue
        eq_pos = _find_unquoted_equal(raw_line)
        if eq_pos == -1:
            continue
        key = raw_line[:eq_pos].strip()
        value = raw_line[eq_pos + 1 :]
        pair = (current_table, key)
        if pair in excluded:
            s = value.lstrip()
            if s.startswith('"""') or s.startswith("'''"):
                close = s[3:].find(s[:3])
                if close == -1:
                    in_multiline = True
                    blocked.append((line_start + eq_pos + 1, line_end))
                    continue
                else:
                    blocked.append((line_start + eq_pos + 1, line_end))
            else:
                blocked.append((line_start + eq_pos + 1, line_end))
        if in_multiline:
            blocked.append((line_start, line_end))
            if raw_line.rstrip().endswith(('"""', "'''")):
                in_multiline = False

    return blocked


def _apply_key_overrides(
    text: str,
    intervals: list[tuple[int, int, str]],
    blocked: list[tuple[int, int]],
    scopes: set[str],
    only: set[str] | None,
    rel_path: str,
    tokens: list[dict],
    table,
    capabilities: frozenset[str] = frozenset(),
) -> list[tuple[int, int, str, str, str, str]]:
    replacements: list[tuple[int, int, str, str, str, str]] = []
    regex, group_map = _name_regex(table)
    for old_sub, new_sub in getattr(table, "KEY_OVERRIDES", ()):
        attr = _first_old_key_in(old_sub, regex, group_map)
        if only is not None and attr not in only and not any(o in old_sub for o in only):
            continue
        pos = 0
        while True:
            idx = text.find(old_sub, pos)
            if idx == -1:
                break
            end = idx + len(old_sub)
            ok = True
            if idx > 0:
                before = text[idx - 1]
                if before.isalnum() or before == "_":
                    ok = False
            if ok and end < len(text):
                after = text[end]
                if not old_sub.endswith("."):
                    if after.isalnum() or after == "_":
                        ok = False
            if ok and not _blocked(idx, end, blocked):
                ctx = _context_at(idx, intervals)
                if not _is_prose_like(ctx):
                    first = None
                    found_match: re.Match | None = None
                    for m in regex.finditer(text, idx, end):
                        gkey = _matched_group(m, group_map)
                        if gkey:
                            first = gkey
                            found_match = m
                            break
                    if first and found_match:
                        old_key, _plural = first
                        shape, _, _, t_start, t_end = _classify_shape(
                            text, found_match.start(), found_match.end()
                        )
                        toml_table = (
                            _current_toml_table_at(found_match.start(), text, intervals)
                            if rel_path.lower().endswith(".toml")
                            else None
                        )
                        scope = _assign_scope(
                            rel_path,
                            ctx,
                            text,
                            found_match.start(),
                            found_match.end(),
                            text[found_match.start() : found_match.end()],
                            text[t_start:t_end],
                            shape,
                            toml_table,
                            tokens,
                            table,
                            capabilities,
                        )
                        if scope in scopes:
                            replacements.append(
                                (idx, end, new_sub, scope, "override", old_key)
                            )
                            blocked.append((idx, end))
                            pos = end
                            continue
            pos = end if not ok else idx + 1
    return replacements


def _matched_group(
    m: re.Match, group_map: dict[int, tuple[str, bool]]
) -> tuple[str, bool] | None:
    for idx, value in group_map.items():
        if m.group(f"g{idx}") is not None:
            return value
    return None


def _current_toml_table_at(
    offset: int, text: str, intervals: list[tuple[int, int, str]]
) -> str | None:
    current = None
    for start, end, ctx in intervals:
        if start > offset:
            break
        if ctx == "toml_header":
            header = text[start:end].strip()
            current = _parse_toml_table_name(header)
    return current


def _apply_persisted_exact(
    text: str,
    intervals: list[tuple[int, int, str]],
    blocked: list[tuple[int, int]],
    scopes: set[str],
    only: set[str] | None,
    table,
) -> list[tuple[int, int, str, str, str, str]]:
    replacements: list[tuple[int, int, str, str, str, str]] = []
    if "persisted" not in scopes:
        return replacements
    regex, group_map = _name_regex(table)
    persisted = getattr(table, "PERSISTED_EXACT", {})
    for start, end, ctx in intervals:
        if ctx not in {
            "py_string",
            "py_text",
            "toml_string",
            "toml_text",
            "toml_key",
        }:
            continue
        if _blocked(start, end, blocked):
            continue
        raw = text[start:end]
        if ctx == "toml_key":
            stripped = raw.strip()
            if (
                (stripped.startswith('"') and stripped.endswith('"'))
                or (stripped.startswith("'") and stripped.endswith("'"))
            ):
                content = _strip_quotes(stripped)
            else:
                content = stripped
        else:
            content = _string_content_at(text, start, end, ctx)
        if content is None:
            continue
        if content not in persisted:
            continue
        attr = _first_old_key_in(content, regex, group_map)
        if only is not None and attr not in only:
            continue
        value = persisted[content]
        if content not in raw:
            continue
        new_raw = raw.replace(content, value, 1)
        replacements.append(
            (start, end, new_raw, "persisted", "persisted-exact", attr)
        )
        blocked.append((start, end))
    return replacements


def _apply_phrases(
    text: str,
    intervals: list[tuple[int, int, str]],
    blocked: list[tuple[int, int]],
    scopes: set[str],
    only: set[str] | None,
    table,
) -> list[tuple[int, int, str, str, str, str]]:
    replacements: list[tuple[int, int, str, str, str, str]] = []
    regex, group_map = _name_regex(table)
    phrases: list[tuple[str, str, str]] = []
    for old_p, new_p in getattr(table, "PHRASES", ()):
        attr = _first_old_key_in(old_p, regex, group_map)
        if only is not None and attr not in only and not any(o in old_p for o in only):
            continue
        phrases.append((old_p, new_p, attr))
        if old_p:
            cap_old = old_p[0].upper() + old_p[1:]
            cap_new = new_p[0].upper() + new_p[1:] if new_p else new_p
            phrases.append((cap_old, cap_new, attr))

    phrases.sort(key=lambda x: -len(x[0]))

    for old_p, new_p, attr in phrases:
        pos = 0
        while True:
            idx = text.find(old_p, pos)
            if idx == -1:
                break
            end = idx + len(old_p)
            before_ok = idx == 0 or not _is_word_char(text[idx - 1])
            after_ok = end == len(text) or not _is_word_char(text[end])
            ctx = _context_at(idx, intervals)
            if (
                before_ok
                and after_ok
                and not _blocked(idx, end, blocked)
                and _same_context(idx, end, intervals)
                and _is_prose_like(ctx)
            ):
                scope = "operator" if ctx in {"py_text", "toml_text"} else "prose"
                if scope in scopes:
                    replacements.append((idx, end, new_p, scope, "phrase", attr))
                    blocked.append((idx, end))
                pos = end
            else:
                pos = idx + 1
    return replacements


def _apply_word_matches(
    text: str,
    intervals: list[tuple[int, int, str]],
    blocked: list[tuple[int, int]],
    scopes: set[str],
    only: set[str] | None,
    change_ids: frozenset[str],
    rel_path: str,
    tokens: list[dict],
    table,
    capabilities: frozenset[str] = frozenset(),
) -> tuple[
    list[tuple[int, int, str, str, str, str]],
    dict[str, int],
    list[Queued],
]:
    replacements: list[tuple[int, int, str, str, str, str]] = []
    queued: list[Queued] = []
    kept: dict[str, int] = {}

    regex, group_map = _name_regex(table)
    starts = _line_starts(text)

    for m in regex.finditer(text):
        start, end = m.start(), m.end()
        if _blocked(start, end, blocked):
            continue
        gkey = _matched_group(m, group_map)
        if gkey is None:
            continue
        old_key, plural = gkey
        if only is not None and old_key not in only:
            continue

        shape, w_start, w_end, t_start, t_end = _classify_shape(text, start, end)
        W = text[w_start:w_end]
        T = text[t_start:t_end]
        ctx = _context_at(start, intervals)

        if _contains_change_id(T, change_ids):
            kept[old_key] = kept.get(old_key, 0) + 1
            continue

        toml_table = None
        if rel_path.lower().endswith(".toml"):
            toml_table = _current_toml_table_at(start, text, intervals)

        resolution = _resolve_resolutions(
            old_key, shape, ctx, rel_path, start, end, text, toml_table, starts, table
        )
        if resolution:
            action, rule_text = resolution
            if action == "rename":
                scope = _assign_scope(
                    rel_path, ctx, text, start, end, W, T, shape, toml_table, tokens, table, capabilities
                )
                if scope in scopes:
                    new_text = _replacement_for(
                        text, start, end, scope, shape, old_key, plural, table, ctx, T, rel_path, capabilities
                    )
                    replacements.append(
                        (start, end, new_text, scope, rule_text, old_key)
                    )
                    blocked.append((start, end))
                continue
            if action == "keep":
                kept[old_key] = kept.get(old_key, 0) + 1
                continue
            if action == "queue":
                queued.append(
                    Queued(
                        rel_path,
                        _line_number(starts, start),
                        old_key,
                        rule_text,
                        _excerpt(text, starts, start),
                    )
                )
                continue

        guarded_result = _resolve_guarded(
            old_key, shape, ctx, rel_path, start, end, text, T, toml_table, starts, table
        )
        if guarded_result:
            action, rule_text = guarded_result
            if action == "rename":
                scope = _assign_scope(
                    rel_path, ctx, text, start, end, W, T, shape, toml_table, tokens, table, capabilities
                )
                if scope in scopes:
                    new_text = _replacement_for(
                        text, start, end, scope, shape, old_key, plural, table, ctx, T, rel_path, capabilities
                    )
                    replacements.append(
                        (start, end, new_text, scope, rule_text, old_key)
                    )
                    blocked.append((start, end))
                continue
            if action == "keep":
                kept[old_key] = kept.get(old_key, 0) + 1
                continue
            if action == "queue":
                queued.append(
                    Queued(
                        rel_path,
                        _line_number(starts, start),
                        old_key,
                        rule_text,
                        _excerpt(text, starts, start),
                    )
                )
                continue

        rename, rule_text = _resolve_non_guarded(ctx, T, rel_path, text, start, end, table)
        if rename:
            scope = _assign_scope(
                rel_path, ctx, text, start, end, W, T, shape, toml_table, tokens, table, capabilities
            )
            if scope in scopes:
                new_text = _replacement_for(
                    text, start, end, scope, shape, old_key, plural, table, ctx, T, rel_path, capabilities
                )
                replacements.append((start, end, new_text, scope, rule_text, old_key))
                blocked.append((start, end))
        else:
            kept[old_key] = kept.get(old_key, 0) + 1

    return replacements, kept, queued


def _contains_change_id(token_text: str, change_ids: frozenset[str]) -> bool:
    for cid in change_ids:
        if cid and cid in token_text:
            return True
    return False


def _sequence_alias_adjustments(
    text: str,
    replacements: list[tuple[int, int, str, str, str, str]],
    table,
) -> tuple[list[tuple[int, int, str, str, str, str]], list[tuple[str, str, str]]]:
    sequence_old_class: str | None = None
    for old_key, entry in _all_entries(table).items():
        if entry.get("new_class") == "Sequence":
            sequence_old_class = entry["old_class"]
            break
    if sequence_old_class is None:
        return replacements, []

    tokens = _python_token_analysis(text)
    if not tokens:
        return replacements, []
    sequence_bound, kaine_imports = _sequence_imports(tokens, sequence_old_class)
    class_defs = _sequence_class_defs(tokens, sequence_old_class)

    collisions: list[tuple[str, str, str]] = []
    adjusted: list[tuple[int, int, str, str, str, str]] = []
    replaced_name_spans: set[tuple[int, int]] = set()

    for rep in replacements:
        start, end, new_text, scope, rule, old_key = rep
        if scope != "identifiers":
            adjusted.append(rep)
            continue
        aligned = _aligned_name_token(tokens, start, end)
        if aligned is None:
            adjusted.append(rep)
            continue
        replaced_name_spans.add((aligned["start"], aligned["end"]))

        if new_text == "Sequence":
            if class_defs and any(a <= start < b for a, b in class_defs):
                collisions.append(("", "Sequence", "bound"))
                adjusted.append(rep)
                continue
            if sequence_bound:
                if any(a <= start < b for a, b in kaine_imports):
                    new_text = "Sequence as SequenceModule"
                else:
                    new_text = "SequenceModule"
                rule = "sequence-alias"
        adjusted.append((start, end, new_text, scope, rule, old_key))

    unreplaced_bound: set[str] = set()
    unreplaced_attr: set[str] = set()
    for idx, tok in enumerate(tokens):
        if tok["type"] != tokenize.NAME:
            continue
        if (tok["start"], tok["end"]) in replaced_name_spans:
            continue
        if idx > 0 and tokens[idx - 1]["type"] == tokenize.OP and tokens[idx - 1]["string"] == ".":
            unreplaced_attr.add(tok["string"])
        else:
            unreplaced_bound.add(tok["string"])

    final: list[tuple[int, int, str, str, str, str]] = []
    seen_collisions: set[tuple[str, str, str]] = set()
    for rep in adjusted:
        start, end, new_text, scope, rule, old_key = rep
        if scope != "identifiers":
            final.append(rep)
            continue
        if " as " in new_text:
            final.append(rep)
            continue
        aligned = _aligned_name_token(tokens, start, end)
        if aligned is None:
            final.append(rep)
            continue
        name = new_text.split()[0]
        idx = tokens.index(aligned)
        prev = tokens[idx - 1] if idx > 0 else None
        is_attr = prev is not None and prev["type"] == tokenize.OP and prev["string"] == "."
        if is_attr:
            if name in unreplaced_attr and aligned["string"] != name:
                key = ("", name, "attribute")
                if key not in seen_collisions:
                    seen_collisions.add(key)
                    collisions.append(key)
        else:
            if name in unreplaced_bound and aligned["string"] != name:
                key = ("", name, "bound")
                if key not in seen_collisions:
                    seen_collisions.add(key)
                    collisions.append(key)
        final.append(rep)

    return final, collisions


def _key_collisions(
    text: str,
    replacements: list[tuple[int, int, str, str, str, str]],
    intervals: list[tuple[int, int, str]],
) -> list[tuple[str, str, str]]:
    key_contexts = {
        "py_string",
        "py_text",
        "toml_string",
        "toml_text",
        "toml_key",
        "toml_header",
    }
    orig_keys: set[str] = set()
    for start, end, ctx in intervals:
        if ctx not in key_contexts:
            continue
        if ctx in {"py_string", "py_text", "toml_string", "toml_text"}:
            content = _string_content_at(text, start, end, ctx)
            if content is not None:
                orig_keys.add(content)
        if ctx in {"toml_key", "toml_header"}:
            for part in text[start:end].replace("[", "").replace("]", "").split("."):
                orig_keys.add(part.strip().strip('"').strip("'"))

    produced_keys: set[str] = set()
    collisions: list[tuple[str, str, str]] = []
    for rep in replacements:
        start, end, new_text, scope, rule, old_key = rep
        ctx = _context_at(start, intervals)
        if ctx not in key_contexts:
            continue
        if scope != "keys":
            continue
        if new_text in orig_keys and new_text not in produced_keys:
            collisions.append(("", new_text, "key"))
        produced_keys.add(new_text)
    return collisions


def rewrite_text(
    rel_path: str,
    text: str,
    table,
    scopes: set[str],
    only: set[str] | None = None,
    change_ids: frozenset[str] = frozenset(),
    capabilities: frozenset[str] = frozenset(),
) -> FileResult:
    """
    Rewrite the contents of one file according to the table.

    This function is pure: it does not touch the file system.
    """
    starts = _line_starts(text)
    intervals = _context_intervals(rel_path, text)
    kind = _file_kind(rel_path, text)
    tokens: list[dict] = []
    if kind == "python":
        tokens = _python_token_analysis(text)
    if not intervals and kind == "python":
        return FileResult(text, [], [], {}, [], "tokenize error")

    blocked = _mask_excluded_regions(rel_path, text, table)

    replacements: list[tuple[int, int, str, str, str, str]] = []

    overrides = _apply_key_overrides(
        text, intervals, blocked, scopes, only, rel_path, tokens, table, capabilities
    )
    replacements.extend(overrides)

    persisted = _apply_persisted_exact(text, intervals, blocked, scopes, only, table)
    replacements.extend(persisted)

    phrases = _apply_phrases(text, intervals, blocked, scopes, only, table)
    replacements.extend(phrases)

    word_reps, kept, queued = _apply_word_matches(
        text, intervals, blocked, scopes, only, change_ids, rel_path, tokens, table, capabilities
    )
    replacements.extend(word_reps)

    if kind == "python":
        replacements, seq_collisions = _sequence_alias_adjustments(
            text, replacements, table
        )
        key_collisions = _key_collisions(text, replacements, intervals)
    else:
        seq_collisions = []
        key_collisions = []

    collisions: list[tuple[str, str, str]] = seq_collisions + key_collisions

    adjusted: list[tuple[int, int, str, str, str, str]] = []
    for rep in replacements:
        start, end, new_sub, scope, rule, old_key = rep
        ctx = _context_at(start, intervals)
        new_end, new_sub = _adjust_possessive(text, start, end, new_sub, ctx)
        adjusted.append((start, new_end, new_sub, scope, rule, old_key))
    replacements = adjusted

    replacements.sort(key=lambda r: r[0])
    new_text = text
    for start, end, new_sub, _scope, _rule, _old_key in reversed(replacements):
        new_text = new_text[:start] + new_sub + new_text[end:]

    changes = []
    for start, end, new_sub, scope, rule, old_key in replacements:
        changes.append(
            Change(
                path=rel_path,
                line=_line_number(starts, start),
                scope=scope,
                rule=rule,
                name=old_key,
                old=text[start:end],
                new=new_sub,
            )
        )

    return FileResult(
        new_text=new_text,
        changes=changes,
        queued=queued,
        kept=kept,
        collisions=collisions,
        skipped=None,
    )


# --------------------------------------------------------------------------- #
# Path moves
# --------------------------------------------------------------------------- #


def _path_move_scope(rel_norm: str) -> str:
    """Return the move scope for a repo-relative path."""
    if re.match(r"(?:plugins/[^/]+/)?openspec/specs/", rel_norm) or re.match(
        r"(?:plugins/[^/]+/)?openspec/changes/[^/]+/specs/", rel_norm
    ):
        return "keys"
    if rel_norm.startswith("docs/"):
        return "prose"
    if rel_norm.startswith("quadlet/") or rel_norm.startswith("compose/"):
        return "operator"
    return "identifiers"


def _override_old_keys(
    key: str, regex: re.Pattern[str], group_map: dict[int, tuple[str, bool]]
) -> set[str]:
    """Return the old keys whose forms appear in a PATH_OVERRIDES key."""
    old_keys: set[str] = set()
    for m in regex.finditer(key):
        gkey = _matched_group(m, group_map)
        if gkey:
            old_keys.add(gkey[0])
    return old_keys


def new_path(
    rel_path: str,
    table,
    scopes: set[str],
    only: set[str] | None = None,
    change_ids: frozenset[str] = frozenset(),
) -> tuple[str, str | None, list[Queued]]:
    """Compute the new repo-relative path for a file, if any."""
    path_overrides = getattr(table, "PATH_OVERRIDES", {})
    rel_norm = rel_path.replace("\\", "/")
    move_scope = _path_move_scope(rel_norm)
    override_applied = False
    new_norm = rel_norm
    regex, group_map = _name_regex(table)

    if rel_norm in path_overrides:
        override_key = rel_norm
        override_old_keys = _override_old_keys(override_key, regex, group_map)
        if move_scope in scopes and (only is None or not override_old_keys.isdisjoint(only)):
            new_norm = path_overrides[rel_norm]
            override_applied = True
    else:
        best_prefix: str | None = None
        best_new: str | None = None
        for old_prefix, new_prefix in path_overrides.items():
            if old_prefix.endswith("/") and rel_norm.startswith(old_prefix):
                if best_prefix is None or len(old_prefix) > len(best_prefix):
                    best_prefix = old_prefix
                    best_new = new_prefix
        if best_prefix is not None and best_new is not None:
            override_old_keys = _override_old_keys(best_prefix, regex, group_map)
            if move_scope in scopes and (only is None or not override_old_keys.isdisjoint(only)):
                remainder = rel_norm[len(best_prefix) :]
                base = best_new
                if remainder and not base.endswith("/"):
                    base += "/"
                new_norm = base + remainder
                override_applied = True

    parts = new_norm.split("/")
    id_segment: str | None = None
    original_parts = rel_norm.split("/")
    if (
        len(original_parts) > 2
        and original_parts[0] == "openspec"
        and original_parts[1] == "changes"
    ):
        id_segment = original_parts[2]

    kebab_dir = rel_norm.startswith("openspec/specs/") or re.match(
        r"openspec/changes/[^/]+/specs/", rel_norm
    )
    docs_path = rel_norm.startswith("docs/")

    full_path = "/".join(parts)
    new_parts: list[str] = []
    queued: list[Queued] = []
    changed = override_applied

    for idx, segment in enumerate(parts):
        if (
            idx == 2
            and len(parts) > 2
            and parts[0] == "openspec"
            and parts[1] == "changes"
            and id_segment is not None
        ):
            new_parts.append(id_segment)
            continue

        current_segment = segment
        matches = list(regex.finditer(segment))
        for m in reversed(matches):
            start, end = m.start(), m.end()
            gkey = _matched_group(m, group_map)
            if gkey is None:
                continue
            old_key, plural = gkey
            if only is not None and old_key not in only:
                continue

            shape, _, _, t_start, t_end = _classify_shape(segment, start, end)
            token_text = segment[t_start:t_end]
            if _contains_change_id(token_text, change_ids):
                continue

            global_start = sum(len(parts[k]) for k in range(idx)) + idx + start
            global_end = global_start + (end - start)

            resolution = _resolve_resolutions(
                old_key,
                shape,
                "path",
                full_path,
                global_start,
                global_end,
                full_path,
                None,
                None,
                table,
            )
            action: str | None = None
            rule_text = "word"
            if resolution:
                action, rule_text = resolution
            if action is None:
                guarded = _resolve_guarded(
                    old_key,
                    shape,
                    "path",
                    full_path,
                    global_start,
                    global_end,
                    full_path,
                    token_text,
                    None,
                    None,
                    table,
                )
                if guarded:
                    action, rule_text = guarded

            if action == "keep":
                continue
            if action == "queue":
                queued.append(Queued(rel_path, 0, old_key, rule_text, segment))
                continue

            if move_scope not in scopes:
                continue

            entry = _all_entries(table)[old_key]
            forms = _new_forms(entry, plural)
            matched = segment[start:end]
            kebab_neighbor = (start > 0 and segment[start - 1] == "-") or (
                end < len(segment) and segment[end] == "-"
            )
            if matched[0].islower():
                new_sub = forms["kebab"] if (kebab_neighbor or kebab_dir or docs_path) else forms["key"]
            elif matched[0].isupper() and (
                len(matched) == 1 or matched[1:].isupper()
            ):
                new_sub = forms["upper"]
            else:
                new_sub = forms["class"]
            new_end, new_sub = _adjust_possessive(segment, start, end, new_sub, "path")
            current_segment = current_segment[:start] + new_sub + current_segment[new_end:]
            changed = True

        new_parts.append(current_segment)

    if not changed:
        return rel_path, None, queued
    return "/".join(new_parts), move_scope, queued


# --------------------------------------------------------------------------- #
# Git / file scanning helpers
# --------------------------------------------------------------------------- #


def tracked_files(root: Path) -> list[str]:
    """Return sorted repo-relative paths for tracked files."""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RootError(f"root {root}: git not found") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RootError(f"root {root}: git ls-files failed: {stderr}")

    raw = proc.stdout.split(b"\0")
    files = [p.decode("utf-8") for p in raw if p]
    files.sort()
    return files


def change_ids(root: Path, files: Iterable[str]) -> frozenset[str]:
    """Collect active and archived change IDs that contain a hyphen."""
    del root
    active: set[str] = set()
    archived: set[str] = set()
    for rel in files:
        rel_norm = rel.replace("\\", "/")
        parts = rel_norm.split("/")
        # Only segments that are directories (not the final path part) may be IDs.
        max_dir_idx = len(parts) - 1
        if max_dir_idx <= 0:
            continue
        for i in range(max_dir_idx - 1):
            if parts[i] == "openspec" and parts[i + 1] == "changes":
                next_idx = i + 2
                if next_idx >= max_dir_idx:
                    continue
                candidate = parts[next_idx]
                if candidate == "archive":
                    archive_idx = next_idx + 1
                    if archive_idx >= max_dir_idx:
                        continue
                    cid = parts[archive_idx]
                    m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", cid)
                    if m:
                        archived.add(m.group(1))
                    else:
                        archived.add(cid)
                else:
                    active.add(candidate)
    return frozenset(cid for cid in (active | archived) if "-" in cid)


def openspec_capabilities(files: Iterable[str]) -> frozenset[str]:
    """Collect capability folder names following every openspec/specs/ segment."""
    caps: set[str] = set()
    for rel in files:
        rel_norm = rel.replace("\\", "/")
        parts = rel_norm.split("/")
        for i in range(len(parts) - 2):
            if parts[i] == "openspec" and parts[i + 1] == "specs":
                candidate = parts[i + 2]
                if candidate and i + 2 < len(parts) - 1:
                    caps.add(candidate)
            elif (
                parts[i] == "openspec"
                and parts[i + 1] == "changes"
                and parts[i + 2] != "archive"
                and i + 3 < len(parts)
                and parts[i + 3] == "specs"
                and i + 4 < len(parts)
            ):
                candidate = parts[i + 4]
                if candidate and i + 4 < len(parts) - 1:
                    caps.add(candidate)
    return frozenset(caps)


def is_excluded(rel_path: str, table) -> bool:
    """Return True when a path is excluded from processing."""
    rel_norm = rel_path.replace("\\", "/")
    for pat in getattr(table, "EXCLUDED_GLOBS", ()):
        if pat.endswith("/"):
            if rel_norm == pat.rstrip("/") or rel_norm.startswith(pat):
                return True
        else:
            if fnmatch.fnmatch(rel_norm, pat) or fnmatch.fnmatch(
                os.path.basename(rel_norm), pat
            ):
                return True
    return False


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


# --------------------------------------------------------------------------- #
# Plan construction
# --------------------------------------------------------------------------- #


def plan(
    root: Path,
    table,
    scopes: set[str],
    only: set[str] | None = None,
) -> Plan:
    """Build a full rename plan for the repository."""
    files = tracked_files(root)
    change_ids_set = change_ids(root, files)
    capabilities_set = openspec_capabilities(files)

    moves: list[tuple[str, str, str]] = []
    results: dict[str, FileResult] = {}
    all_collisions: list[tuple[str, str, str]] = []
    path_queued: list[Queued] = []

    for rel in files:
        if is_excluded(rel, table):
            continue

        new_rel, move_scope, q = new_path(rel, table, scopes, only, change_ids_set)
        for item in q:
            path_queued.append(item)

        if new_rel != rel and move_scope in scopes:
            moves.append((rel, new_rel, move_scope))

        path = root / rel
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue
        if _is_binary(data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue

        result = rewrite_text(rel, text, table, scopes, only, change_ids_set, capabilities_set)
        if result.skipped:
            results[rel] = result
            continue
        if (
            result.changes
            or result.queued
            or result.kept
            or result.collisions
            or new_rel != rel
        ):
            results[rel] = result
            for _path_part, name, kind in result.collisions:
                all_collisions.append((rel, name, kind))

    moves.sort(key=lambda x: (x[0], x[1]))
    all_collisions.sort(key=lambda x: (x[0], x[1], x[2]))

    accepted_pairs: set[tuple[str, str]] = set()
    for item in getattr(table, "ACCEPTED_COLLISIONS", ()):
        accepted_pairs.add(item)

    move_map = {old: new for old, new, _scope in moves}
    collisions: list[tuple[str, str, str]] = []
    accepted: list[tuple[str, str, str]] = []
    for rel, name, kind in all_collisions:
        new_rel = move_map.get(rel, rel)
        if (rel, name) in accepted_pairs or (new_rel, name) in accepted_pairs:
            accepted.append((rel, name, kind))
        else:
            collisions.append((rel, name, kind))

    scopes_tuple = tuple(s for s in getattr(table, "SCOPES", ()) if s in scopes)

    only_tuple: tuple[str, ...] | None = None
    if only is not None:
        only_tuple = tuple(sorted(only))

    return Plan(
        scopes=scopes_tuple,
        only=only_tuple,
        moves=moves,
        results=results,
        collisions=collisions,
        accepted=accepted,
        table_modules=getattr(table, "MODULES", {}),
        table_developmental=getattr(table, "DEVELOPMENTAL", {}),
        path_queued=path_queued,
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def render_report(plan: Plan, mode: str) -> str:
    """Render the deterministic report string."""
    lines: list[str] = []

    lines.append("# rename_modules report")
    lines.append(f"mode: {mode}")
    lines.append(f"scopes: {','.join(plan.scopes)}")
    if plan.only is None:
        lines.append("names: all")
    else:
        lines.append(f"names: {','.join(plan.only)}")

    move_lines = [f"{old} -> {new} [{scope}]" for old, new, scope in plan.moves]

    scope_rule_counts: dict[str, dict[str, dict[str, int]]] = {}
    total_replacements = 0
    for rel, result in plan.results.items():
        for ch in result.changes:
            scope_rule_counts.setdefault(rel, {})
            scope_rule_counts[rel].setdefault(ch.scope, {})
            scope_rule_counts[rel][ch.scope][ch.rule] = (
                scope_rule_counts[rel][ch.scope].get(ch.rule, 0) + 1
            )
            total_replacements += 1

    scope_order = {scope: idx for idx, scope in enumerate(plan.scopes)}

    change_items: list[tuple[str, int, str]] = []
    for rel in scope_rule_counts:
        for scope, rules in scope_rule_counts[rel].items():
            rule_parts = " ".join(
                f"{rule}={count}" for rule, count in sorted(rules.items())
            )
            change_items.append(
                (rel, scope_order.get(scope, len(scope_order)), f"{rel} [{scope}] {rule_parts}")
            )
    change_items.sort(key=lambda x: (x[0], x[1]))
    change_lines = [item[2] for item in change_items]

    renamed_counts: dict[str, int] = {}
    queued_counts: dict[str, int] = {}
    kept_counts: dict[str, int] = {}
    for result in plan.results.values():
        for ch in result.changes:
            renamed_counts[ch.name] = renamed_counts.get(ch.name, 0) + 1
        for q in result.queued:
            queued_counts[q.name] = queued_counts.get(q.name, 0) + 1
        for name, count in result.kept.items():
            kept_counts[name] = kept_counts.get(name, 0) + count

    name_lines: list[str] = []
    for name in list(plan.table_modules.keys()) + list(plan.table_developmental.keys()):
        name_lines.append(
            f"{name} renamed={renamed_counts.get(name, 0)} "
            f"queued={queued_counts.get(name, 0)} "
            f"kept={kept_counts.get(name, 0)}"
        )

    collision_lines = [f"{rel} {name} {kind}" for rel, name, kind in plan.collisions]
    collision_lines.extend(
        f"{rel} {name} {kind} accepted" for rel, name, kind in plan.accepted
    )

    queue_items: list[Queued] = []
    for result in plan.results.values():
        queue_items.extend(result.queued)
    queue_items.extend(plan.path_queued)

    queue_lines = [
        f"{q.path}:{q.line} {q.name} {q.rule} | {q.excerpt}"
        for q in sorted(queue_items, key=lambda x: (x.path, x.line, x.name, x.rule))
    ]

    skipped_items: list[tuple[str, str]] = []
    for rel, result in plan.results.items():
        if result.skipped:
            skipped_items.append((rel, result.skipped))
    skipped_lines = [f"{rel} {reason}" for rel, reason in skipped_items]

    sections = [
        (f"## moves ({len(plan.moves)})", move_lines),
        (f"## changes ({len(scope_rule_counts)} files, {total_replacements} replacements)", change_lines),
        ("## per name", name_lines),
        (f"## collisions ({len(plan.collisions) + len(plan.accepted)})", collision_lines),
        (f"## review queue ({len(queue_items)})", queue_lines),
        (f"## skipped ({len(skipped_items)})", skipped_lines),
    ]

    for heading, items in sections:
        lines.append("")
        lines.append(heading)
        lines.extend(items)

    total_moves = len(plan.moves)
    total_files = len(scope_rule_counts)
    total_queued = len(queue_items)
    total_kept = sum(kept_counts.values())
    total_skipped = len(skipped_items)
    lines.append("")
    lines.append("## totals")
    lines.append(
        f"moves={total_moves} files={total_files} "
        f"replacements={total_replacements} collisions={len(plan.collisions)} "
        f"queued={total_queued} kept={total_kept} skipped={total_skipped}"
    )

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Apply plan
# --------------------------------------------------------------------------- #


class PlanError(Exception):
    """Raised when a plan cannot be applied safely."""


def apply_plan(root: Path, plan: Plan) -> None:
    """Apply a plan: move files and write rewritten contents."""
    targets: dict[str, str] = {}
    for old, new, _scope in plan.moves:
        if (root / new).exists() and str(root / new) != str(root / old):
            raise PlanError(f"move target already exists: {new}")
        if new in targets:
            raise PlanError(f"two moves share target: {new}")
        targets[new] = old

    if plan.collisions:
        raise PlanError(
            f"plan has {len(plan.collisions)} unaccepted collision(s); add to ACCEPTED_COLLISIONS"
        )

    for old, new, _scope in plan.moves:
        new_full = root / new
        new_full.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "mv", old, new], cwd=root, check=True)

    for rel, result in plan.results.items():
        target = rel
        for old, new, _scope in plan.moves:
            if old == rel:
                target = new
                break
        target_path = root / target
        with open(target_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(result.new_text)


# --------------------------------------------------------------------------- #
# Survey
# --------------------------------------------------------------------------- #


def _survey_category(rel_path: str, table) -> str:
    r = rel_path.replace("\\", "/")
    third = getattr(table, "SURVEY_THIRD_PARTY_PREFIXES", ())
    ui = getattr(table, "SURVEY_UI_PREFIXES", ())
    if r.startswith("openspec/changes/archive/"):
        return "Archive"
    if r.startswith("docs/records/"):
        return "Records"
    if r == "CHANGELOG.md":
        return "CHANGELOG"
    if any(r.startswith(p) for p in third):
        return "Third-party"
    if r.startswith("openspec/changes/"):
        return "Active changes"
    if r.startswith("openspec/specs/"):
        return "Specs"
    if r.startswith("tests/"):
        return "Tests"
    if r.startswith("config/"):
        return "Config"
    if (
        r.startswith("quadlet/")
        or r.startswith("compose/")
        or r.startswith("docker/")
        or os.path.basename(r).startswith("Dockerfile")
    ):
        return "Container"
    if any(r.startswith(p) for p in ui):
        return "UI"
    if r.startswith("docs/") or ("/" not in r and r.endswith(".md")):
        return "Docs"
    if r.endswith(".py") and r.startswith(
        ("kaine/", "plugins/", "tools/", "scripts/", "eval_probes/")
    ):
        return "Code"
    return "Other"


def _survey_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def survey(root: Path, table) -> str:
    """Build the survey table."""
    files = tracked_files(root)
    entries = _all_entries(table)

    columns = [
        "Name",
        "Paths",
        "Code",
        "Tests",
        "Config",
        "Container",
        "UI",
        "Docs",
        "Specs",
        "Active changes",
        "Archive",
        "Records",
        "CHANGELOG",
        "Third-party",
        "Other",
    ]

    rows: list[list[str]] = [
        _survey_row(columns),
        _survey_row(["---"] * len(columns)),
    ]

    names: list[tuple[str, str]] = []  # (count_key, display_label)
    for old_key in entries:
        names.append((old_key, old_key))
    for name, label in getattr(table, "SURVEY_EXTRA", ()):
        names.append((name, label))

    name_regexes: dict[str, re.Pattern[str]] = {}
    for count_key, display_label in names:
        if count_key in entries:
            entry = entries[count_key]
            forms = {count_key, entry["old_class"], count_key.upper()}
        else:
            forms = {
                count_key,
                count_key[0].upper() + count_key[1:] if count_key else "",
                count_key.upper(),
            }
        forms = [f for f in forms if f]
        pat = "(?<![A-Za-z])(?:" + "|".join(re.escape(f) for f in forms) + r")(?![a-z])"
        name_regexes[display_label] = re.compile(pat)

    counts: dict[str, dict[str, int]] = {
        label: {col: 0 for col in columns[1:]} for _, label in names
    }
    files_seen: dict[str, set[str]] = {label: set() for _, label in names}

    for rel in files:
        category = _survey_category(rel, table)
        try:
            data = (root / rel).read_bytes()
        except FileNotFoundError:
            continue

        is_binary = _is_binary(data)

        for label, regex in name_regexes.items():
            if regex.search(rel):
                counts[label]["Paths"] += 1
                files_seen[label].add(rel)

        if is_binary:
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")

        for label, regex in name_regexes.items():
            if category in counts[label]:
                matches = len(regex.findall(text))
                if matches:
                    counts[label][category] += matches
                    files_seen[label].add(rel)

    for _, label in names:
        rows.append(
            _survey_row([label] + [str(counts[label][col]) for col in columns[1:]])
        )

    return "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rename module names codemod.")
    parser.add_argument("--root", type=Path, help="repository root")
    parser.add_argument("--table", type=Path, help="path to kaine/legacy_names.py")
    parser.add_argument(
        "--scope",
        action="append",
        help="comma-separated scope names (repeatable)",
    )
    parser.add_argument(
        "--only",
        action="append",
        help="comma-separated old keys to process (repeatable)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--survey", action="store_true")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parents[1] if script_dir.parts else Path.cwd()
    table_path = args.table or repo_root / "kaine" / "legacy_names.py"
    root = args.root or repo_root

    try:
        table = load_table(table_path)
    except TableError as exc:
        print(f"rename_modules: table: {exc}", file=sys.stderr)
        return 2

    all_scopes = set(getattr(table, "SCOPES", ()))
    if args.scope:
        scopes: set[str] = set()
        for part in args.scope:
            for s in part.split(","):
                s = s.strip()
                if s not in all_scopes:
                    print(f"rename_modules: unknown scope {s!r}", file=sys.stderr)
                    return 2
                scopes.add(s)
    else:
        scopes = set(all_scopes)

    only: set[str] | None = None
    if args.only:
        only = set()
        allowed = set(getattr(table, "MODULES", {}).keys()) | set(
            getattr(table, "DEVELOPMENTAL", {}).keys()
        )
        for part in args.only:
            for n in part.split(","):
                n = n.strip()
                if n not in allowed:
                    print(f"rename_modules: unknown name {n!r}", file=sys.stderr)
                    return 2
                only.add(n)

    if args.survey:
        try:
            print(survey(root, table), end="")
        except RootError as exc:
            print(f"rename_modules: root: {exc}", file=sys.stderr)
            return 2
        return 0

    try:
        rename_plan = plan(root, table, scopes, only)
    except RootError as exc:
        print(f"rename_modules: root: {exc}", file=sys.stderr)
        return 2

    if args.apply:
        try:
            apply_plan(root, rename_plan)
        except PlanError as exc:
            print(render_report(rename_plan, "apply"), end="")
            print(f"rename_modules: {exc}", file=sys.stderr)
            return 2
        mode = "apply"
    elif args.check:
        mode = "check"
    else:
        mode = "dry-run"

    print(render_report(rename_plan, mode), end="")
    if args.check and (
        rename_plan.moves or any(r.changes for r in rename_plan.results.values())
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
