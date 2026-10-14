# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stimulus source timing knobs in MaturationConfig."""

from __future__ import annotations

from kaine.lifecycle.maturation_gate import MaturationConfig


def test_stimulus_source_timing_defaults() -> None:
    cfg = MaturationConfig()
    assert cfg.stimulus_source_ready_retry_seconds == 5.0
    assert cfg.stimulus_source_check_seconds == 1.0
    assert cfg.stimulus_source_loss_after_seconds == 5.0
    assert cfg.stimulus_source_arm_timeout_seconds == 120.0
    assert cfg.stimulus_source_presence_window_seconds == 3.0


def test_stimulus_source_timing_from_dict() -> None:
    cfg = MaturationConfig.from_dict(
        {
            "stimulus_source_ready_retry_seconds": 7.5,
            "stimulus_source_check_seconds": 2.0,
            "stimulus_source_loss_after_seconds": 10.0,
            "stimulus_source_arm_timeout_seconds": 300.0,
            "stimulus_source_presence_window_seconds": 6.0,
        }
    )
    assert cfg.stimulus_source_ready_retry_seconds == 7.5
    assert cfg.stimulus_source_check_seconds == 2.0
    assert cfg.stimulus_source_loss_after_seconds == 10.0
    assert cfg.stimulus_source_arm_timeout_seconds == 300.0
    assert cfg.stimulus_source_presence_window_seconds == 6.0
