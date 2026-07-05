# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""SpotConfig.from_section — defaults, per-module overrides, unknown-key reject."""
from __future__ import annotations

import pytest

from kaine.cycle.spot import SpotConfig


def test_defaults():
    cfg = SpotConfig.from_section({})
    assert cfg.enabled is False
    assert cfg.poll_interval_s == 2.0
    assert cfg.heartbeat_timeout_s == 60.0
    assert cfg.max_restart_attempts == 5
    assert cfg.restart_backoff_s == 3.0
    assert cfg.per_module_timeout_s == {}


def test_overrides_and_per_module():
    cfg = SpotConfig.from_section(
        {
            "enabled": True,
            "poll_interval_s": 1.5,
            "heartbeat_timeout_s": 90.0,
            "max_restart_attempts": 3,
            "restart_backoff_s": 5.0,
            "per_module_timeout_s": {"lingua": 120.0, "nous": 200},
        }
    )
    assert cfg.enabled is True
    assert cfg.poll_interval_s == 1.5
    assert cfg.heartbeat_timeout_s == 90.0
    assert cfg.max_restart_attempts == 3
    assert cfg.restart_backoff_s == 5.0
    assert cfg.per_module_timeout_s == {"lingua": 120.0, "nous": 200.0}


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        SpotConfig.from_section({"enabled": False, "bogus": 1})
