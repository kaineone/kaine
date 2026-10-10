# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for the entrainment/self-rhythm review fixes."""

from __future__ import annotations

import asyncio
import json
import math
import tomllib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from kaine.boot import make_soma
from kaine.cycle.gestation import GestationOwner, GestationReadoutConfig, entrainment_plv


def _soma_section() -> dict[str, Any]:
    path = Path(__file__).parents[1] / "config" / "kaine.toml"
    if path.exists():
        with path.open("rb") as f:
            return dict(tomllib.load(f).get("soma", {}))
    return {
        "self_rhythm_enabled": False,
        "self_rhythm_eta": 0.0025,
        "self_rhythm_step_hz": 20.0,
    }


def _make_osc(**kwargs: Any):
    pytest.importorskip("snntorch")
    from kaine.oscillator.module_oscillator import SelfRhythmOscillator

    return SelfRhythmOscillator(**kwargs)


def _owner(tmp_path: Path, seed: int = 0, identity: str | None = "id-a"):
    soma = MagicMock()
    if identity is not None:
        soma._self_rhythm = MagicMock()
        soma._self_rhythm.identity = identity
    else:
        soma._self_rhythm = None
    soma.self_rhythm_state.return_value = (0.0, 1.0)

    config = GestationReadoutConfig.from_dict(
        {
            "readout_period_seconds": 10.0,
            "sample_hz": 10.0,
            "withdrawal_period_seconds": 10.0,
            "withdrawal_seconds": 5.0,
            "perturbation_period_seconds": 20.0,
            "perturbation_seconds": 2.0,
            "baseline_drive_fraction": 0.5,
            "perturbation_drive_fraction": 0.75,
            "probe_jitter_fraction": 0.0,
            "entrainment_window_seconds": 300.0,
            "entrainment_band_low_hz": 0.3,
            "entrainment_band_high_hz": 2.0,
            "edge_trim_seconds": 2.0,
            "frequency_pull_floor": 0.5,
            "baseline_withdrawals": 3.0,
            "hrv_window_seconds": 10.0,
            "recovery_tolerance": 0.25,
            "recovery_cap_seconds": 30.0,
            "entrainment_replications": 1.0,
            "surrogate_count": 19.0,
        }
    )
    state_path = tmp_path / "gestation.json"
    owner = GestationOwner(
        bus=MagicMock(),
        soma=soma,
        drive=MagicMock(),
        beat_phase=lambda: 0.0,
        is_paused=lambda: False,
        config=config,
        clock=lambda: 0.0,
        seed=seed,
        state_path=state_path,
    )
    return owner, state_path


def test_make_soma_with_shipped_config():
    bus = MagicMock()
    section = _soma_section()
    soma = make_soma(bus, section, entity_clock=None)
    assert soma is not None
    assert getattr(soma, "_self_rhythm", None) is None


@pytest.mark.parametrize("eta", [-1, True])
def test_make_soma_disabled_rejects_invalid_eta(eta):
    bus = MagicMock()
    section = {"self_rhythm_enabled": False, "self_rhythm_eta": eta}
    with pytest.raises(ValueError, match="self_rhythm_eta"):
        make_soma(bus, section, entity_clock=None)


@pytest.mark.parametrize("eta", [-1, True])
def test_make_soma_enabled_rejects_invalid_eta(eta):
    bus = MagicMock()
    section = {
        "self_rhythm_enabled": True,
        "self_rhythm_step_hz": 20.0,
        "self_rhythm_eta": eta,
    }
    with patch(
        "kaine.oscillator.module_oscillator.make_self_rhythm_oscillator", return_value=MagicMock()
    ):
        with pytest.raises(ValueError, match="self_rhythm_eta"):
            make_soma(bus, section, entity_clock=None)


def test_oscillator_restore_keeps_constructor_params():
    osc1 = _make_osc(seed=1, step_hz=20.0, eta=0.0025)
    osc2 = _make_osc(seed=2, step_hz=40.0, eta=0.0)

    osc2._a = 0.11
    osc2._s = 0.88
    osc2._ln_tau = 0.5
    osc2._ext_mean = 0.1
    osc2._a_mean = 0.2
    osc2._s_mean = 0.9
    osc2._activity_sum = 123.0
    osc2._step_count = 7

    state = osc2.serialize()
    osc1.deserialize(state)

    assert osc1._eta == 0.0025
    assert osc1._step_hz == 20.0
    assert osc1._a == 0.11
    assert osc1._s == 0.88
    assert osc1._ln_tau == 0.5
    assert osc1._ext_mean == 0.1
    assert osc1._a_mean == 0.2
    assert osc1._s_mean == 0.9
    assert osc1._activity_sum == 123.0
    assert osc1._step_count == 7
    assert osc1.identity == osc2.identity


def test_oscillator_restore_refuses_structural_mismatch():
    osc1 = _make_osc(seed=1)
    original_a = osc1._a

    osc2 = _make_osc(seed=2)
    osc2._w_rec = 99.0
    state = osc2.serialize()
    osc1.deserialize(state)

    assert osc1._a == original_a
    assert osc1._w_rec != 99.0
    assert osc1.identity != osc2.identity


def test_oscillator_identity_roundtrip():
    osc = _make_osc(seed=1)
    ident = osc.identity
    state = osc.serialize()
    assert state["identity"] == ident

    osc2 = _make_osc(seed=2)
    osc2.deserialize(state)
    assert osc2.identity == ident


def test_oscillator_identities_are_unique():
    osc1 = _make_osc(seed=1)
    osc2 = _make_osc(seed=2)
    assert osc1.identity != osc2.identity
    assert len(osc1.identity) == 32
    assert len(osc2.identity) == 32


def test_gestation_readout_config_surrogate_count_validation():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict({"surrogate_count": 0})
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict({"surrogate_count": 3.5})
    cfg = GestationReadoutConfig.from_dict({"surrogate_count": 19})
    assert cfg.surrogate_count == 19.0


def test_gestation_ignores_baseline_from_other_being(tmp_path: Path):
    owner, path = _owner(tmp_path, seed=1, identity="id-a")
    path.write_text(
        json.dumps(
            {
                "self_rhythm_baseline_hz": 1.25,
                "self_rhythm_baseline_count": 5,
                "self_rhythm_baseline_key": "1:id-b",
            }
        ),
        encoding="utf-8",
    )

    owner2, _ = _owner(tmp_path, seed=1, identity="id-a")
    assert owner2._self_rhythm_baseline_hz is None
    assert owner2._self_rhythm_baseline_count == 0


def test_gestation_uses_baseline_for_same_being(tmp_path: Path):
    owner, path = _owner(tmp_path, seed=2, identity="id-c")
    path.write_text(
        json.dumps(
            {
                "self_rhythm_baseline_hz": 1.25,
                "self_rhythm_baseline_count": 5,
                "self_rhythm_baseline_key": "2:id-c",
            }
        ),
        encoding="utf-8",
    )

    owner2, _ = _owner(tmp_path, seed=2, identity="id-c")
    assert owner2._self_rhythm_baseline_hz == 1.25
    assert owner2._self_rhythm_baseline_count == 5


def test_entrainment_plv_enforces_required_surrogate_count():
    pytest.importorskip("scipy")
    sample_hz = 10.0
    t = np.arange(500) / sample_hz
    activity = np.sin(2.0 * math.pi * 1.0 * t)
    beats = np.mod(2.0 * math.pi * 1.0 * t, 2.0 * math.pi)

    surrogates_18 = [beats + 0.1 for _ in range(18)]
    plv, smax = entrainment_plv(
        activity,
        beats,
        surrogates_18,
        sample_hz,
        0.3,
        2.0,
        trim_samples=0,
        required_surrogates=19,
    )
    assert plv is not None
    assert smax is None

    surrogates_19 = [beats + 0.1 for _ in range(19)]
    plv2, smax2 = entrainment_plv(
        activity,
        beats,
        surrogates_19,
        sample_hz,
        0.3,
        2.0,
        trim_samples=0,
        required_surrogates=19,
    )
    assert plv2 is not None
    assert smax2 is not None
    assert smax2 > 0.0


def test_end_probe_resets_markers_on_exception(tmp_path: Path):
    owner, _ = _owner(tmp_path, seed=0, identity="id")
    owner._publish_probe_event = AsyncMock()

    owner._entrain_then_autonomy = True
    owner._entrainment_consecutive_passes = 5
    owner._entrainment_plv = 0.9
    owner._entrainment_plv_surrogate_max = 0.8
    owner._self_rhythm_freq_withdrawn = 1.0
    owner._frequency_pull = 0.7

    owner._probe_kind = "withdrawal"
    owner._probe_state = "withdrawal"
    owner._probe_start = 0.0
    owner._probe_end = 1.0

    async def _boom(start: float, end: float) -> None:
        raise RuntimeError("boom")

    owner._compute_withdrawal_markers = _boom

    asyncio.run(owner._end_probe(1.0))

    assert owner._entrain_then_autonomy is None
    assert owner._entrainment_consecutive_passes == 0
    assert owner._entrainment_plv is None
    assert owner._entrainment_plv_surrogate_max is None
    assert owner._self_rhythm_freq_withdrawn is None
    assert owner._frequency_pull is None
