# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for rung freeze (deterministic/study run rung selection, task 11.4).

Covers the three requirements: rungs freeze at boot, a frozen-rung load
failure is recorded, and rung load failures make a run inadmissible.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaine.residency.rung_freeze import (
    FrozenRungs,
    RungLoadFailure,
    clear_frozen_rungs,
    freeze_rungs,
    get_frozen_rungs,
)
from kaine.experiment.admissibility import scan_run

RUN = "run-freeze-test"


@pytest.fixture(autouse=True)
def _reset_global():
    clear_frozen_rungs()
    yield
    clear_frozen_rungs()


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _plant_complete(root: Path) -> None:
    _write_jsonl(
        root / "cycle.tick-2026-06-14.jsonl",
        [{"run_id": RUN, "seq": i, "tick_index": i, "event_type": "cycle.tick"}
         for i in range(3)],
    )


# --- Freeze at boot ---


class TestFreezeAtBoot:
    def test_freeze_records_components(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox", "vocal.stt": "whisper"})
        assert frozen.components == {"vocal.tts": "chatterbox", "vocal.stt": "whisper"}

    def test_is_frozen_returns_true_for_registered(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox"})
        assert frozen.is_frozen("vocal.tts") is True

    def test_is_frozen_returns_false_for_unregistered(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox"})
        assert frozen.is_frozen("vocal.stt") is False

    def test_expected_rung_returns_key(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox"})
        assert frozen.expected_rung("vocal.tts") == "chatterbox"

    def test_expected_rung_returns_none_for_unregistered(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox"})
        assert frozen.expected_rung("vocal.stt") is None

    def test_get_frozen_rungs_returns_active(self):
        freeze_rungs({"vocal.tts": "chatterbox"})
        assert get_frozen_rungs() is not None
        assert get_frozen_rungs().components == {"vocal.tts": "chatterbox"}

    def test_freeze_copies_input(self):
        src = {"vocal.tts": "chatterbox"}
        frozen = freeze_rungs(src)
        src["vocal.tts"] = "kokoro"
        assert frozen.components["vocal.tts"] == "chatterbox"


# --- Failure recording ---


class TestFailureRecording:
    def test_record_failure_appends(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox"})
        failure = frozen.record_failure("vocal.tts", "model file missing")
        assert isinstance(failure, RungLoadFailure)
        assert failure.component == "vocal.tts"
        assert failure.rung_key == "chatterbox"
        assert failure.reason == "model file missing"
        assert len(frozen.failures) == 1

    def test_record_failure_unknown_component(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox"})
        failure = frozen.record_failure("vocal.stt", "not configured")
        assert failure.rung_key == "unknown"

    def test_multiple_failures(self):
        frozen = freeze_rungs({"vocal.tts": "chatterbox", "vocal.stt": "whisper"})
        frozen.record_failure("vocal.tts", "crash")
        frozen.record_failure("vocal.stt", "timeout")
        assert len(frozen.failures) == 2
        assert frozen.failures[0].component == "vocal.tts"
        assert frozen.failures[1].component == "vocal.stt"


# --- Global state ---


class TestGlobalState:
    def test_get_returns_none_when_not_frozen(self):
        assert get_frozen_rungs() is None

    def test_clear_resets_global(self):
        freeze_rungs({"vocal.tts": "chatterbox"})
        clear_frozen_rungs()
        assert get_frozen_rungs() is None


# --- Admissibility integration ---


class TestAdmissibility:
    def test_rung_failure_makes_run_inadmissible(self, tmp_path):
        _plant_complete(tmp_path)
        report = scan_run(
            RUN, root=tmp_path,
            rung_load_failures=["vocal.tts: chatterbox failed to load"],
        )
        assert report.admissible is False
        assert report.rung_load_failures == ["vocal.tts: chatterbox failed to load"]

    def test_empty_rung_failures_does_not_affect_admissibility(self, tmp_path):
        _plant_complete(tmp_path)
        report = scan_run(RUN, root=tmp_path, rung_load_failures=[])
        assert report.admissible is True
        assert report.rung_load_failures == []

    def test_reasons_includes_rung_failures(self, tmp_path):
        _plant_complete(tmp_path)
        report = scan_run(
            RUN, root=tmp_path,
            rung_load_failures=["vocal.tts: chatterbox failed to load"],
        )
        reasons = report.reasons()
        assert any("rung load failures" in r for r in reasons)

    def test_multiple_rung_failures(self, tmp_path):
        _plant_complete(tmp_path)
        failures = [
            "vocal.tts: chatterbox failed to load",
            "vocal.stt: whisper OOM",
        ]
        report = scan_run(RUN, root=tmp_path, rung_load_failures=failures)
        assert report.admissible is False
        assert report.rung_load_failures == failures

    def test_rung_failure_in_to_dict(self, tmp_path):
        _plant_complete(tmp_path)
        report = scan_run(
            RUN, root=tmp_path,
            rung_load_failures=["vocal.tts: chatterbox failed to load"],
        )
        d = report.to_dict()
        assert d["rung_load_failures"] == ["vocal.tts: chatterbox failed to load"]
        assert any("rung load failures" in r for r in d["reasons"])
