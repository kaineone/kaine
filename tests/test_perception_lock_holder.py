# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the gestation locus lock holder in perception_state."""

from __future__ import annotations

from pathlib import Path

import pytest

from kaine.perception_state import read_desired, write_desired_locus


@pytest.fixture
def desired_path(tmp_path: Path) -> Path:
    return tmp_path / "desired.json"


def test_gestation_lock_holds_womb_against_other_writers(desired_path: Path) -> None:
    write_desired_locus("virtual", locked=True, locked_by="gestation", path=desired_path)

    # A non-gestation write (no locked_by) cannot move the locus.
    write_desired_locus("physical", path=desired_path)
    state = read_desired(desired_path)
    assert state.locus == "virtual"
    assert state.locus_locked is True
    assert state.locked_by == "gestation"

    # Another non-gestation write still cannot move it.
    write_desired_locus("off", path=desired_path)
    state = read_desired(desired_path)
    assert state.locus == "virtual"
    assert state.locus_locked is True
    assert state.locked_by == "gestation"

    # An operator-attributed write also cannot move it.
    write_desired_locus("physical", locked=False, locked_by="operator", path=desired_path)
    state = read_desired(desired_path)
    assert state.locus == "virtual"
    assert state.locus_locked is True
    assert state.locked_by == "gestation"


def test_gestation_holder_can_unlock_and_then_normal_writes_work(desired_path: Path) -> None:
    write_desired_locus("virtual", locked=True, locked_by="gestation", path=desired_path)

    write_desired_locus("physical", locked=False, locked_by="gestation", path=desired_path)
    state = read_desired(desired_path)
    assert state.locus == "physical"
    assert state.locus_locked is False
    # The unlock is recorded as the gestation holder's action (spec: the unlock
    # is attributed to gestation, not the operator).
    assert state.locked_by == "gestation"

    # After the gestation holder unlocks, normal writes apply.
    write_desired_locus("off", path=desired_path)
    assert read_desired(desired_path).locus == "off"


def test_operator_lock_behavior_unchanged(desired_path: Path) -> None:
    # Current behavior: a locked_by="operator" lock lets the locus be changed.
    write_desired_locus("physical", locked=True, locked_by="operator", path=desired_path)
    write_desired_locus("off", path=desired_path)
    state = read_desired(desired_path)
    assert state.locus == "off"
    assert state.locus_locked is True
    assert state.locked_by == "operator"


def test_unknown_locus_in_gestation_lock_resolves_to_virtual(desired_path: Path) -> None:
    desired_path.write_text(
        '{"locus": "unknown_place", "locus_locked": true, "locked_by": "gestation"}'
    )
    state = read_desired(desired_path)
    assert state.locus == "virtual"


def test_unknown_locus_when_unlocked_resolves_to_physical(desired_path: Path) -> None:
    desired_path.write_text(
        '{"locus": "unknown_place", "locus_locked": false, "locked_by": "operator"}'
    )
    state = read_desired(desired_path)
    assert state.locus == "physical"


def test_hypnos_restore_path_does_not_move_gestation_lock(desired_path: Path) -> None:
    write_desired_locus("virtual", locked=True, locked_by="gestation", path=desired_path)

    # Hypnos records the pre-sleep locus as raw string (physical, virtual, off)
    # and restores with exactly this call shape:
    pre_sleep_locus = "physical"
    write_desired_locus(pre_sleep_locus, path=desired_path)

    state = read_desired(desired_path)
    assert state.locus == "virtual"
    assert state.locus_locked is True
    assert state.locked_by == "gestation"
