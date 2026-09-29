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


def test_viewing_with_time_scale_change_is_flagged(tmp_path: Path):
    from kaine.research.ignition_study.analysis import _analyse_viewing

    run_id = "r-scale"
    log_dir = tmp_path / "ignition"
    records = [
        _record(run_id, 1, offset=0.0, time_scale=1.0),
        _record(run_id, 2, offset=60.0, time_scale=1.0),
        _record(run_id, 3, offset=120.0, time_scale=0.5),
    ]
    _write_log(log_dir, records)
    step = {
        "line": "branch",
        "step": 1,
        "run_id": run_id,
        "ignition_log_dir": ".",
        "_study_dir": tmp_path,
        "modules": ["topos"],
    }
    result = _analyse_viewing(step, ["topos"])
    assert result.measures["time_scale_min"] == 0.5
    assert result.measures["time_scale_max"] == 1.0
    assert result.measures["time_scale_changed"] is True
    assert result.measures["broadcasts_per_tick"] == 3 / 3


def _make_study_dir(tmp_path: Path, order: list[str] | None = None) -> Path:
    study_dir = tmp_path / "study"
    study_dir.mkdir()
    manifest = tmp_path / "programme.toml"
    manifest.write_text("items = []\n")
    plan = {
        "study_id": "ignition-test",
        "repo_root": str(tmp_path / "repo"),
        "base_modules": ["soma", "chronos", "topos", "audition", "lingua"],
        "order": list(DEFAULT_ORDER if order is None else order),
        "programme": {
            "manifest": str(manifest),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {
            "gestation": "s_g_",
            "branch": "s_b_",
            "repeat": "s_r_",
            "accumulate": "s_a_",
        },
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
    time_scale: float | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
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
    if time_scale is not None:
        rec["time_scale"] = time_scale
    return rec


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
                "line": "branch",
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
                "line": "branch",
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
                "line": "branch",
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
                "line": "branch",
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
                "line": "branch",
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
                "line": "branch",
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


def _viewing(study_dir: Path, line: str, run_id: str, offsets: list[float]) -> Path:
    log_dir = study_dir / line / run_id / "ignition"
    _write_log(
        log_dir, [_record(run_id, i + 1, offset=off) for i, off in enumerate(offsets)]
    )
    return log_dir


def _step(line: str, step: int, run_id: str, log_dir: Path, outcome: str = "complete") -> dict[str, Any]:
    return {
        "line": line,
        "step": step,
        "outcome": outcome,
        "run_id": run_id,
        "ignition_log_dir": str(log_dir),
        "modules": ["soma"],
    }


def _rate(n: int, seconds: float) -> float:
    return n / (seconds / 60)


def _study_with_k2(tmp_path: Path):
    """Gestation, branch 0..2, repeat, accumulate 1..2 with distinct rates."""
    study_dir = _make_study_dir(tmp_path, order=["thymos", "mnemos"])
    spec = {
        ("branch", 0): [0.0, 20.0, 40.0],
        ("repeat", 0): [0.0, 30.0],
        ("branch", 1): [0.0, 15.0, 30.0, 45.0],
        ("branch", 2): [0.0, 10.0, 20.0, 30.0, 40.0],
        ("accumulate", 1): [0.0, 50.0],
        ("accumulate", 2): [0.0, 25.0, 50.0],
    }
    steps = [{"line": "gestation", "step": 0, "outcome": "complete", "run_id": "g0",
              "ignition_log_dir": str(_viewing(study_dir, "gestation", "g0", [0.0, 5.0])),
              "modules": ["soma"]}]
    for (line, k), offs in spec.items():
        rid = f"{line}{k}"
        steps.append(_step(line, k, rid, _viewing(study_dir, line, rid, offs)))
    return study_dir, steps, spec


def _rate_of(spec, line, k):
    offs = spec[(line, k)]
    return _rate(len(offs), offs[-1])


def test_three_comparison_families_and_k_from_order(tmp_path: Path):
    study_dir, steps, spec = _study_with_k2(tmp_path)
    _write_steps(study_dir, steps)
    report = _load_report(study_dir)

    # Gestation is not a viewing.
    lines = [(v["line"], v["step"]) for v in report["per_viewing"]]
    assert ("gestation", 0) not in lines
    assert sorted(lines) == sorted(spec)

    comps = report["comparisons"]
    assert "viewings_per_line" not in report
    assert "per_step" not in report
    assert [e["k"] for e in comps["module_effect_from_seed"]] == [1, 2]
    assert [e["k"] for e in comps["familiarity_and_history"]] == [1, 2]

    for e in comps["module_effect_from_seed"]:
        assert e["status"] == "complete"
        want = _rate_of(spec, "branch", e["k"]) - _rate_of(spec, "branch", 0)
        assert e["difference"]["broadcast_rate_per_minute"] == pytest.approx(want)
    nf = comps["noise_floor"]
    assert nf["status"] == "complete"
    assert nf["difference"]["broadcast_rate_per_minute"] == pytest.approx(
        _rate_of(spec, "branch", 0) - _rate_of(spec, "repeat", 0)
    )
    for e in comps["familiarity_and_history"]:
        assert e["status"] == "complete"
        want = _rate_of(spec, "accumulate", e["k"]) - _rate_of(spec, "branch", e["k"])
        assert e["difference"]["broadcast_rate_per_minute"] == pytest.approx(want)
        assert e["minuend"] == {"line": "accumulate", "step": e["k"]}
        assert e["subtrahend"] == {"line": "branch", "step": e["k"]}
        assert e["correlation"]["correlation"] == "not_computed"

    md = (study_dir / "analysis" / "report.md").read_text()
    assert "Noise floor" in md
    assert "Familiarity and history" in md


def test_incomplete_steps_make_comparisons_pending(tmp_path: Path):
    study_dir, steps, _ = _study_with_k2(tmp_path)
    for st in steps:
        if (st["line"], st["step"]) in (("repeat", 0), ("branch", 2)):
            st["outcome"] = "failed"
    _write_steps(study_dir, steps)
    report = _load_report(study_dir)
    comps = report["comparisons"]

    assert comps["noise_floor"]["status"] == "pending"
    assert comps["noise_floor"]["difference"] is None
    assert comps["noise_floor"]["correlation"] is None
    seed = {e["k"]: e for e in comps["module_effect_from_seed"]}
    assert seed[1]["status"] == "complete"
    assert seed[2]["status"] == "pending"
    fam = {e["k"]: e for e in comps["familiarity_and_history"]}
    assert fam[1]["status"] == "complete"
    assert fam[2]["status"] == "pending"
    assert "Pending" in (study_dir / "analysis" / "report.md").read_text()


def test_k_follows_the_plan_order_not_viewings_per_line(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path, order=["thymos", "mnemos", "hypnos"])
    _write_steps(study_dir, [])
    report = _load_report(study_dir)
    comps = report["comparisons"]
    assert len(comps["module_effect_from_seed"]) == 3
    assert len(comps["familiarity_and_history"]) == 3
    assert all(e["status"] == "pending" for e in comps["module_effect_from_seed"])


def _profile(study_dir: Path, line: str, run_id: str, minutes: int, varying: bool) -> Path:
    log_dir = study_dir / line / run_id / "ignition"
    records = []
    seq = 0
    for m in range(minutes):
        for j in range(m % 3 + 1 if varying else 1):
            seq += 1
            records.append(_record(run_id, seq, offset=float(m * 60 + 1 + j), title="F"))
    _write_log(log_dir, records)
    return log_dir


def _pair_report(tmp_path: Path, minutes: int, varying: bool) -> dict[str, Any]:
    study_dir = _make_study_dir(tmp_path, order=["thymos"])
    _write_steps(
        study_dir,
        [
            _step("branch", 0, "b0", _profile(study_dir, "branch", "b0", minutes, varying)),
            _step("repeat", 0, "r0", _profile(study_dir, "repeat", "r0", minutes, varying)),
        ],
    )
    return _load_report(study_dir)


def test_correlation_not_computed_under_threshold(tmp_path: Path):
    corr = _pair_report(tmp_path, 29, False)["comparisons"]["noise_floor"]["correlation"]
    assert corr["correlation"] == "not_computed"
    assert corr["shared_bins"] == 29


def test_correlation_computed_at_threshold(tmp_path: Path):
    corr = _pair_report(tmp_path, 30, True)["comparisons"]["noise_floor"]["correlation"]
    assert corr["correlation"] == pytest.approx(1.0)
    assert corr["shared_bins"] == 30


def test_main_and_control_lines_are_not_viewings(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    log_dir = _viewing(study_dir, "main", "m0", [0.0, 10.0])
    _write_steps(study_dir, [_step("main", 0, "m0", log_dir), _step("control", 0, "m0", log_dir)])
    assert _load_report(study_dir)["per_viewing"] == []


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
                "line": "branch",
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
    assert "one being per condition" in limits_text
    assert "noise floor is a single repeat" in limits_text
    assert "not evidence" in limits_text
    assert "fixed order" in limits_text
    assert "mixes familiarity with module history" in limits_text
    assert "no rewatch-only line" in limits_text
    assert "Praxis, Perception and Mundus" in limits_text

    md_path = study_dir / "analysis" / "report.md"
    md_text = md_path.read_text()
    assert "Limits" in md_text
    assert "one being per condition" in md_text


def test_constant_profiles_have_undefined_correlation():
    from kaine.research.ignition_study.analysis import _pearson

    assert _pearson([1] * 30, [1] * 30) is None
    assert _pearson([1, 2, 3] * 10, [1, 2, 3] * 10) == pytest.approx(1.0)
