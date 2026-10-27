# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The colour ramp key is retired: colour follows the hearing stage (paper A.7, Table A1)."""

import logging
import tomllib
from pathlib import Path

import pytest

from kaine.boot.perception_feed import _stimulus_source_params
from kaine.lifecycle.stage import stimulus_source_params_digest
from kaine.modules.stimulus_source_signal import StimulusSourceParams

# sha256 of the parameter record of StimulusSourceParams() before the ramp was retired.
_DEFAULTS_DIGEST = "e21261c7333394e2a22ab7f39b7e142502adb38110aa9e7e207d4158ab58396b"


def _shipped_feed() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    with config_path.open("rb") as f:
        return tomllib.load(f)["perception_feed"]


def test_shipped_config_does_not_set_the_retired_key() -> None:
    video = _shipped_feed()["stimulus_source"].get("video") or {}
    assert "colour_ramp_seconds" not in video


def test_shipped_config_yields_the_default_params() -> None:
    params = _stimulus_source_params(_shipped_feed())
    assert params.colour_ramp_seconds == 3600.0
    assert stimulus_source_params_digest(params) == _DEFAULTS_DIGEST


def test_dataclass_default_and_digest_unchanged() -> None:
    default_params = StimulusSourceParams()
    assert default_params.colour_ramp_seconds == 3600.0
    assert stimulus_source_params_digest(default_params) == _DEFAULTS_DIGEST


def test_hearing_none_leaves_the_record_and_digest_unchanged() -> None:
    from kaine.lifecycle.stored_field_names import stimulus_source_params_record

    params = StimulusSourceParams()
    assert "hearing_schedule" not in stimulus_source_params_record(params)
    assert stimulus_source_params_digest(params, hearing=None) == _DEFAULTS_DIGEST


def test_hearing_schedule_joins_the_record_and_digest() -> None:
    from kaine.lifecycle.stored_field_names import stimulus_source_params_record
    from kaine.modules.audition.hearing_band import HearingBandParams

    params = StimulusSourceParams()
    hearing = HearingBandParams()
    record = stimulus_source_params_record(params, hearing=hearing)
    assert record["hearing_schedule"] == {
        "saturation_window_seconds": 600.0,
        "min_dwell_seconds": 5400.0,
        "max_dwell_seconds": 25200.0,
        "colour": "stage/5",
    }
    with_hearing = stimulus_source_params_digest(params, hearing=hearing)
    assert with_hearing != _DEFAULTS_DIGEST
    assert stimulus_source_params_digest(params, hearing=HearingBandParams()) == with_hearing


@pytest.mark.parametrize(
    "change",
    [
        {"saturation_window_seconds": 300.0},
        {"min_dwell_seconds": 3600.0},
        {"max_dwell_seconds": 7200.0},
    ],
)
def test_digest_changes_with_each_hearing_schedule_value(change) -> None:
    from dataclasses import replace

    from kaine.modules.audition.hearing_band import HearingBandParams

    params = StimulusSourceParams()
    base = stimulus_source_params_digest(params, hearing=HearingBandParams())
    changed = stimulus_source_params_digest(params, hearing=replace(HearingBandParams(), **change))
    assert changed != base


def test_retired_key_is_accepted_with_a_warning_and_ignored(caplog) -> None:
    feed = {"stimulus_source": {"video": {"colour_ramp_seconds": 86400.0}}}
    with caplog.at_level(logging.WARNING):
        params = _stimulus_source_params(feed)
    assert params.colour_ramp_seconds == 3600.0
    assert stimulus_source_params_digest(params) == _DEFAULTS_DIGEST
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "[perception_feed.stimulus_source.video].colour_ramp_seconds is retired and ignored"
        in m
        for m in messages
    )
