# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from pathlib import Path

from kaine.lifecycle.divergence import assess_divergence


def _write_individuation(eval_root: Path, *, significant: bool) -> None:
    d = eval_root / "individuation"
    d.mkdir(parents=True, exist_ok=True)
    report = {
        "ts": "2026-06-07T00:00:00+00:00",
        "metric": "cosine_divergence",
        "fork_divergence": 0.42,
        "p_value": 0.0 if significant else 0.9,
        "significant": significant,
    }
    (d / "report.jsonl").write_text(json.dumps(report) + "\n", encoding="utf-8")


def _write_self_model(
    state_root: Path, *, drift_count: int, identity_history: list[dict]
) -> None:
    d = state_root / "eidolon"
    d.mkdir(parents=True, exist_ok=True)
    model = {
        "name": "Kaine Nova",
        "values": [],
        "behavioral_norms": [],
        "capability_map": {},
        "personality_baseline": {},
        "identity_history": identity_history,
        "drift_count": drift_count,
        "internal_speech_count": 0,
        "external_speech_count": 0,
        "voice_observations": [],
    }
    (d / "self_model.json").write_text(json.dumps(model), encoding="utf-8")


def test_diverged_from_significant_individuation(tmp_path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    _write_individuation(eval_root, significant=True)
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is True
    assert a.signals["individuation_significant"] is True
    assert "DIVERGED" in a.summary


def test_not_diverged_from_nonsignificant(tmp_path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    _write_individuation(eval_root, significant=False)
    _write_self_model(state_root, drift_count=0, identity_history=[])
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is False
    assert "NOT DIVERGED" in a.summary


def test_diverged_from_eidolon_drift(tmp_path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    _write_self_model(
        state_root, drift_count=2, identity_history=[{"at": "x"}, {"at": "y"}]
    )
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is True
    assert a.signals["eidolon_drift_signal"] is True


def test_drift_without_history_is_not_diverged(tmp_path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    _write_self_model(state_root, drift_count=3, identity_history=[])
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is False


def test_diverged_from_adapters_present(tmp_path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    adapters = state_root / "hypnos" / "adapters"
    adapters.mkdir(parents=True, exist_ok=True)
    (adapters / "voice_lora.bin").write_bytes(b"weights")
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is True
    assert a.signals["hypnos_adapters_present"] is True


def test_unsure_when_nothing_found(tmp_path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged is False
    assert "COULD NOT CONFIRM" in a.summary
    assert "treat the entity as mature" in a.summary.lower()


def test_newest_report_wins(tmp_path):
    import os
    import time

    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    d = eval_root / "individuation"
    d.mkdir(parents=True, exist_ok=True)
    old = d / "old.jsonl"
    old.write_text(json.dumps({"significant": True}) + "\n", encoding="utf-8")
    time.sleep(0.01)
    new = d / "new.jsonl"
    new.write_text(json.dumps({"significant": False}) + "\n", encoding="utf-8")
    # Ensure mtimes differ in the expected order.
    os.utime(old, (time.time() - 100, time.time() - 100))
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.signals["individuation_significant"] is False


def test_never_raises_on_garbage(tmp_path):
    state_root = tmp_path / "state"
    eval_root = tmp_path / "data" / "evaluation"
    d = eval_root / "individuation"
    d.mkdir(parents=True, exist_ok=True)
    (d / "bad.jsonl").write_text("not json at all\n{partial", encoding="utf-8")
    (state_root / "eidolon").mkdir(parents=True, exist_ok=True)
    (state_root / "eidolon" / "self_model.json").write_text("{broken", encoding="utf-8")
    a = assess_divergence(state_root=state_root, eval_root=eval_root)
    assert a.diverged in (True, False)  # did not raise
