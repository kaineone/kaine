# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-checks that ``docs/accelerator-provisioning.md`` stays in sync with
the implementation in :mod:`kaine.wheel_index`."""

from pathlib import Path

from kaine.wheel_index import DECISION_TABLE, INDEX_ARCH_MAP

DOC_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "accelerator-provisioning.md"
)

MEMORY_STATES = ("known-discrete", "known-unified", "unknown")
PLATFORM_SECTIONS = ("### Jetson", "### AMD APU", "### Apple Silicon")


def test_decision_table_row_count() -> None:
    """The decision table in the doc has one row per DECISION_TABLE entry."""
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()
    table_lines = []
    in_section = False
    for line in lines:
        if line.startswith("### Decision table"):
            in_section = True
            continue
        if in_section and line.startswith("#"):
            break
        if in_section and line.startswith("|"):
            table_lines.append(line)
    body_lines = [line for line in table_lines if "---" not in line]
    data_rows = body_lines[1:]  # drop the header row
    assert len(data_rows) == len(DECISION_TABLE), (
        f"doc decision table has {len(data_rows)} data rows, "
        f"expected {len(DECISION_TABLE)}"
    )


def test_index_variants_in_doc() -> None:
    """Every wheel index variant in INDEX_ARCH_MAP appears in the doc table."""
    doc = DOC_PATH.read_text(encoding="utf-8")
    for url in INDEX_ARCH_MAP:
        variant = url.rsplit("/", 1)[-1]
        assert variant in doc, (
            f"wheel index variant {variant!r} (from {url!r}) is missing from the doc"
        )


def test_memory_states_in_doc() -> None:
    """The doc mentions all three memory states."""
    doc = DOC_PATH.read_text(encoding="utf-8")
    for state in MEMORY_STATES:
        assert state in doc, f"memory state {state!r} is missing from the doc"


def test_platform_sections_in_doc() -> None:
    """The doc has headings for Jetson, AMD APU, and Apple Silicon."""
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()
    heading_lines = [line for line in lines if line.startswith("#")]
    for section in PLATFORM_SECTIONS:
        assert any(section in line for line in heading_lines), (
            f"platform section heading {section!r} is missing from the doc"
        )
