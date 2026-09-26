# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the module-ignition study analysis."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from kaine.research.ignition_study.analysis import run_analysis
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    set_state_encryptor,
)

DEFAULT_ORDER = [
    "thymos",
    "mnemos",
    "hypnos",
    "phantasia",
    "nous",
    "eidolon",
    "empatheia",
    "vox",
    "praxis",
    "perception",
    "mundus",
]


@pytest.fixture(autouse=True)
def _reset_encryptor():
    """Restore a plaintext no-op encryptor after every test."""
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _make_study_dir(tmp_path: Path, viewings_per_line: int = 2) -> Path:
    study_dir = tmp_path / "study"
    study_dir.mkdir()
    manifest = tmp_path / "programme.toml"
    manifest.write_text("items = []\n")
    plan = {
        "study_id": "ignition-test",
        "repo_root": str(tmp_path / "repo"),
        "base_modules": ["soma", "chronos", "topos", "audition", "lingua"],
        "order": list(DEFAULT_ORDER),
        "programme": {
            "manifest": str(manifest),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "main": 11, "control": 12},
        },
        "collections": {
            "gestation": "s_g_",
            "main": "s_m_",
            "control": "s_c_",
        },
        "viewings_per_line": viewings_per_line,
    }
    (study_dir / "study.json").write_text(json.dumps(plan, indent=2, sort_keys=True))
    return study_dir


def _record(
    run_id: str,
    seq: int,
    *,
    offset: float = 0.0,
    paused: bool = False,
    item_idx: int = 0,
    title: str = "Film",
    delivered: float | None = None,
    inhibited: bool = False,
    members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "tick_index": seq,
        "entry_id": f"e{seq}",
        "wall_ts": "2026-01-01T00:00:00Z",
        "mono_ts": float(seq),
        "programme": {
            "item_idx": item_idx,
            "order": 0,
            "title": title,
            "offset_s": offset,
            "paused": paused,
        },
        "audio": None
        if delivered is None
        else {"item_idx": item_idx, "delivered_s": delivered},
        "inhibited": inhibited,
        "salience_scores": {},
        "members": members or [],
        "run_id": run_id,
        "seq": seq,
    }


def _member(source: str, salience: float = 0.5) -> dict[str, Any]:
    return {
        "entry_id": f"{source}-1",
        "source": source,
        "type": "topos.report",
        "salience": salience,
        "timestamp": "2026-01-01T00:00:00Z",
    }


def _write_log(log_dir: Path, records: list[dict[str, Any]]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "ignition-2026-01-01.jsonl"
    # The real sink appends every run of a day to one daily file.
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _write_steps(study_dir: Path, steps: list[dict[str, Any]]) -> None:
    with (study_dir / "steps.jsonl").open("w", encoding="utf-8") as fh:
        for rec in steps:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _load_report(study_dir: Path) -> dict[str, Any]:
    json_path, _ = run_analysis(study_dir)
    return json.loads(json_path.read_text())


def test_rate_excludes_paused_time(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    log_dir = study_dir / "main" / "data" / "ignition"
    records = [
        _record("m0", 1, offset=0.0, paused=False),
        _record("m0", 2, offset=30.0, paused=False),
        _record("m0", 3, offset=60.0, paused=True),
        _record("m0", 4, offset=90.0, paused=False),
    ]
    _write_log(log_dir, records)
    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "m0",
                "ignition_log_dir": str(log_dir),
                "modules": ["soma"],
            }
        ],
    )

    report = _load_report(study_dir)
    pv = report["per_viewing"][0]["measures"]
    assert pv["programme_time_minutes"] == pytest.approx(1.5)
    assert pv["paused_broadcasts"] == 1
    # The paused broadcast is reported, not counted in the rate.
    assert pv["broadcast_rate_per_minute"] == pytest.approx(3 / 1.5)


def test_film_minute_bins_and_absent_bins(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    log_dir = study_dir / "main" / "data" / "ignition"
    records = [
        _record("m0", 1, offset=0.0, title="F"),
        _record("m0", 2, offset=30.0, title="F"),
        _record("m0", 3, offset=90.0, title="F"),
    ]
    _write_log(log_dir, records)
    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "m0",
                "ignition_log_dir": str(log_dir),
                "modules": ["soma"],
            }
        ],
    )

    report = _load_report(study_dir)
    bins = report["per_viewing"][0]["film_minute_bins"]["F"]
    assert bins["0"] == 2
    assert bins["1"] == 1
    assert "2" not in bins


def test_coalition_sizes_and_module_shares(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    log_dir = study_dir / "main" / "data" / "ignition"
    records = [
        _record("m0", 1, members=[_member("thymos", 0.8)]),
        _record(
            "m0",
            2,
            members=[_member("thymos", 0.7), _member("syneidesis", 0.4)],
        ),
        _record("m0", 3, members=[_member("mnemos", 0.6)]),
    ]
    _write_log(log_dir, records)
    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "m0",
                "ignition_log_dir": str(log_dir),
                "modules": ["soma"],
            }
        ],
    )

    report = _load_report(study_dir)
    pv = report["per_viewing"][0]["measures"]
    sizes = pv["coalition_size_mean"], pv["coalition_size_median"], pv["coalition_size_p90"]
    assert sizes[0] == pytest.approx(4 / 3)
    assert sizes[1] == pytest.approx(1.0)
    assert sizes[2] == pytest.approx(1.8)

    assert pv["module_shares"]["thymos"] == pytest.approx(2 / 3)
    assert pv["module_shares"]["syneidesis"] == pytest.approx(1 / 3)
    assert pv["module_shares"]["mnemos"] == pytest.approx(1 / 3)
    assert pv["module_shares"]["praxis"] == 0.0

    flagged = set(pv["expected_null_modules_flagged"])
    assert {"praxis", "perception", "mundus"} <= flagged

    assert pv["member_salience"]["thymos"]["mean"] == pytest.approx(0.75)
    assert pv["member_salience"]["thymos"]["median"] == pytest.approx(0.75)
    assert pv["member_salience"]["syneidesis"]["p90"] == pytest.approx(0.4)


def test_picture_to_sound_drift(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    log_dir = study_dir / "main" / "data" / "ignition"
    records = [
        _record("m0", 1, offset=10.0, delivered=9.5),
        _record("m0", 2, offset=20.0, delivered=21.0),
    ]
    _write_log(log_dir, records)
    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "m0",
                "ignition_log_dir": str(log_dir),
                "modules": ["soma"],
            }
        ],
    )

    report = _load_report(study_dir)
    pv = report["per_viewing"][0]["measures"]
    assert pv["drift_median"] == pytest.approx(0.75)
    assert pv["drift_max"] == pytest.approx(1.0)


def test_seq_gaps_counted_as_drops(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    log_dir = study_dir / "main" / "data" / "ignition"
    records = [
        _record("m0", 1),
        _record("m0", 3),
        _record("m0", 4),
    ]
    _write_log(log_dir, records)
    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "m0",
                "ignition_log_dir": str(log_dir),
                "modules": ["soma"],
            }
        ],
    )

    report = _load_report(study_dir)
    dq = report["per_viewing"][0]["measures"]["data_quality"]
    assert dq["dropped_records"] == 1


def test_encrypted_lines_decrypt_and_unreadable_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("KAINE_STATE_KEY", key)

    encryptor = StateEncryptor(CryptoConfig(enabled=True))

    study_dir = _make_study_dir(tmp_path)
    log_dir = study_dir / "main" / "data" / "ignition"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "ignition-2026-01-01.jsonl"
    recs = [_record("m0", 1), _record("m0", 2)]
    with path.open("w", encoding="utf-8") as fh:
        fh.write(encryptor.encrypt_text(json.dumps(recs[0], sort_keys=True)) + "\n")
        fh.write("this is not valid json or encrypted\n")
        fh.write(json.dumps(recs[1], sort_keys=True) + "\n")

    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "m0",
                "ignition_log_dir": str(log_dir),
                "modules": ["soma"],
            }
        ],
    )

    report = _load_report(study_dir)
    pv = report["per_viewing"][0]["measures"]
    assert pv["data_quality"]["record_count"] == 2
    assert pv["data_quality"]["unreadable_lines"] == 1


def test_main_minus_control_and_step_deltas(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path, viewings_per_line=2)

    def _viewing(line: str, step: int, run_id: str, offsets: list[float]) -> tuple[Path, list[dict[str, Any]]]:
        log_dir = study_dir / line / "data" / "ignition"
        records = [
            _record(run_id, i + 1, offset=off)
            for i, off in enumerate(offsets)
        ]
        _write_log(log_dir, records)
        return log_dir, records

    main0_dir, _ = _viewing("main", 0, "main0", [0.0, 20.0, 40.0])
    ctrl0_dir, _ = _viewing("control", 0, "ctrl0", [0.0, 30.0])
    main1_dir, _ = _viewing("main", 1, "main1", [0.0, 15.0, 30.0, 45.0])
    ctrl1_dir, _ = _viewing("control", 1, "ctrl1", [0.0, 50.0])

    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "main0",
                "ignition_log_dir": str(main0_dir),
                "modules": ["soma", "thymos"],
            },
            {
                "line": "control",
                "step": 0,
                "outcome": "complete",
                "run_id": "ctrl0",
                "ignition_log_dir": str(ctrl0_dir),
                "modules": ["soma"],
            },
            {
                "line": "main",
                "step": 1,
                "outcome": "complete",
                "run_id": "main1",
                "ignition_log_dir": str(main1_dir),
                "modules": ["soma", "thymos", "mnemos"],
            },
            {
                "line": "control",
                "step": 1,
                "outcome": "complete",
                "run_id": "ctrl1",
                "ignition_log_dir": str(ctrl1_dir),
                "modules": ["soma"],
            },
        ],
    )

    report = _load_report(study_dir)

    # Main0: 3 records over ~40s => ~1.25 min, rate 2.4
    # Ctrl0: 2 records over ~30s => 0.5 min, rate 4.0
    main0_rate = report["per_viewing"][0]["measures"]["broadcast_rate_per_minute"]
    ctrl0_rate = report["per_viewing"][1]["measures"]["broadcast_rate_per_minute"]
    assert main0_rate == pytest.approx(3 / (40 / 60))
    assert ctrl0_rate == pytest.approx(2 / (30 / 60))

    step0 = report["per_step"][0]
    assert step0["main_minus_control"]["broadcast_rate_per_minute"] == pytest.approx(
        main0_rate - ctrl0_rate
    )

    step1 = report["per_step"][1]
    # Main1: 4 records over ~45s => 0.75 min, rate 5.333
    main1_rate = report["per_viewing"][2]["measures"]["broadcast_rate_per_minute"]
    assert main1_rate == pytest.approx(4 / (45 / 60))
    assert step1["main_delta_from_previous"]["broadcast_rate_per_minute"] == pytest.approx(
        main1_rate - main0_rate
    )

    # Ctrl1: 2 records over ~50s => ~0.833 min, rate 2.4
    ctrl1_rate = report["per_viewing"][3]["measures"]["broadcast_rate_per_minute"]
    assert ctrl1_rate == pytest.approx(2 / (50 / 60))
    assert step1["control_delta_from_previous"]["broadcast_rate_per_minute"] == pytest.approx(
        ctrl1_rate - ctrl0_rate
    )


def test_correlation_not_computed_under_threshold(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path, viewings_per_line=1)

    def _profile(line: str, run_id: str, minutes: int) -> Path:
        log_dir = study_dir / line / "data" / "ignition"
        records = [
            _record(run_id, m + 1, offset=float(m * 60 + 1), title="F")
            for m in range(minutes)
        ]
        _write_log(log_dir, records)
        return log_dir

    main_dir = _profile("main", "main0", 29)
    ctrl_dir = _profile("control", "ctrl0", 29)

    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "main0",
                "ignition_log_dir": str(main_dir),
                "modules": ["soma"],
            },
            {
                "line": "control",
                "step": 0,
                "outcome": "complete",
                "run_id": "ctrl0",
                "ignition_log_dir": str(ctrl_dir),
                "modules": ["soma"],
            },
        ],
    )

    report = _load_report(study_dir)
    corr = report["per_step"][0]["main_vs_control_correlation"]
    assert corr["correlation"] == "not_computed"
    assert corr["shared_bins"] == 29


def test_correlation_computed_at_threshold(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path, viewings_per_line=1)

    def _profile(line: str, run_id: str, minutes: int) -> Path:
        # A varying profile: minute m carries (m % 3) + 1 broadcasts.
        log_dir = study_dir / line / "data" / "ignition"
        records = []
        seq = 0
        for m in range(minutes):
            for j in range(m % 3 + 1):
                seq += 1
                records.append(
                    _record(run_id, seq, offset=float(m * 60 + 1 + j), title="F")
                )
        _write_log(log_dir, records)
        return log_dir

    main_dir = _profile("main", "main0", 30)
    ctrl_dir = _profile("control", "ctrl0", 30)

    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "main0",
                "ignition_log_dir": str(main_dir),
                "modules": ["soma"],
            },
            {
                "line": "control",
                "step": 0,
                "outcome": "complete",
                "run_id": "ctrl0",
                "ignition_log_dir": str(ctrl_dir),
                "modules": ["soma"],
            },
        ],
    )

    report = _load_report(study_dir)
    corr = report["per_step"][0]["main_vs_control_correlation"]
    assert corr["correlation"] == pytest.approx(1.0)
    assert corr["shared_bins"] == 30


def _walk_keys(obj: Any, callback):
    if isinstance(obj, dict):
        for key, value in obj.items():
            callback(key)
            _walk_keys(value, callback)
    elif isinstance(obj, list):
        for value in obj:
            _walk_keys(value, callback)


def test_report_contains_no_payload_and_includes_limits(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    log_dir = study_dir / "main" / "data" / "ignition"
    records = [
        _record(
            "m0",
            1,
            members=[_member("thymos", 0.8)],
        )
    ]
    _write_log(log_dir, records)
    _write_steps(
        study_dir,
        [
            {
                "line": "main",
                "step": 0,
                "outcome": "complete",
                "run_id": "m0",
                "ignition_log_dir": str(log_dir),
                "modules": ["soma"],
            }
        ],
    )

    report = _load_report(study_dir)
    keys: set[str] = set()
    _walk_keys(report, keys.add)
    assert "payload" not in keys

    limits_text = " ".join(report["limits"])
    assert "one fixed order" in limits_text
    assert "Control removes familiarity" in limits_text
    assert "Praxis, Perception" in limits_text
    assert "one being per line" in limits_text

    md_path = study_dir / "analysis" / "report.md"
    md_text = md_path.read_text()
    assert "Limits" in md_text
    assert "one being per line" in md_text


def test_constant_profiles_have_undefined_correlation():
    from kaine.research.ignition_study.analysis import _pearson

    assert _pearson([1] * 30, [1] * 30) is None
    assert _pearson([1, 2, 3] * 10, [1, 2, 3] * 10) == pytest.approx(1.0)
