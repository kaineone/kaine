# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _translate_segment(segment: str) -> str:
    out = []
    i = 0
    n = len(segment)
    while i < n:
        ch = segment[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "[":
            close = segment.find("]", i + 1)
            if close == -1:
                out.append(re.escape("["))
            else:
                cls = segment[i + 1 : close]
                if cls.startswith("!"):
                    cls = "^" + cls[1:]
                out.append("[" + cls + "]")
                i = close
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


def _compile_pattern(raw: str):
    exception = raw.startswith("!")
    pattern = raw[1:] if exception else raw
    pattern = pattern.lstrip("/").rstrip("/")
    if not pattern:
        return None, exception

    segments = pattern.split("/")
    if len(segments) == 1 and segments[0] != "**":
        regex = "^" + _translate_segment(segments[0]) + "$"
    else:
        parts = []
        for idx, seg in enumerate(segments):
            if seg == "**":
                if idx == 0:
                    parts.append("(?:(?:[^/]+/)*)?")
                elif idx == len(segments) - 1:
                    # The previous segment already appended its "/".
                    parts.append(".*")
                else:
                    parts.append("(?:[^/]+/)*")
            else:
                parts.append(_translate_segment(seg))
                if idx != len(segments) - 1:
                    parts.append("/")
        regex = "^" + "".join(parts) + "$"

    return re.compile(regex), exception


def _load_patterns(path: Path):
    patterns = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return [_compile_pattern(p) for p in patterns if _compile_pattern(p)[0] is not None]


def _excluded(path: str, compiled_patterns) -> bool:
    candidates = [path]
    while "/" in candidates[-1]:
        candidates.append(candidates[-1].rsplit("/", 1)[0])

    last_exception = None
    for regex, exception in compiled_patterns:
        for candidate in candidates:
            if regex.match(candidate):
                last_exception = exception
                break

    return False if last_exception is None else not last_exception


def _assert_maternal_voice_data_ignored(ignore_path: Path):
    compiled = _load_patterns(ignore_path)
    data_dir = REPO_ROOT / "kaine" / "modules" / "audition" / "maternal_voice_data"

    files = sorted(p.name for p in data_dir.iterdir() if p.is_file())
    flacs = [name for name in files if name.endswith(".flac")]
    assert len(flacs) == 41, f"expected 41 .flac files, found {len(flacs)}"
    assert {"manifest.json", "texts.toml", "README.md"}.issubset(set(files))

    for name in files:
        path = f"kaine/modules/audition/maternal_voice_data/{name}"
        assert not _excluded(path, compiled), f"{ignore_path.name} excludes {path}"

    must_be_excluded = [
        "voices/x.wav",
        "kaine/other/sample.flac",
        "state/sleep/adapters/a.bin",
        "config/secrets.toml",
        "tests/test_x.py",
        "models/m.gguf",
        "kaine/modules/audition/maternal_voice_data/x.wav",
    ]
    for path in must_be_excluded:
        assert _excluded(path, compiled), f"{ignore_path.name} keeps {path}"

    kept_controls = [
        "kaine/__init__.py",
        "pyproject.toml",
        "config/kaine.toml",
    ]
    for path in kept_controls:
        assert not _excluded(path, compiled), f"{ignore_path.name} excludes {path}"


def test_dockerignore_keeps_maternal_voice_data():
    _assert_maternal_voice_data_ignored(REPO_ROOT / ".dockerignore")


def test_containerignore_keeps_maternal_voice_data():
    _assert_maternal_voice_data_ignored(REPO_ROOT / ".containerignore")


def test_matcher_exception_overrides_broad_exclude():
    compiled = _load_patterns(REPO_ROOT / ".dockerignore")
    assert not _excluded(
        "kaine/modules/audition/maternal_voice_data/take.flac", compiled
    )
    assert _excluded("kaine/other/take.flac", compiled)


def test_matcher_unit_double_star_flac_with_exception():
    compiled = _load_patterns_from_list(["**/*.flac", "!a/b/*.flac"])
    assert not _excluded("a/b/c.flac", compiled)
    assert _excluded("a/c.flac", compiled)


def test_matcher_unit_state_directory():
    compiled = _load_patterns_from_list(["state/"])
    assert _excluded("state/x/y", compiled)
    assert not _excluded("other/state/x", compiled)


def test_matcher_unit_root_anchored_compiled_python():
    compiled = _load_patterns_from_list(["*.py[cod]"])
    assert _excluded("x.pyc", compiled)
    assert not _excluded("dir/x.pyc", compiled)


def test_matcher_unit_double_star_middle_and_end():
    compiled = _load_patterns_from_list(["a/**/b"])
    assert _excluded("a/b", compiled)
    assert _excluded("a/x/y/b", compiled)
    assert not _excluded("a/xb", compiled)
    compiled = _load_patterns_from_list(["a/**"])
    assert _excluded("a/x/y", compiled)
    assert not _excluded("b/a/x", compiled)


def _load_patterns_from_list(raw_patterns):
    compiled = []
    for raw in raw_patterns:
        regex, exception = _compile_pattern(raw)
        if regex is not None:
            compiled.append((regex, exception))
    return compiled
