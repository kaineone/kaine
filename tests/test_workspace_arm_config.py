# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import types

import kaine.cycle.__main__ as cyc
from kaine.config import load_kaine_config


def test_shipped_arm_is_competitive():
    cfg = load_kaine_config(
        profile="thesis_test",
        operator_path="/nonexistent-operator-for-tests.toml",
    )
    assert cfg["syneidesis"]["arm"] == "competitive"


def test_arm_kwargs_default_and_seed():
    assert cyc._syneidesis_arm_kwargs({}, types.SimpleNamespace(seed=42)) == {
        "arm": "competitive",
        "arm_seed": 42,
    }
    assert cyc._syneidesis_arm_kwargs(
        {"arm": " Matched "}, types.SimpleNamespace(seed=7)
    ) == {"arm": "matched", "arm_seed": 7}
    assert cyc._syneidesis_arm_kwargs({"arm": "pooled"}, None) == {
        "arm": "pooled",
        "arm_seed": None,
    }
