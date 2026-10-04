# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Smoke test for the offline individuation validation simulator."""

import importlib.util
from pathlib import Path


def _load_simulate():
    repo = Path(__file__).resolve().parents[1]
    path = repo / "openspec" / "changes" / "individuation-rebuild" / "validation" / "simulate.py"
    spec = importlib.util.spec_from_file_location("simulate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_size_smoke():
    mod = _load_simulate()
    result = mod.run_size(N=20, seed=42, workers=1, sigma=1.0)
    assert result["experiment"] == "size"
    assert 0.0 <= result["alpha05"]["rate"] <= 1.0
    assert 0.0 <= result["alpha01"]["rate"] <= 1.0
    assert "pass" in result["alpha05"]
    assert "pass" in result["alpha01"]
    assert "pass" in result["ks_check"]
    assert 0.0 <= result["mean_within_prompt_cosine"] <= 1.0


def test_lifetime_smoke():
    mod = _load_simulate()
    result = mod.run_lifetime(L=5, looks=5, seed=42, workers=1, sigma=1.0)
    assert result["experiment"] == "lifetime"
    for rule in ("instrument", "naive", "old_percentile"):
        for look in (10, 50, 100):
            if look > result["parameters"]["looks"]:
                continue
            rate = result[rule]["by_look"][str(look)]["rate"]
            assert 0.0 <= rate <= 1.0
    assert 0.0 <= result["mean_within_prompt_cosine"] <= 1.0
    assert "pass" in result["instrument"]
