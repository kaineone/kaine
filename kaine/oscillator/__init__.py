# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-module neural-oscillation layer (oscillatory-binding capability).

Each KAINE module may carry a small leaky integrate-and-fire (LIF) population
whose spiking rhythm is summarised by a single **phase** value. Syneidesis
reads these phases to compute the phase-locking value (PLV) among the modules
contributing to a candidate coalition and applies a bounded coherence
multiplier to the coalition's aggregate salience (see
``kaine/workspace/coherence.py``).

The real oscillator (`ModuleOscillator`) is backed by snnTorch, imported
lazily so this package imports cleanly when snnTorch is absent; in that case
the module reports the neutral phase and the coherence factor degrades to 1.0.
`FakeOscillator` is a deterministic, dependency-free stand-in used by the test
suite and by any environment without the `[oscillator]` extra installed.
"""
from __future__ import annotations

from kaine.oscillator.module_oscillator import (
    NEUTRAL_PHASE,
    FakeOscillator,
    ModuleOscillator,
    OscillatorProtocol,
    make_oscillator,
    neutral_phase,
    snntorch_available,
)

__all__ = [
    "NEUTRAL_PHASE",
    "FakeOscillator",
    "ModuleOscillator",
    "OscillatorProtocol",
    "make_oscillator",
    "neutral_phase",
    "snntorch_available",
]
