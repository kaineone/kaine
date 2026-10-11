# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaine.lifecycle.divergence import assess_divergence
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    Ledger,
    ProbeSample,
    ReferenceDoc,
    battery_digest_of,
    build_report,
    conditioning_digest,
    report_sink,
    save_ledger,
    save_reference,
)
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    set_state_encryptor,
)


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _paths(state_root: Path) -> IndividuationPaths:
    return IndividuationPaths(root=state_root / "individuation")


def _empty_digest() -> str:
    return conditioning_digest(adapter_sha=None, values=[], norms=[])


def _write_reference(state_root: Path, kind: str = "birth") -> ReferenceDoc:
    paths = _paths(state_root)
    ref_id = uuid.uuid4().hex
    battery = ("p1", "p2")
    conditioning = {
        "adapter_sha": "none",
        "identity_values": [],
        "identity_norms": [],
    }
    def _sample(text: str, seed: int) -> ProbeSample:
        return ProbeSample(text=text, seed=seed, finish_reason="stop", completion_tokens=1)

    ref = ReferenceDoc(
        reference_id=ref_id,
        reference_kind=kind,
        captured_at=datetime.now(timezone.utc).isoformat(),
        born_at=None,
        battery=battery,
        battery_digest=battery_digest_of(battery),
        conditions={},
        conditioning=conditioning,
        samples=(
            (_sample("r1a", 1), _sample("r1b", 2)),
            (_sample("r2a", 3), _sample("r2b", 4)),
        ),
    )
    save_reference(paths, ref)
    return ref


def _write_ledger(
    state_root: Path, ref: ReferenceDoc | None = None, **fields
) -> None:
    paths = _paths(state_root)
    reference_id = ref.reference_id if ref is not None else uuid.uuid4().hex
    save_ledger(paths, Ledger(reference_id=reference_id, **fields))


def _write_report(state_root: Path, **fields) -> dict:
    paths = _paths(state_root)
    rec = build_report(**fields)

    async def _run() -> None:
        sink = report_sink(paths)
        await sink.start()
        await sink.write(rec)
        await sink.stop()

    asyncio.run(_run())
    return rec


def _write_self_model(
    state_root: Path,
    *,
    drift_count: int = 0,
    identity_history: list[dict] | None = None,
) -> None:
    path = state_root / "eidolon" / "self_model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "name": "Kaine Nova",
        "values": [],
        "behavioral_norms": [],
        "drift_count": drift_count,
        "identity_history": identity_history or [],
    }
    path.write_text(__import__("json").dumps(data), encoding="utf-8")


def test_latched_ledger_means_diverged(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_ledger(
        state_root,
        ref,
        individuated=True,
        looks_completed=3,
        last_look_conditions_digest="any",
    )
    a = assess_divergence(state_root=state_root, now=datetime.now(timezone.utc))
    assert a.diverged is True
    assert a.signals["individuation_state"] == "latched"
    assert a.signals["individuation_latched"] is True
    assert "DIVERGED" in a.summary


def test_fresh_nonsignificant_report_not_diverged(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_self_model(state_root)
    digest = _empty_digest()
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest=digest,
    )
    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="scored",
        significant=False,
        p_value=0.9,
        effect_size_h=0.1,
        alpha_k=0.05,
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=1)).isoformat(),
    )
    a = assess_divergence(state_root=state_root, now=now)
    assert a.diverged is False
    assert a.signals["individuation_state"] == "not_individuated"
    assert "NOT DIVERGED" in a.summary


def test_digest_mismatch_means_stale(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_self_model(state_root)
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest="not-the-digest",
    )
    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="scored",
        significant=False,
        p_value=0.9,
        effect_size_h=0.1,
        alpha_k=0.05,
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=1)).isoformat(),
    )
    a = assess_divergence(state_root=state_root, now=now)
    assert a.diverged is False
    assert a.signals["individuation_state"] == "stale"
    assert "STALE" in a.summary


def test_old_report_means_stale(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_self_model(state_root)
    digest = _empty_digest()
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest=digest,
    )
    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="scored",
        significant=False,
        p_value=0.9,
        effect_size_h=0.1,
        alpha_k=0.05,
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=15)).isoformat(),
    )
    a = assess_divergence(state_root=state_root, now=now)
    assert a.diverged is False
    assert a.signals["individuation_state"] == "stale"


def test_inconclusive_report(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_self_model(state_root)
    digest = _empty_digest()
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest=digest,
    )
    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="inconclusive",
        inconclusive_reason="organ_resting",
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=1)).isoformat(),
    )
    a = assess_divergence(state_root=state_root, now=now)
    assert a.diverged is False
    assert a.signals["individuation_state"] == "inconclusive"
    assert "INCONCLUSIVE" in a.summary
    assert "organ_resting" in a.summary
    assert a.signals["individuation_last_inconclusive_reason"] == "organ_resting"


def test_unreadable_ledger_counts_as_diverged(tmp_path):
    state_root = tmp_path / "state"
    paths = _paths(state_root)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.ledger.write_bytes(b"not valid ledger content")
    a = assess_divergence(state_root=state_root, now=datetime.now(timezone.utc))
    assert a.diverged is True
    assert a.signals["individuation_state"] == "unreadable"
    assert "could not be read" in a.summary


def test_nothing_found_could_not_confirm(tmp_path):
    state_root = tmp_path / "state"
    a = assess_divergence(state_root=state_root, now=datetime.now(timezone.utc))
    assert a.diverged is False
    assert a.signals["individuation_state"] in ("none", "no_reference")
    assert "COULD NOT CONFIRM" in a.summary
    assert "no individuation measurement" in a.summary


def test_fresh_nonsignificant_does_not_suppress_eidolon_drift(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_self_model(state_root, drift_count=1, identity_history=[{"at": "x"}])
    digest = _empty_digest()
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest=digest,
    )
    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="scored",
        significant=False,
        p_value=0.9,
        effect_size_h=0.1,
        alpha_k=0.05,
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=1)).isoformat(),
    )
    a = assess_divergence(state_root=state_root, now=now)
    assert a.diverged is True
    assert a.signals["eidolon_drift_signal"] is True
    assert a.signals["individuation_state"] == "not_individuated"


def test_capture_reference_note(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root, kind="capture")
    _write_self_model(state_root)
    digest = _empty_digest()
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest=digest,
    )
    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="scored",
        significant=False,
        p_value=0.9,
        effect_size_h=0.1,
        alpha_k=0.05,
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=1)).isoformat(),
    )
    a = assess_divergence(state_root=state_root, now=now)
    assert a.diverged is False
    assert a.signals["individuation_reference_kind"] == "capture"
    assert "after its birth" in a.summary


def test_latched_ledger_without_reference(tmp_path):
    state_root = tmp_path / "state"
    _write_ledger(
        state_root,
        None,
        individuated=True,
        looks_completed=1,
        last_look_conditions_digest="any",
    )
    a = assess_divergence(state_root=state_root, now=datetime.now(timezone.utc))
    assert a.diverged is True
    assert a.signals["individuation_state"] == "latched"
    assert a.signals["individuation_reference_kind"] is None


def test_signals_no_old_keys(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_ledger(state_root, ref, individuated=True, looks_completed=1)
    a = assess_divergence(state_root=state_root, now=datetime.now(timezone.utc))
    assert "fork_divergence" not in a.signals
    assert "individuation_report_found" not in a.signals


def test_unreadable_reports_count_as_individuated(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_ledger(state_root, ref)

    def _broken(*_a, **_k):
        raise OSError("disk error")

    monkeypatch.setattr("kaine.lifecycle.divergence.read_reports", _broken)
    a = assess_divergence(state_root=state_root)
    assert a.diverged is True
    assert a.signals["individuation_state"] == "unreadable"
