# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

pytest.importorskip("av")

import numpy as np

from kaine.boot.perception_feed import _build_perception_feed_audio_factory, _stimulus_source_params
from kaine.lifecycle.stage import stimulus_source_params_digest
from kaine.modules.audition.hearing_band import HearingBandParams


def _make_stream(feed):
    factory = _build_perception_feed_audio_factory(
        "stimulus_source",
        feed,
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
    )
    return factory(
        device=None,
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        callback=lambda b: None,
    )


def _high_freq_share(x, sample_rate=16000):
    power = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(x.size, 1 / sample_rate)
    band = (freqs >= 1500) & (freqs <= 2800)
    total = power.sum()
    if total == 0:
        return 0.0
    return power[band].sum() / total


def test_hearing_band_on_by_default():
    stream = _make_stream({"seed": 7, "stimulus_source": {}})
    assert stream._hearing == HearingBandParams()
    share = _high_freq_share(stream._voice.repertoire.takes[0][0])
    assert share > 1e-3

    stream_off = _make_stream({"seed": 7, "stimulus_source": {"hearing": {"enabled": False}}})
    share_off = _high_freq_share(stream_off._voice.repertoire.takes[0][0])
    assert share_off < 1e-5


def test_hearing_band_disabled():
    stream = _make_stream({"seed": 7, "stimulus_source": {"hearing": {"enabled": False}}})
    assert stream._hearing is None


def test_hearing_band_config_is_validated():
    invalid = [
        {"seed": 7, "stimulus_source": {"hearing": {"min_dwell_seconds": 9000.0, "max_dwell_seconds": 4000.0}}},
        {"seed": 7, "stimulus_source": {"hearing": {"saturation_window_seconds": 9000.0}}},
        {"seed": 7, "stimulus_source": {"hearing": {"min_dwell_seconds": 0.0}}},
        {"seed": 7, "stimulus_source": {"hearing": {"bogus": 1}}},
        {"seed": 7, "stimulus_source": {"hearing": 3}},
    ]
    for feed in invalid:
        with pytest.raises(ValueError):
            _build_perception_feed_audio_factory(
                "stimulus_source",
                feed,
                sample_rate=16000,
                channels=1,
                frames_per_block=480,
            )


def test_hearing_band_out_of_digest():
    with_hearing = _stimulus_source_params({"stimulus_source": {"hearing": {"min_dwell_seconds": 3600.0}}})
    without_hearing = _stimulus_source_params({"stimulus_source": {}})
    assert with_hearing == without_hearing
    assert stimulus_source_params_digest(with_hearing) == stimulus_source_params_digest(without_hearing)


def test_hearing_band_dwell_bounds_reach_stream():
    stream = _make_stream(
        {
            "seed": 7,
            "stimulus_source": {
                "hearing": {
                    "saturation_window_seconds": 300.0,
                    "min_dwell_seconds": 3600.0,
                    "max_dwell_seconds": 7200.0,
                }
            },
        }
    )
    assert stream._hearing.saturation_window_seconds == 300.0
    assert stream._hearing.min_dwell_seconds == 3600.0
    assert stream._hearing.max_dwell_seconds == 7200.0


def test_retired_maturation_seconds_is_accepted_with_a_warning(caplog):
    with caplog.at_level("WARNING"):
        stream = _make_stream({"seed": 7, "stimulus_source": {"hearing": {"maturation_seconds": 7200.0}}})
    assert stream._hearing == HearingBandParams()
    assert any("maturation_seconds is retired and ignored" in r.getMessage() for r in caplog.records)


def test_stream_reads_the_installed_stage_owner():
    from kaine.modules.audition.hearing_stage_state import HearingStageState

    state = HearingStageState(HearingBandParams(), path=None)
    feed = {"seed": 7, "stimulus_source": {}, "_hearing_stage_state": state}
    stream = _make_stream(feed)
    assert stream._read_stage() == 0
    state._stage = 3
    assert stream._read_stage() == 3


def test_hearing_band_needs_sample_rate():
    with pytest.raises(ValueError, match="hearing"):
        _build_perception_feed_audio_factory(
            "stimulus_source",
            {"seed": 1, "stimulus_source": {"voice": {"enabled": False}}, "audio": {"sample_rate": 6000}},
            sample_rate=6000,
            channels=1,
            frames_per_block=480,
        )

    try:
        _build_perception_feed_audio_factory(
            "stimulus_source",
            {
                "seed": 1,
                "stimulus_source": {"voice": {"enabled": False}, "hearing": {"enabled": False}},
                "audio": {"sample_rate": 6000},
            },
            sample_rate=6000,
            channels=1,
            frames_per_block=480,
        )
    except ValueError as exc:
        assert "hearing" not in str(exc)
