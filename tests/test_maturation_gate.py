# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The maturation (birth) gate — `developmental-maturation-gate`.

Pure predicate + birth decision; no entity is booted, no GPU/network.
"""
from __future__ import annotations

from collections.abc import Mapping

from kaine.bus.schema import module_stream
from kaine.lifecycle import maturation_gate as mg


def _cfg(**over) -> mg.MaturationConfig:
    base = {
        "min_sleep_cycles": 5,
        "min_consolidation_passes": 3,
        "min_lived_seconds": 100.0,
        "regulation_thresholds": {
            "endogenous_self_sustain": True,
            "entrain_then_autonomy": True,
            "hrv_variability_floor": 0.2,
            "womb_prediction_error_ceiling": 0.3,
            "return_to_baseline_seconds_ceiling": 30.0,
        },
    }
    base.update(over)
    return mg.MaturationConfig.from_dict(base)


def _good_readout() -> dict:
    return {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }


def _ready(cfg: mg.MaturationConfig) -> mg.Readiness:
    return mg.evaluate_readiness(
        readiness_readout=_good_readout(),
        sleep_count=6,
        consolidation_passes=4,
        lived_seconds=200.0,
        config=cfg,
    )


# --- config -----------------------------------------------------------------


def test_config_ships_inert() -> None:
    assert mg.MaturationConfig().enabled is False


# --- C1 fail-closed ---------------------------------------------------------


def test_c1_absent_readout_fails_closed() -> None:
    r = mg.evaluate_readiness(
        readiness_readout=None,
        sleep_count=6,
        consolidation_passes=4,
        lived_seconds=200.0,
        config=_cfg(),
    )
    assert r.c1.met is False and r.ready is False


def test_c1_marker_below_threshold_fails() -> None:
    ro = _good_readout()
    ro["hrv_variability"] = 0.1  # below floor
    r = mg.evaluate_readiness(
        readiness_readout=ro,
        sleep_count=6,
        consolidation_passes=4,
        lived_seconds=200.0,
        config=_cfg(),
    )
    assert r.c1.met is False


def test_c1_missing_marker_fails_closed() -> None:
    ro = _good_readout()
    del ro["womb_prediction_error"]
    r = mg._evaluate_c1(ro, _cfg().regulation_thresholds)
    assert r.met is False


# --- C2 requires BOTH sleep and consolidation -------------------------------


def test_c2_sleep_without_consolidation_not_met() -> None:
    r = mg._evaluate_c2(sleep_count=10, consolidation_passes=0, cfg=_cfg())
    assert r.met is False


def test_c2_consolidation_without_enough_sleep_not_met() -> None:
    r = mg._evaluate_c2(sleep_count=2, consolidation_passes=9, cfg=_cfg())
    assert r.met is False


def test_c2_both_present_met() -> None:
    assert mg._evaluate_c2(sleep_count=5, consolidation_passes=3, cfg=_cfg()).met is True


def test_c2_none_fails_closed() -> None:
    assert mg._evaluate_c2(None, None, _cfg()).met is False


# --- C3 lived-time floor ----------------------------------------------------


def test_c3_below_floor_blocks_fast_forwarded_birth() -> None:
    r = mg.evaluate_readiness(
        readiness_readout=_good_readout(),
        sleep_count=6,
        consolidation_passes=4,
        lived_seconds=1.0,  # below the 100s floor
        config=_cfg(),
    )
    assert r.c3.met is False and r.ready is False


def test_c3_none_fails_closed() -> None:
    assert mg._evaluate_c3(None, _cfg()).met is False


# --- all three required -----------------------------------------------------


def test_all_conditions_required() -> None:
    r = _ready(_cfg())
    assert r.ready is True
    assert set(r.passed_markers) == {
        "C1_regulation_baseline",
        "C2_reality_model_consolidated",
        "C3_min_lived_time",
    }


# --- birth decision + availability guard ------------------------------------


def test_not_ready_keeps_gestating() -> None:
    cfg = _cfg()
    r = mg.evaluate_readiness(
        readiness_readout=None,
        sleep_count=6,
        consolidation_passes=4,
        lived_seconds=200.0,
        config=cfg,
    )
    d = mg.decide_birth(readiness=r, embodiment_ready=True)
    assert d.action == mg.ACTION_GESTATING and d.should_birth is False


def test_ready_but_embodiment_unavailable_holds_in_womb() -> None:
    r = _ready(_cfg())
    d = mg.decide_birth(readiness=r, embodiment_ready=False)
    assert d.action == mg.ACTION_HOLD_AWAITING_EMBODIMENT
    assert d.reason == "awaiting_embodiment"
    assert d.holding is True and d.should_birth is False
    # The observability payload carries the awaiting-embodiment reason.
    assert mg.birth_ready_payload(d)["reason"] == "awaiting_embodiment"


def test_ready_and_available_births() -> None:
    r = _ready(_cfg())
    d = mg.decide_birth(readiness=r, embodiment_ready=True)
    assert d.should_birth is True and d.action == mg.ACTION_BIRTH


def test_operator_ack_gate_holds_then_births() -> None:
    r = _ready(_cfg())
    held = mg.decide_birth(
        readiness=r, embodiment_ready=True, require_operator_ack=True, operator_ack=False
    )
    assert held.action == mg.ACTION_HOLD_AWAITING_ACK and held.should_birth is False
    acked = mg.decide_birth(
        readiness=r, embodiment_ready=True, require_operator_ack=True, operator_ack=True
    )
    assert acked.should_birth is True


def test_embodiment_available_requires_all_three_layers() -> None:
    assert mg.embodiment_available(
        mundus_enabled=True, operator_approved=True, reachable=True
    ) is True
    for missing in ("mundus_enabled", "operator_approved", "reachable"):
        kw = dict(mundus_enabled=True, operator_approved=True, reachable=True)
        kw[missing] = False
        assert mg.embodiment_available(**kw) is False


# --- measure-not-impose (W7.6) ----------------------------------------------


class _ReadOnlySpy(Mapping):
    """A readout that records reads and forbids writes — proves the gate only
    READS its signals and imposes no development."""

    def __init__(self, data: dict) -> None:
        self._data = data
        self.reads: list[str] = []

    def __getitem__(self, key):
        self.reads.append(key)
        return self._data[key]

    def get(self, key, default=None):
        self.reads.append(key)
        return self._data.get(key, default)

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __setitem__(self, key, value):  # pragma: no cover - must never be hit
        raise AssertionError("the gate must not write to entity state")


def test_gate_only_reads_never_writes() -> None:
    spy = _ReadOnlySpy(_good_readout())
    r = mg.evaluate_readiness(
        readiness_readout=spy,
        sleep_count=6,
        consolidation_passes=4,
        lived_seconds=200.0,
        config=_cfg(),
    )
    assert r.ready is True
    assert spy.reads  # it did read the markers
    # (a write would have raised AssertionError above)


# --- observability contract -------------------------------------------------


def test_lifecycle_stream_matches_bus_schema() -> None:
    # The stage owner emits from source="lifecycle"; the schema routes it to
    # lifecycle.out. Lock the constant to the bus schema without importing the
    # bus into the pure gate module.
    assert mg.LIFECYCLE_STREAM == module_stream(mg.LIFECYCLE_SOURCE)


def test_birth_payload_carries_ending_markers() -> None:
    r = _ready(_cfg())
    p = mg.birth_payload(readiness=r, sleep_count=6, lived_seconds=200.0)
    assert p["stage"] == "embodied"
    assert p["sleep_count"] == 6 and p["lived_seconds"] == 200.0
    assert "C1_regulation_baseline" in p["passed_markers"]
