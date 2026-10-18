# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import tomllib
from pathlib import Path

import pytest

from kaine.boot.perception_feed import _stimulus_source_params
from kaine.lifecycle.stage import stimulus_source_params_digest
from kaine.modules.stimulus_source_signal import StimulusSourceParams, colour_saturation


def _load_shipped_stimulus_source_params() -> StimulusSourceParams:
    config_path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    with config_path.open("rb") as f:
        cfg = tomllib.load(f)
    return _stimulus_source_params(cfg["perception_feed"])


@pytest.fixture
def shipped_params() -> StimulusSourceParams:
    return _load_shipped_stimulus_source_params()


def test_shipped_colour_ramp_spans_the_phase(shipped_params: StimulusSourceParams) -> None:
    late_day_colour = colour_saturation(24 * 3600.0, shipped_params)
    mid_day_colour = colour_saturation(12 * 3600.0, shipped_params)
    assert late_day_colour - mid_day_colour >= 0.05
    assert shipped_params.colour_ramp_seconds >= 6 * 3600.0


def test_dataclass_default_and_digest_unchanged() -> None:
    default_params = StimulusSourceParams()
    assert default_params.colour_ramp_seconds == 3600.0
    assert (
        stimulus_source_params_digest(default_params)
        == "e21261c7333394e2a22ab7f39b7e142502adb38110aa9e7e207d4158ab58396b"
    )
