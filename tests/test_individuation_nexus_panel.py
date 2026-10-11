# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.evaluation.config import EvaluationConfig
from kaine.evaluation.nexus_tab import _aggregate_individuation
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    Ledger,
    ProbeSample,
    ReferenceDoc,
    battery_digest_of,
    build_report,
    report_sink,
    save_ledger,
    save_reference,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from kaine.storage import set_data_root


@pytest.fixture(autouse=True)
def reset_encryptor_and_root():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    set_data_root(None)
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    set_data_root(None)


def _paths(state_root: Path) -> IndividuationPaths:
    return IndividuationPaths(root=state_root / "individuation")


def _sample(text: str, seed: int) -> ProbeSample:
    return ProbeSample(text=text, seed=seed, finish_reason="stop", completion_tokens=1)


def _write_reference(state_root: Path, kind: str = "birth") -> ReferenceDoc:
    paths = _paths(state_root)
    ref_id = uuid.uuid4().hex
    battery = ("p1", "p2")
    conditioning = {"adapter_sha": "none", "identity_values": [], "identity_norms": []}
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


def test_no_state_returns_none(tmp_path, monkeypatch):
    """When there is no individuation evidence, the panel returns None."""
    set_data_root(None)
    monkeypatch.chdir(tmp_path)
    result = _aggregate_individuation(EvaluationConfig.from_mapping({}))
    assert result is None


def test_latched_ledger_returns_latched_result(tmp_path, monkeypatch):
    """A latched ledger and reference surface only the expected scalar keys."""
    set_data_root(None)
    monkeypatch.chdir(tmp_path)
    state = Path("state")
    ref = _write_reference(state)
    _write_ledger(state, ref, individuated=True, looks_completed=1)
    result = _aggregate_individuation(EvaluationConfig.from_mapping({}))
    assert result is not None
    assert result["latched"] is True
    assert result["state"] == "latched"
    assert set(result.keys()) == {
        "state",
        "latched",
        "reference_kind",
        "reference_captured_at",
        "looks_completed",
        "outcome",
        "effect_size_h",
        "p_value",
        "alpha_k",
        "warmed_up",
        "inconclusive_reason",
        "inconclusive_since",
        "inconclusive_alerted",
    }


def test_negative_effect_size_h_is_clipped_to_zero(tmp_path, monkeypatch):
    """Effect-size H is clipped at zero for the panel."""
    set_data_root(None)
    monkeypatch.chdir(tmp_path)
    state = Path("state")
    ref = _write_reference(state)
    _write_ledger(state, ref, individuated=True, looks_completed=1)
    _write_report(
        state,
        reference_id=ref.reference_id,
        outcome="scored",
        significant=False,
        effect_size_h=-0.2,
        p_value=0.05,
        alpha_k=0.05,
        warmed_up=True,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=1,
    )
    result = _aggregate_individuation(EvaluationConfig.from_mapping({}))
    assert result is not None
    assert result["effect_size_h"] == 0.0


def test_evaluation_config_rejects_retired_individuation_table():
    """[evaluation.individuation] is rejected at parse time."""
    with pytest.raises(ValueError, match=r"\[individuation\]"):
        EvaluationConfig.from_mapping({"individuation": {"enabled": False}})


def test_shipped_config_has_no_evaluation_individuation_table():
    """The shipped config no longer carries an [evaluation.individuation] table."""
    import tomllib

    from kaine.evaluation.config import SHIPPED_CONFIG_PATH

    with open(SHIPPED_CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    assert "individuation" not in data["evaluation"]
