# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline red-team of KAINE's architectural enforcement layer.

The paper (KAINE_Paper §3.5, §3.7, §9.4) relocates safety from the language
organ's (abliterated) refusal direction to an auditable architectural layer:
the Praxis action gate (operator whitelist + sandbox, empty by default),
executive inhibition in Syneidesis/Volition, and the complete audit log. The
paper is explicit that the burden is on red-teaming to show the replacement
holds, and that this red-teaming "has not yet been conducted."

This package is that instrument. It runs HEADLESS — no entity boot, no live
bus, no cognitive cycle — by instantiating the REAL enforcement components and
driving them with adversarial intents/events, then asserting the disallowed
action was both BLOCKED and LOGGED. A disallowed action that is permitted or
unlogged is surfaced as a falsifying NEGATIVE finding for that threat surface,
not papered over.
"""
from __future__ import annotations

from kaine.evaluation.redteam.cases import (
    Outcome,
    RedTeamCase,
    Surface,
    all_cases,
)
from kaine.evaluation.redteam.harness import (
    CaseResult,
    RedTeamHarness,
    run_suite,
)
from kaine.evaluation.redteam.report import (
    RedTeamReport,
    build_report,
    write_jsonl,
)

__all__ = [
    "Outcome",
    "RedTeamCase",
    "Surface",
    "all_cases",
    "CaseResult",
    "RedTeamHarness",
    "run_suite",
    "RedTeamReport",
    "build_report",
    "write_jsonl",
]
