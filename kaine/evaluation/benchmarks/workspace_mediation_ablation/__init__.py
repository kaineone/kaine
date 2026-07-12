# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace-mediation ablation (the paper's primary experiment).

Runs the system as built (competitive workspace on) against a matched fan-in
prompt-assembler control (workspace off), under matched seed / stimulus /
modules, and measures whether routing modules through the competitive workspace
does work that flat concatenation of the same module outputs does not.

Primary evidence is trajectory structure — cross-module error coupling
(Soma<->Chronos error correlation) and coalition-selection structure (source
entropy); language-organ output divergence is secondary confirmation. Verdicts
resolve WIN / NULL (prompt-assembler) / NEGATIVE, all reachable.

This is NOT the oscillatory ablation (a different mechanism, a sibling package):
that toggles the precision/coherence layer inside selection; this toggles whether
the language organ is conditioned by the competitive coalition or by a flat
rendering of the same module outputs. No module internals are modified.
"""
from __future__ import annotations
