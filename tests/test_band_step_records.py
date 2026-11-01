# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The band-step record and the live-gap record exist for the shipped stimulus version.

The full-span release rule ships for a developmental run only with two records
about the stimulus the run will hear (developmental-stimulus spec, "The band-step
record is kept and the live gap closed before the release rule ships"):

- a band-step record (``kind = "band_step"``): the offline check of each band step;
- a live-gap record (``kind = "live_gap"``): the same per-step readings with
  arousal, rests and broadcast context, or from a test boot's audition errors,
  saying which (``method``).

Each record is a ``*.record.json`` sidecar in docs/records/validation/band-steps/
naming the ``stimulus_version`` it measured (``kaine.boot.stimulus_version``). A
change to the stimulus, its hearing schedule or the release rule changes the
version, and the records must be made again.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from kaine.boot.stimulus_version import developmental_stimulus_version

REPO = Path(__file__).resolve().parents[1]
RECORDS = REPO / "docs" / "records" / "validation" / "band-steps"
LIVE_GAP_METHODS = ("harness_with_arousal_rests_broadcast", "test_boot_replay")


def _shipped_version() -> str:
    return developmental_stimulus_version(tomllib.loads((REPO / "config" / "kaine.toml").read_text()))


def missing_records(directory: Path, version: str) -> list[str]:
    """What is missing for ``version``: an empty list when both records are there."""
    found: dict[str, list[dict]] = {"band_step": [], "live_gap": []}
    for path in sorted(directory.glob("*.record.json")):
        record = json.loads(path.read_text())
        kind = record.get("kind")
        if kind in found and record.get("stimulus_version") == version:
            summary = record.get("summary")
            if isinstance(summary, str) and (directory / summary).is_file():
                found[kind].append(record)
    missing = []
    if not found["band_step"]:
        missing.append(f"a band-step record for stimulus version {version}")
    if not any(r.get("method") in LIVE_GAP_METHODS for r in found["live_gap"]):
        missing.append(f"a live-gap record (method one of {LIVE_GAP_METHODS}) for stimulus version {version}")
    return missing


def _write(directory: Path, name: str, kind: str, version: str, method: str = "offline harness") -> None:
    (directory / f"{name}.json").write_text("[]")
    (directory / f"{name}.record.json").write_text(
        json.dumps({"kind": kind, "summary": f"{name}.json", "stimulus_version": version, "method": method})
    )


def test_the_live_record_is_missing(tmp_path):
    """Spec: the shipped version has a band-step record but no live-gap record."""
    _write(tmp_path, "a", "band_step", "v1")
    assert missing_records(tmp_path, "v1") == [
        f"a live-gap record (method one of {LIVE_GAP_METHODS}) for stimulus version v1"
    ]
    _write(tmp_path, "b", "live_gap", "v1", method="harness_with_arousal_rests_broadcast")
    assert missing_records(tmp_path, "v1") == []
    # Records of another stimulus version do not count.
    assert len(missing_records(tmp_path, "v2")) == 2
    # A live-gap record must say which method it used.
    _write(tmp_path, "c", "band_step", "v3")
    _write(tmp_path, "d", "live_gap", "v3", method="something else")
    assert len(missing_records(tmp_path, "v3")) == 1


def test_the_version_follows_the_stimulus_and_the_release_rule():
    cfg = tomllib.loads((REPO / "config" / "kaine.toml").read_text())
    base = developmental_stimulus_version(cfg)
    assert base == _shipped_version()
    for section, key, value in (
        ("affect", "learning_progress_span_s", 3600.0),
        ("affect", "learning_progress_floor", 0.3),
    ):
        changed = json.loads(json.dumps(cfg))
        changed[section][key] = value
        assert developmental_stimulus_version(changed) != base
    changed = json.loads(json.dumps(cfg))
    changed["perception_feed"]["stimulus_source"]["added_sounds"]["melody_probability"] = 0.05
    assert developmental_stimulus_version(changed) != base
    changed = json.loads(json.dumps(cfg))
    changed["perception_feed"]["stimulus_source"]["hearing"]["max_dwell_seconds"] = 20000.0
    assert developmental_stimulus_version(changed) != base
    # The run seed is not part of it: records cover seeds.
    changed = json.loads(json.dumps(cfg))
    changed["perception_feed"]["seed"] = 12345
    assert developmental_stimulus_version(changed) == base


def test_both_records_exist_for_the_shipped_stimulus_version():
    """The release rule is not used in a developmental run without both records.

    This fails until the live-gap record exists (task 3.1 of
    developmental-stimulus-progress): run the band-step harness again with an
    arousal trace, rests and a broadcast-context input, or replay a test boot's
    audition errors, and store its record naming the shipped version.
    """
    missing = missing_records(RECORDS, _shipped_version())
    assert not missing, "missing: " + "; ".join(missing)
