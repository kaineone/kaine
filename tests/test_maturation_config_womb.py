# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Womb timing knobs in MaturationConfig."""

from __future__ import annotations

from kaine.lifecycle.maturation_gate import MaturationConfig


def test_womb_timing_defaults() -> None:
    cfg = MaturationConfig()
    assert cfg.womb_ready_retry_seconds == 5.0
    assert cfg.womb_check_seconds == 1.0
    assert cfg.womb_loss_after_seconds == 5.0
    assert cfg.womb_arm_timeout_seconds == 120.0
    assert cfg.womb_presence_window_seconds == 3.0


def test_womb_timing_from_dict() -> None:
    cfg = MaturationConfig.from_dict(
        {
            "womb_ready_retry_seconds": 7.5,
            "womb_check_seconds": 2.0,
            "womb_loss_after_seconds": 10.0,
            "womb_arm_timeout_seconds": 300.0,
            "womb_presence_window_seconds": 6.0,
        }
    )
    assert cfg.womb_ready_retry_seconds == 7.5
    assert cfg.womb_check_seconds == 2.0
    assert cfg.womb_loss_after_seconds == 10.0
    assert cfg.womb_arm_timeout_seconds == 300.0
    assert cfg.womb_presence_window_seconds == 6.0
