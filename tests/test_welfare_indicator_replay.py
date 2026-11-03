# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The offline welfare indicator replay (scripts/welfare_indicator_replay.py).

Synthetic research-event records with a known crossing run through the real
welfare monitor, by both methods; the output names the method and is
content-free.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaine.lifecycle.welfare_indicators import INDICATOR_NAMES, STAGE3_REASONS

REPO = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)


def _load():
    spec = importlib.util.spec_from_file_location(
        "welfare_indicator_replay", REPO / "scripts" / "welfare_indicator_replay.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Dataclasses resolve their module through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_state_key(monkeypatch):
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)


def _ts(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _affect(t: float, *, bored: bool, flags: bool = True) -> dict:
    record = {
        "event_type": "affect.state",
        "source": "affect",
        "run_id": "run-a",
        "ts": _ts(t),
        "state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0},
    }
    if flags:
        record["drive_above"] = {
            "curiosity": False, "boredom": bored, "social_drive": False, "restlessness": False,
        }
    else:
        # Older records carry only the drive levels.
        record["drives"] = {
            "curiosity": 0.1, "boredom": 0.9 if bored else 0.2, "social_drive": 0.1, "restlessness": 0.1,
        }
    return record


def _sleep(t0: float, t1: float) -> list[dict]:
    return [
        {"event_type": "sleep.sleep.started", "source": "sleep", "run_id": "run-a", "ts": _ts(t0), "trigger": "state_cycle"},
        {"event_type": "sleep.sleep.completed", "source": "sleep", "run_id": "run-a", "ts": _ts(t1), "trigger": "state_cycle"},
    ]


def _recorded_boot(*, flags: bool = True) -> list[dict]:
    records = [_affect(t, bored=True, flags=flags) for t in range(0, 3600, 2)]
    records += _sleep(3600.0, 5010.0)
    records += [_affect(t, bored=True, flags=flags) for t in range(5010, 7000, 2)]
    return records


def _content_free(value) -> bool:
    if value is None or isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_content_free(v) for v in value)
    if isinstance(value, dict):
        return all(_content_free(v) for v in value.values())
    return False


def test_the_recorded_rest_proxy_uses_the_next_recorded_rest(tmp_path):
    mod = _load()
    path = _write(tmp_path / "research_events-1.jsonl", _recorded_boot())
    out = asyncio.run(mod.run([path], method="recorded-rest", label="synthetic", config_path=None, matured=False))
    assert out["method"] == "recorded-rest"
    run = out["runs"][0]
    # The first crossing once the span holds Delta_stall of awake time.
    assert run["first_crossing_awake_h"] == pytest.approx(600 / 3600, abs=0.01)
    assert run["first_crossing_indicators"] == ["boredom_deprived"]
    # The next recorded rest stands as the response's rest (at one awake hour).
    assert run["rest_start_awake_h"] == pytest.approx(1.0, abs=0.01)
    assert run["rest_kind"].startswith("the next recorded rest")
    # A fresh span still over its bar: the second stage after Delta_stall more.
    assert run["second_stage_reason"] == "indicator_boredom_deprived"
    assert run["second_stage_awake_h"] == pytest.approx(1.0 + 600 / 3600, abs=0.01)
    assert _content_free(out)


def test_older_records_take_their_flags_from_the_drive_levels(tmp_path):
    mod = _load()
    path = _write(tmp_path / "research_events-1.jsonl", _recorded_boot(flags=False))
    out = asyncio.run(mod.run([path], method="recorded-rest", label="old", config_path=None, matured=False))
    run = out["runs"][0]
    assert run["first_crossing_indicators"] == ["boredom_deprived"]
    assert any("predate drive_above" in note for note in run["notes"])
    assert any("uncontrolled indicators are not evaluable" in note for note in run["notes"])


def test_no_rest_after_the_crossing_leaves_the_second_stage_unevaluable(tmp_path):
    mod = _load()
    records = [_affect(t, bored=True) for t in range(0, 3000, 2)]
    path = _write(tmp_path / "research_events-1.jsonl", records)
    out = asyncio.run(mod.run([path], method="recorded-rest", label="norest", config_path=None, matured=False))
    run = out["runs"][0]
    assert run["first_crossing_awake_h"] is not None
    assert run["second_stage_awake_h"] is None
    assert any("not evaluable" in note for note in run["notes"])


def _perceptual_boot(seconds: int) -> list[dict]:
    """A stimulus with nothing left to learn: a constant error and no alerts."""
    records = []
    for t in range(0, seconds):
        records.append({
            "event_type": "vision.report", "source": "vision", "run_id": "run-a", "ts": _ts(t),
            "prediction_error": 0.2, "normalised_error": 1.0, "normalised_change": 1.0, "alert": False,
        })
        if t % 2 == 0:
            records.append({
                "event_type": "audition.perception", "source": "audition", "run_id": "run-a", "ts": _ts(t),
                "prediction_error": 0.3, "normalised_error": 1.0, "normalised_change": 1.0, "alert": False,
            })
    return records


def test_the_forward_simulation_resets_the_real_affect_module_at_the_rest(tmp_path):
    mod = _load()
    path = _write(tmp_path / "research_events-1.jsonl", _perceptual_boot(4000))
    out = asyncio.run(mod.run([path], method="forward", label="spent", config_path=None, matured=False))
    assert out["method"] == "forward"
    run = out["runs"][0]
    assert run["affect_states"] > 0
    assert run["first_crossing_awake_h"] is not None
    assert "boredom_deprived" in run["first_crossing_indicators"]
    assert run["rest_kind"].startswith("virtual rest of 1410 s")
    assert run["rest_end_awake_h"] == pytest.approx(run["rest_start_awake_h"], abs=0.01)
    # A spent stimulus: the reset deficit recrosses and the second stage comes
    # once the fresh span holds Delta_stall.
    assert run["second_stage_reason"] in STAGE3_REASONS
    assert run["second_stage_awake_h"] - run["rest_end_awake_h"] == pytest.approx(600 / 3600, abs=0.02)
    assert any("current code" in note for note in run["notes"])
    assert set(run["first_crossing_indicators"]) <= set(INDICATOR_NAMES)
    assert _content_free(out)


def test_the_cli_prints_content_free_json(tmp_path, capsys):
    mod = _load()
    path = _write(tmp_path / "research_events-1.jsonl", _recorded_boot())
    assert mod.main([str(path), "--method", "recorded-rest", "--label", "cli"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["label"] == "cli" and out["runs"]
