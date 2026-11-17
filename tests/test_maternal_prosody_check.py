# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the maternal prosody checker heuristics."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "check_maternal_prosody",
    REPO_ROOT / "tools" / "maintainer" / "check_maternal_prosody.py",
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_syllable_density_low_for_simple_syllables():
    assert mod.check_syllable_density("ba ba ba")
    assert not mod.check_syllable_density("supercalifragilistic expialidocious")


def test_consonant_transient_reduction_prefers_soft():
    soft = mod.consonant_transient_reduction("aaaa mmmm llll")
    hard = mod.consonant_transient_reduction("ptkbdg ptkbdg")
    assert soft > hard
    assert mod.check_consonant_transient("aaaa mmmm llll")


def test_readability_threshold_low_for_nonsense():
    assert mod.check_readability("supercalifragilistic expialidocious")
    assert not mod.check_readability("The quick brown fox jumps over the lazy dog.")


def test_aggregate_components():
    assert mod.check_syllable_density("ma ma ma la la la")
    assert mod.check_consonant_transient("ma ma ma la la la")
    assert not mod.check_prosody("The quick brown fox jumps over the lazy dog.")


def test_cli_main_runs():
    assert mod.main(["--text", "supercalifragilistic expialidocious"]) in (0, 1)
