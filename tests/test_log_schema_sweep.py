# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Post-run log range validation (log-schema-range-sweep change).

Plants in-range records (no violations) and out-of-range records (negative
prediction_error, valence=2.0, confidence=1.5) and asserts each is flagged with
the offending field and its declared bound. Covers the decrypt path and the CLI
exit code.
"""
from __future__ import annotations

import asyncio
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from kaine.experiment.log_schema import sweep_run
from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

RUN = "run-bbbb"


@pytest.fixture(autouse=True)
def _reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig()))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig()))


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def test_in_range_records_have_no_violations(tmp_path):
    _write_jsonl(
        tmp_path / "soma.report-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "soma.report",
          "prediction_error": 0.0, "wellness": 0.9}],
    )
    _write_jsonl(
        tmp_path / "thymos.state-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "thymos.state",
          "valence": -0.5, "arousal": 0.3, "dominance": 0.1}],
    )
    _write_jsonl(
        tmp_path / "nous.policy-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "nous.policy", "confidence": 0.7}],
    )
    assert sweep_run(RUN, root=tmp_path) == []


def test_negative_prediction_error_is_violation(tmp_path):
    _write_jsonl(
        tmp_path / "soma.report-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "soma.report",
          "prediction_error": -0.3}],
    )
    violations = sweep_run(RUN, root=tmp_path)
    assert len(violations) == 1
    v = violations[0]
    assert v.field == "prediction_error"
    assert v.value == -0.3
    assert v.bound[0] == 0.0
    assert math.isinf(v.bound[1])


def test_out_of_bounds_affect_is_violation(tmp_path):
    _write_jsonl(
        tmp_path / "thymos.state-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "thymos.state",
          "valence": 2.0, "arousal": 0.3, "dominance": 0.0}],
    )
    violations = sweep_run(RUN, root=tmp_path)
    fields = {(v.field, v.value, v.bound) for v in violations}
    assert ("valence", 2.0, (-1.0, 1.0)) in fields


def test_out_of_bounds_confidence_is_violation(tmp_path):
    _write_jsonl(
        tmp_path / "nous.policy-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "nous.policy", "confidence": 1.5}],
    )
    violations = sweep_run(RUN, root=tmp_path)
    assert len(violations) == 1
    assert violations[0].field == "confidence"
    assert violations[0].value == 1.5
    assert violations[0].bound == (0.0, 1.0)


def test_multiple_violations_in_one_record(tmp_path):
    _write_jsonl(
        tmp_path / "thymos.state-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "thymos.state",
          "valence": 2.0, "arousal": 5.0, "dominance": -3.0}],
    )
    violations = sweep_run(RUN, root=tmp_path)
    flagged = {v.field for v in violations}
    assert flagged == {"valence", "arousal", "dominance"}


def test_coherence_plv_out_of_range_is_violation(tmp_path):
    _write_jsonl(
        tmp_path / "coherence-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "coherence",
          "coherence": {"soma|thymos": 0.5, "topos|nous": 1.4}}],
    )
    violations = sweep_run(RUN, root=tmp_path)
    assert len(violations) == 1
    assert violations[0].field == "coherence[topos|nous]"
    assert violations[0].value == 1.4
    assert violations[0].bound == (0.0, 1.0)


def test_generic_field_range_applies_off_taxonomy(tmp_path):
    # salience is a generic field-range rule — flagged even on an unlisted event.
    _write_jsonl(
        tmp_path / "trajectory-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "workspace.broadcast",
          "salience": 1.7}],
    )
    violations = sweep_run(RUN, root=tmp_path)
    assert len(violations) == 1
    assert violations[0].field == "salience"
    assert violations[0].bound == (0.0, 1.0)


def test_nan_numeric_field_is_not_flagged(tmp_path):
    """Design contract of `_as_float`: a NaN in a numeric field is NOT a range
    violation — NaN is not a real number, so the sweep skips it rather than
    fabricating an out-of-range flag. (JSON has no NaN literal; emit it the way a
    Python json dump of float('nan') does — the bare token NaN — which json.loads
    accepts back as a float NaN.)"""
    # prediction_error: NaN — written as the bare JSON token Python's json emits.
    path = tmp_path / "soma.report-2026-06-14.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"run_id": "%s", "seq": 0, "event_type": "soma.report", '
        '"prediction_error": NaN}\n' % RUN,
        encoding="utf-8",
    )
    # Sanity: the planted value really is a float NaN once parsed.
    parsed = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert math.isnan(parsed["prediction_error"])

    violations = sweep_run(RUN, root=tmp_path)
    assert violations == []  # NaN skipped, not flagged


@pytest.mark.asyncio
async def test_decrypt_path_round_trip(tmp_path):
    import os

    from kaine.experiment.run_context import RunContext, set_run_context

    key = os.urandom(32).hex()
    os.environ["KAINE_STATE_KEY"] = key
    try:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
        ctx = RunContext(run_id=RUN, seed=1, started_at="t", git_sha=None)
        set_run_context(ctx)
        try:
            sink = AsyncJsonlSink(tmp_path, name="thymos.state", flush_interval_s=0.05)
            await sink.start()
            try:
                await sink.write(
                    {"event_type": "thymos.state", "valence": 2.0,
                     "arousal": 0.3, "dominance": 0.0}
                )
                await asyncio.sleep(0.2)
            finally:
                await sink.stop()
        finally:
            set_run_context(None)

        path = list(tmp_path.glob("thymos.state-*.jsonl"))[0]
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert not first.startswith("{")  # encrypted on disk

        violations = sweep_run(RUN, root=tmp_path)
        assert any(v.field == "valence" and v.value == 2.0 for v in violations)
    finally:
        os.environ.pop("KAINE_STATE_KEY", None)


def test_cli_exits_nonzero_when_violations(tmp_path):
    _write_jsonl(
        tmp_path / "soma.report-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "soma.report",
          "prediction_error": -1.0}],
    )
    proc = subprocess.run(
        [sys.executable, "-m", "kaine.experiment.log_schema", RUN,
         "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "violations: 1" in proc.stdout


def test_cli_exits_zero_when_clean(tmp_path):
    _write_jsonl(
        tmp_path / "soma.report-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "event_type": "soma.report",
          "prediction_error": 0.2}],
    )
    proc = subprocess.run(
        [sys.executable, "-m", "kaine.experiment.log_schema", RUN,
         "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "violations: 0" in proc.stdout
