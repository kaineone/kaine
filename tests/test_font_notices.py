# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The vendored dashboard fonts are credited in THIRD_PARTY_LICENSES.md and ship their licence files."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = ROOT / "kaine" / "dashboard" / "static" / "fonts"
NOTICES = ROOT / "THIRD_PARTY_LICENSES.md"
FONT_SUFFIXES = (".woff2", ".woff", ".ttf", ".otf")


def _expand_braces(path: str) -> list[str]:
    match = re.search(r"\{([^}]+)\}", path)
    if not match:
        return [path]
    prefix = path[: match.start()]
    suffix = path[match.end() :]
    return [prefix + item.strip() + suffix for item in match.group(1).split(",")]


def _font_rows() -> list[tuple[list[str], str, str]]:
    rows: list[tuple[list[str], str, str]] = []
    text = NOTICES.read_text(encoding="utf-8-sig")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 6:
            continue
        font_cell = cells[2]
        licence_cell = cells[4]

        font_paths = []
        for quoted in re.findall(r"`([^`]+)`", font_cell):
            if not quoted.startswith("kaine/dashboard/static/fonts/"):
                continue
            if not any(quoted.endswith(suffix) for suffix in FONT_SUFFIXES):
                continue
            font_paths.extend(_expand_braces(quoted))

        if not font_paths:
            continue

        licence_match = re.search(r"`([^`]+)`", licence_cell)
        if not licence_match:
            raise AssertionError(
                f"Row for font {font_paths[0]!r} is missing a licence path in its licence cell"
            )
        licence_path = licence_match.group(1)

        copyright_match = re.search(r'"([^"]+)"', licence_cell)
        if not copyright_match:
            raise AssertionError(
                f"Row for font {font_paths[0]!r} is missing a copyright line in its licence cell"
            )
        copyright_line = copyright_match.group(1)

        rows.append((font_paths, licence_path, copyright_line))

    return rows


def _check_full_licence_text(text: str, licence_path: str) -> str | None:
    """Return an error message if the SIL OFL text is incomplete or out of order."""
    markers = [
        "SIL OPEN FONT LICENSE Version 1.1",
        "PREAMBLE",
        "DEFINITIONS",
    ]
    pos = 0
    for marker in markers:
        idx = text.find(marker, pos)
        if idx == -1:
            return f"Licence file missing or out-of-order {marker!r}: {licence_path}"
        pos = idx + len(marker)

    permission_match = re.search(
        r"PERMISSION (?:&|AND) CONDITIONS", text[pos:]
    )
    if not permission_match:
        return (
            f"Licence file missing or out-of-order PERMISSION &/AND CONDITIONS heading: "
            f"{licence_path}"
        )
    pos = pos + permission_match.end()

    for cond in ("1)", "2)", "3)", "4)", "5)"):
        idx = text.find(cond, pos)
        if idx == -1:
            return (
                f"Licence file missing or out-of-order condition {cond!r} "
                f"after PERMISSION heading: {licence_path}"
            )
        pos = idx + len(cond)

    for marker in ("TERMINATION", "DISCLAIMER"):
        idx = text.find(marker, pos)
        if idx == -1:
            return f"Licence file missing or out-of-order {marker} section: {licence_path}"
        pos = idx + len(marker)

    return None


def test_every_font_file_is_credited():
    credited = set()
    for font_paths, _licence_path, _copyright in _font_rows():
        credited.update(font_paths)

    on_disk = {
        path.relative_to(ROOT).as_posix()
        for path in FONTS_DIR.rglob("*")
        if path.is_file() and path.suffix in FONT_SUFFIXES
    }

    uncredited = sorted(on_disk - credited)
    assert not uncredited, f"Uncredited font files: {uncredited}"


def test_every_listed_font_file_exists():
    missing = [
        path
        for font_paths, _licence_path, _copyright in _font_rows()
        for path in font_paths
        if not (ROOT / path).exists()
    ]
    assert not missing, f"Missing listed font files: {missing}"


def test_every_font_is_covered_by_its_licence_file():
    errors = []
    for _font_paths, licence_path, expected_copyright in _font_rows():
        licence_file = ROOT / licence_path
        if not licence_file.exists():
            errors.append(f"Licence file missing: {licence_path}")
            continue
        if licence_file.parent != FONTS_DIR:
            errors.append(f"Licence file not in fonts directory: {licence_path}")
            continue

        text = licence_file.read_text(encoding="utf-8-sig")
        non_empty_lines = [
            line.strip() for line in text.splitlines() if line.strip()
        ]
        if not non_empty_lines:
            errors.append(f"Licence file is empty: {licence_path}")
            continue
        if non_empty_lines[0] != expected_copyright:
            errors.append(
                f"Copyright mismatch in {licence_path}: "
                f"{non_empty_lines[0]!r} != {expected_copyright!r}"
            )

        error = _check_full_licence_text(text, licence_path)
        if error:
            errors.append(error)

    assert not errors, "\n".join(errors)


def test_font_rows_parse():
    rows = _font_rows()
    assert rows, "No font rows parsed from THIRD_PARTY_LICENSES.md"
