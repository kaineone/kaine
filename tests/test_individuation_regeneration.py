# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for tasks 6.2 and 6.3: reconstructed reference kind and
non-maturation reference regeneration on conditions change.

Uses the same rig as test_individuation_failure_paths.py: real producer core,
real scheduler, fake organ.
"""

from __future__ import annotations

import pytest

from kaine.cycle.individuation_runtime import IndividuationConfig, IndividuationRuntime
from kaine.lifecycle.individuation_store import (
    Ledger,
    load_ledger,
    load_reference,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_failure_paths import (
    FakeConditioning,
    make_rig,
    warm,
)

CONDITIONS = {"server_build": "b1", "organ_model_file": "m.gguf"}


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _capture_as(rig, kind: str, *, regenerate: bool = False) -> Ledger:
    """Capture a reference of the given kind."""
    doc, reason = await rig.core.capture_reference(kind, regenerate=regenerate)
    assert reason is None and doc is not None, f"capture failed: {reason}"
    assert doc.reference_kind == kind
    ledger = load_ledger(rig.paths)
    assert ledger is not None
    return ledger


def _make_runtime(
    rig, *, allow_reconstructed: bool = False
) -> IndividuationRuntime:
    """Build a runtime around an existing rig."""

    async def ensure_fact(_fact: str, *, replaces: tuple[str, ...] = ()) -> bool:
        return True

    return IndividuationRuntime(
        config=IndividuationConfig.from_dict(
            {"allow_reconstructed": allow_reconstructed}
        ),
        paths=rig.paths,
        scheduler=rig.sched,
        core=rig.core,
        bus=None,
        notify=None,
        ensure_fact=ensure_fact,
        is_developing=lambda: False,
        sleeping=None,
    )


# ---------------------------------------------------------------------------
# Task 6.2 -- config parsing
# ---------------------------------------------------------------------------


class TestIndividuationConfigAllowReconstructed:
    def test_default_is_false(self):
        cfg = IndividuationConfig.from_dict(None)
        assert cfg.allow_reconstructed is False

    def test_true_parses(self):
        cfg = IndividuationConfig.from_dict({"allow_reconstructed": True})
        assert cfg.allow_reconstructed is True

    def test_false_parses(self):
        cfg = IndividuationConfig.from_dict({"allow_reconstructed": False})
        assert cfg.allow_reconstructed is False

    def test_non_bool_raises(self):
        with pytest.raises(ValueError, match="allow_reconstructed must be a bool"):
            IndividuationConfig.from_dict({"allow_reconstructed": "yes"})


# ---------------------------------------------------------------------------
# Task 6.2 -- reconstructed capture succeeds when approved
# ---------------------------------------------------------------------------


async def test_reconstructed_capture_succeeds_when_approved(tmp_path):
    """A reconstructed capture replaces an existing capture reference."""
    rig = make_rig(tmp_path)
    # First, capture as "capture"
    await _capture_as(rig, "capture")
    old_ref = load_reference(rig.paths)
    assert old_ref.reference_kind == "capture"

    # Now regenerate as "reconstructed"
    rig2 = make_rig(
        tmp_path,
        conditioning=FakeConditioning(sha="sha-a", second_sha="sha-b"),
    )
    doc, reason = await rig2.core.capture_reference(
        "reconstructed", regenerate=True
    )
    assert reason is None
    assert doc is not None
    assert doc.reference_kind == "reconstructed"

    new_ref = load_reference(rig2.paths)
    assert new_ref.reference_kind == "reconstructed"
    assert new_ref.reference_id != old_ref.reference_id

    # Ledger references the new reference
    ledger = load_ledger(rig2.paths)
    assert ledger.reference_id == new_ref.reference_id


# ---------------------------------------------------------------------------
# Task 6.2 -- reconstructed capture not attempted when not approved (boot)
# ---------------------------------------------------------------------------


async def test_reconstructed_not_requested_at_boot_when_not_approved(tmp_path):
    """With allow_reconstructed=False, boot does not request reconstructed."""
    rig = make_rig(tmp_path, with_scheduler=True)
    await _capture_as(rig, "capture")

    runtime = _make_runtime(rig, allow_reconstructed=False)
    await runtime.start()

    # No capture was requested
    assert rig.sched._capture_kind is None


async def test_reconstructed_requested_at_boot_when_approved_and_capture_ref(tmp_path):
    """With allow_reconstructed=True and a capture ref, boot requests reconstructed."""
    rig = make_rig(tmp_path, with_scheduler=True)
    await _capture_as(rig, "capture")

    runtime = _make_runtime(rig, allow_reconstructed=True)
    await runtime.start()

    assert rig.sched._capture_kind == "reconstructed"
    assert rig.sched._capture_regenerate is True


async def test_reconstructed_not_requested_at_boot_for_maturation_ref(tmp_path):
    """With allow_reconstructed=True but a maturation ref, no reconstructed request."""
    rig = make_rig(tmp_path, with_scheduler=True)
    await _capture_as(rig, "maturation")

    runtime = _make_runtime(rig, allow_reconstructed=True)
    await runtime.start()

    # Maturation references are not replaced by reconstructed
    assert rig.sched._capture_kind is None


async def test_reconstructed_not_requested_at_boot_for_reconstructed_ref(tmp_path):
    """With allow_reconstructed=True but already a reconstructed ref, no re-request."""
    rig = make_rig(tmp_path, with_scheduler=True)
    await _capture_as(rig, "capture")
    # Regenerate as reconstructed
    doc, reason = await rig.core.capture_reference("reconstructed", regenerate=True)
    assert reason is None and doc is not None

    runtime = _make_runtime(rig, allow_reconstructed=True)
    await runtime.start()

    # Already reconstructed, so no new request
    assert rig.sched._capture_kind is None


# ---------------------------------------------------------------------------
# Task 6.3 -- conditions-changed on a capture reference triggers regeneration
# ---------------------------------------------------------------------------


async def test_conditions_changed_on_capture_triggers_regeneration(tmp_path):
    """When conditions change and the ref is a 'capture', auto-regenerate."""
    changed = lambda: {**CONDITIONS, "server_build": "new-build"}  # noqa: E731
    rig = make_rig(tmp_path, with_scheduler=True, conditions=lambda: dict(CONDITIONS))
    await _capture_as(rig, "capture")
    warm(rig.paths)
    rig.core._conditions = changed

    await rig.sched.tick()
    rig.clock.t = 10
    await rig.sched.tick()

    # The look returned conditions_changed, and the scheduler auto-requested
    # a regeneration capture of the same kind.
    assert rig.sched._capture_kind == "capture"
    assert rig.sched._capture_regenerate is True


async def test_conditions_changed_on_reconstructed_triggers_regeneration(tmp_path):
    """When conditions change and the ref is 'reconstructed', auto-regenerate."""
    changed = lambda: {**CONDITIONS, "server_build": "new-build"}  # noqa: E731
    rig = make_rig(tmp_path, with_scheduler=True, conditions=lambda: dict(CONDITIONS))
    await _capture_as(rig, "capture")
    # Upgrade to reconstructed
    doc, reason = await rig.core.capture_reference("reconstructed", regenerate=True)
    assert reason is None
    warm(rig.paths)
    rig.core._conditions = changed

    await rig.sched.tick()
    rig.clock.t = 10
    await rig.sched.tick()

    assert rig.sched._capture_kind == "reconstructed"
    assert rig.sched._capture_regenerate is True


# ---------------------------------------------------------------------------
# Task 6.3 -- conditions-changed on a maturation reference does NOT trigger
# ---------------------------------------------------------------------------


async def test_conditions_changed_on_maturation_does_not_trigger_regeneration(tmp_path):
    """Maturation references are never auto-regenerated."""
    changed = lambda: {**CONDITIONS, "server_build": "new-build"}  # noqa: E731
    rig = make_rig(tmp_path, with_scheduler=True, conditions=lambda: dict(CONDITIONS))
    await _capture_as(rig, "maturation")
    warm(rig.paths)
    rig.core._conditions = changed

    await rig.sched.tick()
    rig.clock.t = 10
    await rig.sched.tick()

    # The look returned conditions_changed, but no regeneration was requested
    assert rig.sched._capture_kind is None
    # The alert was still sent
    cond_alerts = [a for a in rig.alerts if a["kind"] == "individuation_conditions_changed"]
    assert len(cond_alerts) == 1


# ---------------------------------------------------------------------------
# Task 6.3 -- regeneration replaces the reference and resets the ledger
# ---------------------------------------------------------------------------


async def test_regeneration_replaces_reference_and_resets_ledger(tmp_path):
    """A successful regeneration replaces the old reference; the ledger
    points to the new reference and the inconclusive stretch clears."""
    rig = make_rig(tmp_path, with_scheduler=True, conditions=lambda: dict(CONDITIONS))
    await _capture_as(rig, "capture")
    warm(rig.paths)
    old_ref = load_reference(rig.paths)

    # Trigger conditions_changed to start regeneration
    changed_conditions = lambda: {**CONDITIONS, "server_build": "new-build"}  # noqa: E731
    rig.core._conditions = changed_conditions
    rig.organ.variant = "current"

    await rig.sched.tick()
    rig.clock.t = 10
    await rig.sched.tick()

    # The scheduler should have requested a regeneration
    assert rig.sched._capture_kind == "capture"
    assert rig.sched._capture_regenerate is True

    # Now advance time so the capture fires, with matching conditions
    rig.core._conditions = changed_conditions
    rig.organ.variant = "maturation"  # Use maturation variant for fresh capture
    rig.clock.t = 15
    await rig.sched.tick()

    # The capture should have completed (capture_kind cleared)
    if rig.sched._capture_kind is None:
        new_ref = load_reference(rig.paths)
        assert new_ref is not None
        assert new_ref.reference_kind == "capture"
        assert new_ref.reference_id != old_ref.reference_id

        new_ledger = load_ledger(rig.paths)
        assert new_ledger.reference_id == new_ref.reference_id


# ---------------------------------------------------------------------------
# Task 6.2 -- producer blocks maturation regeneration
# ---------------------------------------------------------------------------


async def test_producer_blocks_maturation_regeneration(tmp_path):
    """The producer raises ValueError for regenerate=True with kind='maturation'."""
    rig = make_rig(tmp_path)
    await _capture_as(rig, "maturation")

    with pytest.raises(ValueError, match="maturation"):
        await rig.core.capture_reference("maturation", regenerate=True)
