# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared helpers for the controlled instrument runners.

A single seeded-JSONL writer (re-exported from the benchmarks package) and a
shared verdict-summary formatter so all three runners persist and render results
identically.
"""
from __future__ import annotations

from typing import Any

from kaine.evaluation.benchmarks import write_jsonl
from kaine.experiment.verdict import Outcome

__all__ = ["write_jsonl", "format_verdict_summary"]


def format_verdict_summary(
    *,
    title: str,
    config_line: str,
    metric_lines: list[str],
    verdict: dict[str, Any],
    win_note: str,
    null_note: str,
) -> str:
    """Render the shared header/separator/metric-lines/VERDICT block.

    The three controlled instrument runners share an identical summary shape: a
    title, a ``=``-rule, a one-line config echo, a list of metric lines, then a
    ``VERDICT:`` line and a WIN/NULL explanatory note. Callers supply only the
    parts that differ.
    """
    lines = [title, "=" * 60, config_line, *metric_lines]
    lines.append(f"VERDICT: {verdict['outcome']} — {verdict['detail']}")
    if verdict["outcome"] == Outcome.WIN.value:
        lines.append(win_note)
    else:
        lines.append(null_note)
    return "\n".join(lines)
