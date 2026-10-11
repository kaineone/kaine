# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kaine.config import load_kaine_config
from kaine.cycle.individuation_runtime import IndividuationConfig
from kaine.modules.lingua import Lingua

_SELF_MODEL = {"values": ["a"], "behavioral_norms": ["b"], "situation_facts": ["fact"]}


def _lingua(temperature: float) -> Lingua:
    return Lingua(
        MagicMock(),
        chat_client=MagicMock(),
        intent_log=MagicMock(),
        temperature=temperature,
    )


def test_probe_request_uses_the_probe_temperature():
    lingua = _lingua(0.7)
    req = lingua.probe_request(
        about="hello", seed=1, max_tokens=16, self_model=_SELF_MODEL
    )
    assert req.temperature == 0.0

    lingua.set_probe_temperature(0.3)
    req = lingua.probe_request(
        about="hello", seed=1, max_tokens=16, self_model=_SELF_MODEL
    )
    assert req.temperature == 0.3


def test_probe_conditions_do_not_follow_the_voice_temperature():
    hot = _lingua(0.7)
    cold = _lingua(0.0)
    assert hot.probe_conditions() == cold.probe_conditions()
    assert hot.probe_conditions()["temperature"] == 0.0


def test_set_probe_temperature_validates():
    lingua = _lingua(0.7)
    for bad in (-0.1, float("nan"), True, "0"):
        with pytest.raises(ValueError):
            lingua.set_probe_temperature(bad)


def test_shipped_probe_temperature_is_greedy():
    cfg = IndividuationConfig.from_dict(
        load_kaine_config(operator_path="/nonexistent-operator-for-tests.toml")[
            "individuation"
        ]
    )
    assert cfg.probe_temperature == 0.0


def test_config_probe_temperature_validation():
    assert (
        IndividuationConfig.from_dict({"probe_temperature": 0.2}).probe_temperature == 0.2
    )

    for bad in (-1, float("inf"), True, "x"):
        with pytest.raises(ValueError):
            IndividuationConfig.from_dict({"probe_temperature": bad})
