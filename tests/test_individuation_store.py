# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import dataclasses
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.lifecycle.individuation_store import (
    DEFAULT_ROOT,
    Evidence,
    IndividuationPaths,
    IndividuationStoreError,
    Ledger,
    LedgerRegression,
    LedgerUnreadable,
    ProbeSample,
    ReferenceDoc,
    ReferenceUnreadable,
    _write_encrypted_json,
    battery_digest_of,
    build_report,
    conditioning_digest,
    copy_birth_adapter,
    individuation_evidence,
    load_ledger,
    load_reference,
    read_conditioning_inputs,
    read_reports,
    report_sink,
    save_ledger,
    save_reference,
)
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)


@pytest.fixture(autouse=True)
def reset_encryptor():
    """Reset the global encryptor to disabled after each test."""
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _enable_encryption(monkeypatch):
    """Install a random key and enable state encryption."""
    key = os.urandom(32).hex()
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))


def _make_reference(text: str = "reference sample") -> ReferenceDoc:
    battery = ("prompt one", "prompt two")
    samples = (
        (
            ProbeSample(text + " a", 1, "stop", 16),
            ProbeSample(text + " b", 2, "stop", 16),
        ),
        (
            ProbeSample(text + " c", 3, "stop", 16),
            ProbeSample(text + " d", 4, "stop", 16),
            ProbeSample(text + " e", 5, "stop", 16),
        ),
    )
    return ReferenceDoc(
        reference_id="ref-000",
        reference_kind="birth",
        captured_at="2025-01-01T00:00:00+00:00",
        born_at="2025-01-01T00:00:00+00:00",
        battery=battery,
        battery_digest=battery_digest_of(battery),
        conditions={
            "model_id": "m1",
            "temperature": 0.7,
            "max_tokens": 160,
            "think": False,
            "persona_version": "1",
            "persona_name": "test",
            "embedder_id": "e1",
            "embedder_dim": 384,
            "server_build": "b1",
        },
        conditioning={
            "adapter_sha": "sha-000",
            "identity_values": ["curiosity", "kindness"],
            "identity_norms": ["do no harm"],
        },
        samples=samples,
    )


@pytest.mark.parametrize("encrypted", [True, False])
def test_reference_roundtrip(tmp_path, monkeypatch, encrypted):
    if encrypted:
        _enable_encryption(monkeypatch)

    paths = IndividuationPaths(tmp_path / "individuation")
    doc = _make_reference("round trip sample")
    save_reference(paths, doc)

    if encrypted:
        raw = paths.reference.read_text(encoding="utf-8")
        assert "round trip sample" not in raw
        assert (paths.reference.stat().st_mode & 0o777) == 0o600

    loaded = load_reference(paths)
    assert loaded == doc


def test_reference_missing(tmp_path):
    paths = IndividuationPaths(tmp_path / "individuation")
    assert load_reference(paths) is None


def test_reference_garbage_raises(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    paths = IndividuationPaths(tmp_path / "individuation")
    paths.reference.parent.mkdir(parents=True, exist_ok=True)
    paths.reference.write_bytes(b"not encrypted anything")
    with pytest.raises(ReferenceUnreadable):
        load_reference(paths)


def test_reference_bad_battery_digest(tmp_path):
    paths = IndividuationPaths(tmp_path / "individuation")
    doc = ReferenceDoc(
        reference_id="ref-bad",
        reference_kind="birth",
        captured_at="2025-01-01T00:00:00+00:00",
        born_at=None,
        battery=("one",),
        battery_digest="bad",
        conditions={},
        conditioning={},
        samples=(
            (
                ProbeSample("a", 1, None, 1),
                ProbeSample("b", 2, None, 1),
            ),
        ),
    )
    save_reference(paths, doc)
    with pytest.raises(ReferenceUnreadable):
        load_reference(paths)


def test_ledger_roundtrip(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    paths = IndividuationPaths(tmp_path / "individuation")
    ledger = Ledger(
        reference_id="ref-ledger",
        looks_completed=3,
        alpha_spent=0.15,
        last_look_conditions_digest="digest-1",
        lived_seconds=12.5,
        lived_ticks=100,
        individuated=False,
    )
    save_ledger(paths, ledger)
    loaded = load_ledger(paths)
    assert loaded == ledger


def test_ledger_missing(tmp_path):
    paths = IndividuationPaths(tmp_path / "individuation")
    assert load_ledger(paths) is None


def test_ledger_corrupt_raises_and_blocks_overwrite(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    paths = IndividuationPaths(tmp_path / "individuation")
    paths.ledger.parent.mkdir(parents=True, exist_ok=True)
    paths.ledger.write_bytes(b"corrupt ledger bytes")
    original = paths.ledger.read_bytes()

    with pytest.raises(LedgerUnreadable):
        load_ledger(paths)

    new_ledger = Ledger(reference_id="ref-x")
    with pytest.raises(LedgerUnreadable):
        save_ledger(paths, new_ledger)

    assert paths.ledger.read_bytes() == original


@pytest.mark.parametrize(
    "mutate",
    [
        lambda old: dataclasses.replace(old, looks_completed=old.looks_completed - 1),
        lambda old: dataclasses.replace(old, alpha_spent=old.alpha_spent - 0.01),
        lambda old: dataclasses.replace(old, individuated=False),
        lambda old: dataclasses.replace(old, lived_ticks=old.lived_ticks - 1),
        lambda old: dataclasses.replace(old, lived_seconds=old.lived_seconds - 1.0),
    ],
    ids=[
        "looks_completed",
        "alpha_spent",
        "individuated",
        "lived_ticks",
        "lived_seconds",
    ],
)
def test_ledger_regression_refused(tmp_path, monkeypatch, mutate):
    _enable_encryption(monkeypatch)
    paths = IndividuationPaths(tmp_path / "individuation")
    old = Ledger(
        reference_id="old-ref",
        looks_completed=5,
        alpha_spent=0.5,
        lived_seconds=10.0,
        lived_ticks=50,
        individuated=True,
    )
    save_ledger(paths, old)

    new = mutate(old)
    with pytest.raises(LedgerRegression):
        save_ledger(paths, new)


def test_ledger_reference_id_change_allowed(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    paths = IndividuationPaths(tmp_path / "individuation")
    old = Ledger(
        reference_id="old-ref",
        looks_completed=5,
        alpha_spent=0.5,
        lived_seconds=10.0,
        lived_ticks=50,
        individuated=True,
    )
    save_ledger(paths, old)

    new = dataclasses.replace(old, reference_id="new-ref")
    save_ledger(paths, new)
    loaded = load_ledger(paths)
    assert loaded.reference_id == "new-ref"
    assert loaded.looks_completed == 5


def test_build_report_scored():
    report = build_report(
        outcome="scored",
        entity_name="ent",
        reference_id="ref-1",
        p_value=0.01,
        effect_size_h=0.6,
        alpha_k=0.05,
        significant=True,
    )
    assert report["kind"] == "individuation_report"
    assert report["schema_version"] == 2
    assert report["outcome"] == "scored"
    assert "report_id" in report
    assert "ts" in report


def test_build_report_inconclusive_with_p_value_raises():
    with pytest.raises(ValueError):
        build_report(
            outcome="inconclusive",
            inconclusive_reason="too few samples",
            p_value=0.1,
        )


def test_build_report_unknown_key_raises():
    with pytest.raises(ValueError):
        build_report(
            outcome="scored",
            p_value=0.01,
            effect_size_h=0.6,
            alpha_k=0.05,
            significant=False,
            text="forbidden",
        )


def test_build_report_non_scalar_raises():
    with pytest.raises(ValueError):
        build_report(
            outcome="scored",
            p_value=0.01,
            effect_size_h=0.6,
            alpha_k=0.05,
            significant=False,
            duration_s={"bad": 1},
        )


def test_build_report_bad_outcome_raises():
    with pytest.raises(ValueError):
        build_report(outcome="maybe")


def test_sink_and_reader(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    paths = IndividuationPaths(tmp_path / "individuation")

    async def run():
        sink = report_sink(paths)
        await sink.start()

        r1 = build_report(
            outcome="scored",
            entity_name="ent",
            reference_id="ref-a",
            reference_kind="birth",
            p_value=0.02,
            effect_size_h=0.5,
            alpha_k=0.05,
            significant=False,
            ts="2025-01-02T00:00:00+00:00",
        )
        r2 = build_report(
            outcome="scored",
            entity_name="ent",
            reference_id="ref-a",
            reference_kind="birth",
            p_value=0.03,
            effect_size_h=0.4,
            alpha_k=0.05,
            significant=False,
            ts="2025-01-01T00:00:00+00:00",
        )
        r3 = build_report(
            outcome="inconclusive",
            entity_name="ent",
            reference_id="ref-b",
            reference_kind="birth",
            inconclusive_reason="organ_resting",
            ts="2025-01-01T00:00:00+00:00",
        )

        await sink.write(r2)
        await sink.write(r1)
        await sink.write(r3)

        await sink.stop()

    asyncio.run(run())

    # Append extra lines by hand.
    reports_dir = paths.reports
    daily = list(reports_dir.glob("*.jsonl"))[0]
    with daily.open("a", encoding="utf-8") as fh:
        fh.write("garbage line that cannot decrypt\n")
        fh.write(json.dumps({"kind": "other", "schema_version": 2}) + "\n")
        fh.write(
            json.dumps(
                {
                    "kind": "individuation_report",
                    "schema_version": 2,
                    "report_id": "plain-1",
                    "ts": "2025-01-03T00:00:00+00:00",
                    "reference_id": "ref-a",
                    "outcome": "inconclusive",
                    "inconclusive_reason": "legacy plaintext",
                }
            )
            + "\n"
        )

    reports = read_reports(paths, reference_id="ref-a")
    assert len(reports) == 3
    assert [r["ts"] for r in reports] == [
        "2025-01-01T00:00:00+00:00",
        "2025-01-02T00:00:00+00:00",
        "2025-01-03T00:00:00+00:00",
    ]

    raw = daily.read_text(encoding="utf-8")
    sink_lines = raw.splitlines()[:3]
    assert all("ref-a" not in line for line in sink_lines)


def test_read_reports_sorted_by_ts_not_name(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    paths = IndividuationPaths(tmp_path / "individuation")
    paths.reports.mkdir(parents=True, exist_ok=True)

    earlier = {
        "kind": "individuation_report",
        "schema_version": 2,
        "report_id": "e",
        "ts": "2025-01-01T00:00:00+00:00",
        "reference_id": "ref-z",
        "outcome": "scored",
        "p_value": 0.1,
        "effect_size_h": 0.1,
        "alpha_k": 0.05,
        "significant": False,
    }
    later = {
        "kind": "individuation_report",
        "schema_version": 2,
        "report_id": "l",
        "ts": "2025-01-02T00:00:00+00:00",
        "reference_id": "ref-z",
        "outcome": "scored",
        "p_value": 0.1,
        "effect_size_h": 0.1,
        "alpha_k": 0.05,
        "significant": False,
    }

    file_b = paths.reports / "b-2025-01-01.jsonl"
    file_a = paths.reports / "a-2025-01-02.jsonl"
    with file_b.open("w", encoding="utf-8") as fh:
        fh.write(get_state_encryptor().encrypt_text(json.dumps(earlier)) + "\n")
    with file_a.open("w", encoding="utf-8") as fh:
        fh.write(get_state_encryptor().encrypt_text(json.dumps(later)) + "\n")

    reports = read_reports(paths, reference_id="ref-z")
    assert [r["report_id"] for r in reports] == ["e", "l"]


def test_individuation_evidence_truth_table():
    now = datetime.fromisoformat("2025-01-15T00:00:00+00:00")

    # 1. latched ledger
    ledger = Ledger(
        reference_id="ref-1",
        looks_completed=3,
        individuated=True,
        last_look_conditions_digest="d1",
    )
    scored = {
        "ts": "2025-01-10T00:00:00+00:00",
        "outcome": "scored",
        "significant": True,
    }
    ev = individuation_evidence(
        ledger, [scored], current_digest="d1", now=now, max_report_age_s=86400
    )
    assert ev == Evidence(True, "latched", scored)

    # 2. no reports
    assert individuation_evidence(
        None, [], current_digest=None, now=now, max_report_age_s=86400
    ) == Evidence(False, "none", None)

    # 3. only inconclusive
    inconclusive = {
        "ts": "2025-01-10T00:00:00+00:00",
        "outcome": "inconclusive",
        "inconclusive_reason": "organ_resting",
    }
    ev = individuation_evidence(
        None, [inconclusive], current_digest=None, now=now, max_report_age_s=86400
    )
    assert ev == Evidence(False, "inconclusive", inconclusive)

    # 4. fresh scored, matching digest
    fresh_scored = {
        "ts": "2025-01-14T00:00:00+00:00",
        "outcome": "scored",
        "significant": False,
    }
    ev = individuation_evidence(
        dataclasses.replace(ledger, individuated=False),
        [fresh_scored],
        current_digest="d1",
        now=now,
        max_report_age_s=86400 * 2,
    )
    assert ev == Evidence(False, "not_individuated", fresh_scored)

    # 5. digest mismatch -> stale
    ev = individuation_evidence(
        dataclasses.replace(ledger, individuated=False),
        [fresh_scored],
        current_digest="d2",
        now=now,
        max_report_age_s=86400 * 2,
    )
    assert ev == Evidence(False, "stale", fresh_scored)

    # 6. too old -> stale
    old_scored = {
        "ts": "2025-01-01T00:00:00+00:00",
        "outcome": "scored",
        "significant": False,
    }
    ev = individuation_evidence(
        dataclasses.replace(ledger, individuated=False),
        [old_scored],
        current_digest="d1",
        now=now,
        max_report_age_s=86400,
    )
    assert ev == Evidence(False, "stale", old_scored)

    # 7. significant scored but unlatched ledger -> fail-safe latched
    ev = individuation_evidence(
        None,
        [scored],
        current_digest=None,
        now=now,
        max_report_age_s=86400,
    )
    assert ev == Evidence(True, "latched", scored)


def test_conditioning_digest():
    d1 = conditioning_digest(
        adapter_sha="sha-a", values=["a", "b"], norms=["x"]
    )
    d2 = conditioning_digest(
        adapter_sha="sha-a", values=["a", "b"], norms=["x"]
    )
    assert d1 == d2

    assert conditioning_digest(
        adapter_sha="sha-a", values=["a", "b"], norms=["x"]
    ) != conditioning_digest(
        adapter_sha="sha-b", values=["a", "b"], norms=["x"]
    )

    assert conditioning_digest(
        adapter_sha="sha-a", values=["a", "b"], norms=["x"]
    ) != conditioning_digest(
        adapter_sha="sha-a", values=["a", "c"], norms=["x"]
    )

    assert conditioning_digest(
        adapter_sha="sha-a", values=["a", "b"], norms=["x"]
    ) != conditioning_digest(
        adapter_sha="sha-a", values=["a", "b"], norms=["y"]
    )

    d_first5 = conditioning_digest(
        adapter_sha="sha-a", values=["1", "2", "3", "4", "5", "6"], norms=[]
    )
    d_drop6 = conditioning_digest(
        adapter_sha="sha-a", values=["1", "2", "3", "4", "5"], norms=[]
    )
    assert d_first5 == d_drop6


def test_read_conditioning_inputs(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)

    self_model_path = tmp_path / "self_model.json"
    adapter_output_dir = tmp_path / "adapters"

    _write_encrypted_json(
        self_model_path,
        {
            "values": ["curiosity", "kindness"],
            "behavioral_norms": ["do no harm", "be truthful"],
        },
    )

    real_dir = adapter_output_dir / "run-1"
    real_dir.mkdir(parents=True)
    (real_dir / "adapter.gguf").write_bytes(b"x")
    current_link = adapter_output_dir / "current"
    current_link.symlink_to(real_dir, target_is_directory=True)

    sha, values, norms = read_conditioning_inputs(
        self_model_path=self_model_path,
        adapter_output_dir=adapter_output_dir,
    )
    assert sha == hashlib.sha256(b"x").hexdigest()
    assert values == ["curiosity", "kindness"]
    assert norms == ["do no harm", "be truthful"]


def test_read_conditioning_inputs_no_adapter(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    self_model_path = tmp_path / "self_model.json"
    adapter_output_dir = tmp_path / "adapters"

    _write_encrypted_json(self_model_path, {"values": ["v"], "behavioral_norms": []})

    sha, values, norms = read_conditioning_inputs(
        self_model_path=self_model_path,
        adapter_output_dir=adapter_output_dir,
    )
    assert sha is None
    assert values == ["v"]
    assert norms == []


def test_read_conditioning_inputs_corrupt_self_model(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    self_model_path = tmp_path / "self_model.json"
    self_model_path.write_bytes(b"not valid encrypted data")
    with pytest.raises(IndividuationStoreError):
        read_conditioning_inputs(
            self_model_path=self_model_path,
            adapter_output_dir=tmp_path / "adapters",
        )


def test_copy_birth_adapter(tmp_path):
    paths = IndividuationPaths(tmp_path / "individuation")
    source = tmp_path / "src.gguf"
    source.write_bytes(b"adapter body")
    sha = copy_birth_adapter(paths, source)
    assert sha == hashlib.sha256(b"adapter body").hexdigest()
    assert paths.birth_adapter.read_bytes() == b"adapter body"
    assert (paths.birth_adapter.stat().st_mode & 0o777) == 0o600


def test_copy_birth_adapter_none(tmp_path):
    paths = IndividuationPaths(tmp_path / "individuation")
    assert copy_birth_adapter(paths, None) == "none"


def test_default_root():
    assert DEFAULT_ROOT == Path("state/individuation")


def test_latch_overrides_an_empty_report_list():
    """After a reference is regenerated the reader filters out older reports;
    a latched being must still read as individuated."""
    ledger = Ledger(reference_id="new-ref", looks_completed=4, individuated=True)
    ev = individuation_evidence(
        ledger,
        [],
        current_digest="d",
        now=datetime.now(timezone.utc),
        max_report_age_s=3600.0,
    )
    assert ev.individuated is True
    assert ev.state == "latched"


def test_report_without_ts_is_skipped(tmp_path):
    paths = IndividuationPaths(tmp_path / "ind")
    paths.reports.mkdir(parents=True)
    good = build_report(
        reference_id="r1",
        outcome="inconclusive",
        inconclusive_reason="organ_resting",
    )
    no_ts = dict(good)
    del no_ts["ts"]
    (paths.reports / "individuation-x.jsonl").write_text(
        json.dumps(no_ts) + "\n" + json.dumps(good) + "\n", encoding="utf-8"
    )
    got = read_reports(paths, reference_id="r1")
    assert [r["report_id"] for r in got] == [good["report_id"]]


def test_malformed_identity_clause_raises(tmp_path):
    sm = tmp_path / "self_model.json"
    sm.write_text(json.dumps({"values": "not a list", "behavioral_norms": []}), encoding="utf-8")
    with pytest.raises(IndividuationStoreError):
        read_conditioning_inputs(self_model_path=sm, adapter_output_dir=tmp_path / "adapters")
