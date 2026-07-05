# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Run completeness gating (run-completeness-gating change).

Plants JSONL sink records for a synthetic run under a temp eval root and asserts
the admissibility scan: a complete run is admissible; a tick gap, a seq gap, and
a missing expected stream each make it inadmissible with the right reason. Also
covers the decrypt path (write via AsyncJsonlSink with encryption on, read back)
and the shared run_records loader (run filtering, grouping, parse-error counting).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kaine.experiment.admissibility import scan_run
from kaine.experiment.run_records import (
    discover_run_ids,
    load_run_records,
)
from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    set_state_encryptor,
)

RUN = "run-aaaa"


@pytest.fixture(autouse=True)
def _reset_encryptor():
    # Default disabled no-op; tests that need encryption install their own.
    set_state_encryptor(StateEncryptor(CryptoConfig()))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig()))


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _tick_records(n: int, *, run=RUN, skip: set[int] | None = None) -> list[dict]:
    skip = skip or set()
    out = []
    seq = 0
    for i in range(n):
        if i in skip:
            continue
        out.append({"run_id": run, "seq": seq, "tick_index": i, "event_type": "cycle.tick"})
        seq += 1
    return out


def _plant_complete(root: Path) -> None:
    """A complete run: contiguous ticks + contiguous seq on two streams."""
    _write_jsonl(root / "cycle.tick-2026-06-14.jsonl", _tick_records(5))
    _write_jsonl(
        root / "welfare-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": i, "v": i} for i in range(3)],
    )


def test_complete_run_is_admissible(tmp_path):
    _plant_complete(tmp_path)
    report = scan_run(RUN, root=tmp_path, expected_streams=["cycle.tick", "welfare"])
    assert report.admissible is True
    assert report.tick_gaps == []
    assert report.seq_gaps == {}
    assert report.missing_streams == []
    assert report.parse_errors == 0
    # Restart/multi-process detection (run-admissibility: restart handling)
    # must not false-positive on a normal, monotonic single-process run.
    assert report.restart_seq_resets == {}
    assert report.related_run_ids == []
    assert report.restart_detected() is False


def test_tick_gap_is_inadmissible(tmp_path):
    # Ticks 0,1,3,4 — index 2 missing; reindex seq so seq stays contiguous so
    # the ONLY violation is the tick gap.
    recs = []
    seq = 0
    for i in (0, 1, 3, 4):
        recs.append({"run_id": RUN, "seq": seq, "tick_index": i, "event_type": "cycle.tick"})
        seq += 1
    _write_jsonl(tmp_path / "cycle.tick-2026-06-14.jsonl", recs)
    report = scan_run(RUN, root=tmp_path, expected_streams=["cycle.tick"])
    assert report.admissible is False
    assert report.tick_gaps == [2]
    assert report.seq_gaps == {}


def test_seq_gap_is_inadmissible(tmp_path):
    # seq 0,1,3 on welfare — seq 2 dropped (records silently lost).
    _write_jsonl(tmp_path / "cycle.tick-2026-06-14.jsonl", _tick_records(3))
    _write_jsonl(
        tmp_path / "welfare-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": s, "v": s} for s in (0, 1, 3)],
    )
    report = scan_run(RUN, root=tmp_path, expected_streams=["cycle.tick", "welfare"])
    assert report.admissible is False
    assert report.seq_gaps == {"welfare": [2]}
    assert report.tick_gaps == []


def test_missing_stream_is_inadmissible(tmp_path):
    # welfare expected but never wrote a record this run.
    _write_jsonl(tmp_path / "cycle.tick-2026-06-14.jsonl", _tick_records(3))
    report = scan_run(RUN, root=tmp_path, expected_streams=["cycle.tick", "welfare"])
    assert report.admissible is False
    assert report.missing_streams == ["welfare"]


def test_parse_error_is_inadmissible(tmp_path):
    _plant_complete(tmp_path)
    # Append a malformed line — must be counted, never raised on.
    with (tmp_path / "welfare-2026-06-14.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    report = scan_run(RUN, root=tmp_path, expected_streams=["cycle.tick", "welfare"])
    assert report.admissible is False
    assert report.parse_errors == 1


def test_empty_run_missing_expected_stream_is_inadmissible(tmp_path):
    """A run that produced NO records at all but was expected to produce
    cycle.tick is inadmissible with that stream in missing_streams (silent
    never-ran failure)."""
    report = scan_run("never-ran", root=tmp_path, expected_streams=["cycle.tick"])
    assert report.admissible is False
    assert report.missing_streams == ["cycle.tick"]
    # No records → no tick or seq gaps and no parse errors; the ONLY reason is
    # the missing expected stream.
    assert report.tick_gaps == []
    assert report.seq_gaps == {}
    assert report.parse_errors == 0


def test_seq_reset_mid_run_is_restart_detected(tmp_path):
    """The literal spec scenario: a stream's seq resets back to 0 mid-way
    (0, 1, 2, 0, 1). The set-based contiguity check tolerates the duplicate
    0/1 values as 'not gaps', so this must be caught separately: the run is
    inadmissible and the report flags a restart/multi-process condition."""
    _write_jsonl(tmp_path / "cycle.tick-2026-06-14.jsonl", _tick_records(3))
    welfare = [{"run_id": RUN, "seq": s, "v": s} for s in (0, 1, 2, 0, 1)]
    _write_jsonl(tmp_path / "welfare-2026-06-14.jsonl", welfare)

    report = scan_run(RUN, root=tmp_path, expected_streams=["cycle.tick", "welfare"])
    assert report.admissible is False
    # The set-based gate must NOT be fooled by the reset (no gap by that logic).
    assert report.seq_gaps == {}
    assert report.tick_gaps == []
    assert report.restart_seq_resets == {"welfare": [0, 1]}
    assert report.restart_detected() is True
    assert any("restart" in r.lower() for r in report.reasons())


def test_related_run_ids_is_restart_detected(tmp_path):
    """A caller-declared 'these run_ids are one logical run' correlation
    (e.g. a crash/resume that minted a fresh run_id) is itself a restart
    signal: scanning them together makes the run inadmissible."""
    _write_jsonl(tmp_path / "cycle.tick-2026-06-14.jsonl", _tick_records(3))
    _write_jsonl(
        tmp_path / "cycle.tick-2026-06-14.jsonl",
        _tick_records(2, run="run-resumed"),
    )
    report = scan_run(
        RUN, root=tmp_path, expected_streams=["cycle.tick"],
        related_run_ids=["run-resumed"],
    )
    assert report.admissible is False
    assert report.related_run_ids == ["run-resumed"]
    assert report.restart_detected() is True
    assert any("restart" in r.lower() for r in report.reasons())
    # Merged completeness still holds: no tick gap purely from the merge.
    assert report.tick_gaps == []


def test_seq_reset_undetected_when_pre_crash_stream_has_single_record(tmp_path):
    """DOCUMENTS the known _seq_resets blind spot: a pre-crash stream that only
    reached seq=0, then a restart also from seq=0 (records 0, 0) is NOT caught
    by the seq-reset heuristic (0 < running_max(0) is False). The intended
    detector for such a crash/resume is a fresh run_id (related_run_ids /
    auto-discovery of >1 run), which this test also confirms still fires."""
    # A single stream, seq 0 then 0 again — a duplicate, not a backward jump.
    welfare = [{"run_id": RUN, "seq": 0, "v": 0}, {"run_id": RUN, "seq": 0, "v": 1}]
    _write_jsonl(tmp_path / "welfare-2026-06-14.jsonl", welfare)
    report = scan_run(RUN, root=tmp_path, expected_streams=["welfare"])
    # Blind spot: seq-reset heuristic does NOT flag the duplicate-0.
    assert report.restart_seq_resets == {}
    # And with a single stream this run reads (wrongly) as admissible — which is
    # precisely why the run_id-based detector is the real safeguard:
    assert report.admissible is True

    # The intended detector: a second run_id in the logs is caught.
    _write_jsonl(
        tmp_path / "welfare-2026-06-14.jsonl",
        [{"run_id": "run-after-crash", "seq": 0, "v": 0}],
    )
    report2 = scan_run(
        RUN, root=tmp_path, expected_streams=["welfare"],
        related_run_ids=["run-after-crash"],
    )
    assert report2.admissible is False
    assert report2.restart_detected() is True


def test_discover_run_ids_reads_encrypted_logs(tmp_path):
    """discover_run_ids must decrypt through the installed encryptor: with the
    right key it finds the run_ids; with a wrong key it finds NONE and reports
    unreadable_lines (the fail-closed signal build_research_bundle relies on)."""
    import os

    key = os.urandom(32).hex()
    os.environ["KAINE_STATE_KEY"] = key
    try:
        enc = StateEncryptor(CryptoConfig(enabled=True))
        set_state_encryptor(enc)
        # Write two distinct runs as ENCRYPTED lines.
        path = tmp_path / "welfare-2026-06-14.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for rec in (
                {"run_id": "run-enc-a", "seq": 0, "v": 0},
                {"run_id": "run-enc-b", "seq": 0, "v": 1},
            ):
                fh.write(enc.encrypt_text(json.dumps(rec)) + "\n")

        # Positive: right key → both run_ids discovered, nothing unreadable.
        got = discover_run_ids(tmp_path)
        assert got.run_ids == ["run-enc-a", "run-enc-b"]
        assert got.unreadable_lines == 0

        # Negative: a DIFFERENT key can't decrypt → zero run_ids, all unreadable.
        os.environ["KAINE_STATE_KEY"] = os.urandom(32).hex()
        wrong = StateEncryptor(CryptoConfig(enabled=True))
        set_state_encryptor(wrong)
        got_wrong = discover_run_ids(tmp_path)
        assert got_wrong.run_ids == []
        assert got_wrong.unreadable_lines == 2
    finally:
        os.environ.pop("KAINE_STATE_KEY", None)


def test_empty_run_with_no_expected_streams_is_vacuously_admissible(tmp_path):
    """With no expected streams declared, a run that produced nothing has no
    completeness obligation to violate → vacuously admissible."""
    report = scan_run("never-ran", root=tmp_path, expected_streams=[])
    assert report.admissible is True
    assert report.missing_streams == []
    assert report.tick_gaps == []
    assert report.seq_gaps == {}


def test_loader_filters_by_run_and_groups_by_stream(tmp_path):
    _write_jsonl(
        tmp_path / "cycle.tick-2026-06-14.jsonl",
        _tick_records(2) + [{"run_id": "other", "seq": 9, "tick_index": 0}],
    )
    _write_jsonl(tmp_path / "welfare-2026-06-14.jsonl", [{"run_id": RUN, "seq": 0}])
    recs = load_run_records(RUN, root=tmp_path)
    assert set(recs.by_stream) == {"cycle.tick", "welfare"}
    assert len(recs.by_stream["cycle.tick"]) == 2  # the "other" run is filtered out
    assert recs.streams() == {"cycle.tick", "welfare"}


def test_loader_skips_runs_manifest_dir(tmp_path):
    # Manifests live under runs/<id>/manifest.json (json, not jsonl) — never a
    # record stream. A stray jsonl under runs/ must also be ignored.
    (tmp_path / "runs" / RUN).mkdir(parents=True)
    _write_jsonl(tmp_path / "runs" / RUN / "stray.jsonl", [{"run_id": RUN, "seq": 0}])
    _write_jsonl(tmp_path / "cycle.tick-2026-06-14.jsonl", _tick_records(2))
    recs = load_run_records(RUN, root=tmp_path)
    assert "stray" not in recs.by_stream
    assert set(recs.by_stream) == {"cycle.tick"}


@pytest.mark.asyncio
async def test_decrypt_path_round_trip(tmp_path):
    """Write encrypted records via AsyncJsonlSink, scan reads them back."""
    import os

    from kaine.experiment.run_context import RunContext, set_run_context

    key = os.urandom(32).hex()
    os.environ["KAINE_STATE_KEY"] = key
    try:
        enc = StateEncryptor(CryptoConfig(enabled=True))
        set_state_encryptor(enc)
        ctx = RunContext(run_id=RUN, seed=1, started_at="t", git_sha=None)
        set_run_context(ctx)
        try:
            sink = AsyncJsonlSink(
                tmp_path, name="cycle.tick", flush_interval_s=0.05
            )
            await sink.start()
            try:
                for i in range(4):
                    await sink.write({"tick_index": i, "event_type": "cycle.tick"})
                await asyncio.sleep(0.2)
            finally:
                await sink.stop()
        finally:
            set_run_context(None)

        # On-disk lines must be ciphertext, not plaintext JSON.
        path = list(tmp_path.glob("cycle.tick-*.jsonl"))[0]
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert not first.startswith("{")

        report = scan_run(RUN, root=tmp_path, expected_streams=["cycle.tick"])
        assert report.admissible is True
        assert report.tick_gaps == []
        assert report.seq_gaps == {}
    finally:
        os.environ.pop("KAINE_STATE_KEY", None)


def test_cli_exits_nonzero_when_inadmissible(tmp_path):
    _write_jsonl(
        tmp_path / "cycle.tick-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": 0, "tick_index": 0},
         {"run_id": RUN, "seq": 1, "tick_index": 2}],  # tick gap at 1
    )
    proc = subprocess.run(
        [sys.executable, "-m", "kaine.experiment.admissibility", RUN,
         "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "admissible: False" in proc.stdout


def test_cli_exits_zero_when_admissible(tmp_path):
    _plant_complete(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "kaine.experiment.admissibility", RUN,
         "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "admissible: True" in proc.stdout
