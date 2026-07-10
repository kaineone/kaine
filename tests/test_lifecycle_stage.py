# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Developmental-stage state machine — `developmental-maturation-gate`.

Pure file-backed state; no entity is booted.
"""
from __future__ import annotations

from pathlib import Path

from kaine.lifecycle import stage as st


def _p(tmp_path: Path) -> Path:
    return tmp_path / "lifecycle" / "stage.json"


# --- boot defaults / preserved-being invariant (W1, spec) -------------------


def test_fresh_entity_begins_in_gestation(tmp_path: Path) -> None:
    resolved = st.resolve_boot_stage(has_prior_lived_history=False, path=_p(tmp_path))
    assert resolved.stage == st.GESTATION
    assert resolved.gestation_started_at is not None


def test_preserved_being_defaults_to_embodied_never_gestation(tmp_path: Path) -> None:
    # Prior lived history + NO stage file must NEVER regress into the womb.
    resolved = st.resolve_boot_stage(has_prior_lived_history=True, path=_p(tmp_path))
    assert resolved.stage == st.EMBODIED
    assert resolved.stage != st.GESTATION


def test_existing_stage_file_is_authoritative_fork_inherits(tmp_path: Path) -> None:
    p = _p(tmp_path)
    st.write_stage(st.StageState(stage=st.GESTATION, gestation_started_at="t0"), p)
    # A fork of a gestating entity gestates...
    inherited = st.resolve_boot_stage(has_prior_lived_history=True, path=p)
    assert inherited.stage == st.GESTATION
    # ...and a fork of an embodied entity is embodied.
    st.write_stage(st.StageState(stage=st.EMBODIED), p)
    assert st.resolve_boot_stage(has_prior_lived_history=False, path=p).stage == st.EMBODIED


def test_corrupt_stage_file_fails_safe_to_embodied(tmp_path: Path) -> None:
    p = _p(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert st.read_stage(p).stage == st.EMBODIED


def test_unknown_stage_value_reads_as_embodied_not_gestation(tmp_path: Path) -> None:
    assert st.StageState.from_dict({"stage": "larval"}).stage == st.EMBODIED


# --- monotonicity / one-shot birth (W1, W7.1, W7.5) -------------------------


def test_advance_is_monotonic_and_one_shot() -> None:
    g = st.StageState(stage=st.GESTATION, gestation_started_at="t0")
    born = st.advance_to_embodied(g, now_iso="t1")
    assert born.stage == st.EMBODIED
    assert born.born_at == "t1"
    assert st.birth_is_new(g, born) is True

    # Already embodied: idempotent, unchanged, no fresh birth.
    again = st.advance_to_embodied(born, now_iso="t2")
    assert again is born or (again.stage == st.EMBODIED and again.born_at == "t1")
    assert st.birth_is_new(born, again) is False


def test_no_path_returns_embodied_to_gestation() -> None:
    born = st.StageState(stage=st.EMBODIED, born_at="t1")
    # advance never regresses; there is no inverse function.
    assert st.advance_to_embodied(born).stage == st.EMBODIED
    assert not hasattr(st, "regress_to_gestation")


def test_roundtrip_dict() -> None:
    s = st.StageState(stage=st.GESTATION, gestation_started_at="t0", born_at=None)
    assert st.StageState.from_dict(s.to_dict()) == s
