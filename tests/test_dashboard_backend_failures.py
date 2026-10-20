# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Backend load failures reach the dashboard from the cycle process
(openspec nexus-backend-failures)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kaine.backend_state import clear_backend_failures, record_backend_failure
from kaine.dashboard.health import blocks
from kaine.dashboard.health.prober import HealthProber


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_backend_failures()
    yield
    clear_backend_failures()


def _runtime(tmp_path: Path, **fields) -> Path:
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(fields))
    return path


def _rec(**over):
    base = {"module": "language", "backend": "vllm", "fallback": "llama_cpp", "reason": "no gpu", "ts": 1.5}
    base.update(over)
    return base


# ---- the cycle writes the field -------------------------------------------


async def _write_state(cyc, runtime: Path, monkeypatch) -> dict:
    monkeypatch.setattr(cyc, "RUNTIME_PATH", runtime)
    cycle = MagicMock()
    cycle.tick_index = 1
    cycle.processing_rate_hz = 3.0
    cycle.experiential_rate_hz = 3.0
    cycle.is_paused = False
    cycle.deterministic = False
    cycle.time_scale = 1.0
    cycle.pacing_stats = {}
    registry = MagicMock()
    registry.all_modules.return_value = []
    await cyc._write_runtime_state(cycle, registry)
    return json.loads(runtime.read_text())


@pytest.mark.asyncio
async def test_runtime_state_writes_empty_backend_failures(tmp_path, monkeypatch):
    import kaine.cycle.__main__ as cyc

    raw = await _write_state(cyc, tmp_path / "runtime.json", monkeypatch)
    assert raw["backend_failures"] == []


@pytest.mark.asyncio
async def test_runtime_state_writes_recorded_backend_failure(tmp_path, monkeypatch):
    import kaine.cycle.__main__ as cyc

    record_backend_failure("language", "vllm", "no gpu", fallback="llama_cpp")
    raw = await _write_state(cyc, tmp_path / "runtime.json", monkeypatch)
    assert len(raw["backend_failures"]) == 1
    entry = raw["backend_failures"][0]
    assert (entry["module"], entry["backend"], entry["fallback"], entry["reason"]) == (
        "language",
        "vllm",
        "llama_cpp",
        "no gpu",
    )


# ---- backends_block --------------------------------------------------------


def test_missing_runtime_file_is_cycle_not_running(tmp_path):
    out = blocks.backends_block(tmp_path / "absent.json")
    assert out == {"ok": None, "source": "cycle_not_running", "failures": []}


def test_unreadable_or_non_dict_is_not_reported(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert blocks.backends_block(bad)["source"] == "not_reported"
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]")
    out = blocks.backends_block(arr)
    assert out["source"] == "not_reported" and out["ok"] is None


def test_missing_or_non_list_key_is_not_reported(tmp_path):
    assert blocks.backends_block(_runtime(tmp_path, pid=1))["source"] == "not_reported"
    out = blocks.backends_block(_runtime(tmp_path, backend_failures="oops"))
    assert out == {"ok": None, "source": "not_reported", "failures": []}


def test_empty_list_is_cycle_ok(tmp_path):
    out = blocks.backends_block(_runtime(tmp_path, backend_failures=[]))
    assert out == {"ok": True, "source": "cycle", "failures": []}


def test_listed_failure_is_not_ok(tmp_path):
    out = blocks.backends_block(_runtime(tmp_path, backend_failures=[_rec()]))
    assert out["ok"] is False and out["source"] == "cycle"
    assert out["failures"] == [_rec()]


def test_entries_are_sanitised(tmp_path):
    entries = [
        "junk",
        _rec(secret="leak", reason="r" * 500, module="m" * 300, ts=float("nan")),
        _rec(backend=7, fallback=3, module="other", ts="soon", reason=None),
    ]
    out = blocks.backends_block(_runtime(tmp_path, backend_failures=entries))
    first, second = out["failures"]
    assert set(first) == {"module", "backend", "fallback", "reason", "ts"}
    assert len(first["reason"]) == 200
    assert len(first["module"]) == 80
    assert first["ts"] is None
    assert second["backend"] is None and second["fallback"] is None
    assert second["ts"] is None and second["reason"] == ""
    assert out["ok"] is False


def test_in_process_failure_is_merged_and_makes_unknown_not_ok(tmp_path):
    record_backend_failure("memory", "faiss", "missing dep")
    out = blocks.backends_block(tmp_path / "absent.json")
    assert out["source"] == "cycle_not_running"
    assert out["ok"] is False
    assert [f["module"] for f in out["failures"]] == ["memory"]
    assert out["failures"][0]["fallback"] is None


def test_in_process_duplicate_of_cycle_record_is_skipped(tmp_path):
    record_backend_failure("language", "vllm", "no gpu", fallback="llama_cpp")
    record_backend_failure("memory", "faiss", "missing dep")
    out = blocks.backends_block(_runtime(tmp_path, backend_failures=[_rec()]))
    assert [f["module"] for f in out["failures"]] == ["language", "memory"]


# ---- prober delegation ------------------------------------------------------


def test_prober_delegates_to_runtime_file(tmp_path):
    prober = object.__new__(HealthProber)
    prober.cycle_runtime_path = _runtime(tmp_path, backend_failures=[_rec()])
    out = prober._backends_block()
    assert out["source"] == "cycle" and out["ok"] is False
    assert out["failures"][0]["module"] == "language"


# ---- health board render ----------------------------------------------------


def _render(backends) -> str:
    from kaine.dashboard.diagnostics import _templates

    tpl = _templates().env.get_template("_health_board.html")
    return tpl.render(health={"dependencies": [], "modules": [], "backends": backends})


def test_board_lists_failures_with_fallback_and_disabled():
    html = _render(
        {
            "ok": False,
            "source": "cycle",
            "failures": [
                _rec(),
                _rec(module="memory", backend="faiss", fallback=None, reason="missing dep"),
            ],
        }
    )
    assert "backend load" in html
    assert "language: vllm failed, using llama_cpp" in html
    assert "memory: faiss failed, module disabled" in html
    assert "no gpu" in html and "missing dep" in html


def test_board_all_loaded_message():
    html = _render({"ok": True, "source": "cycle", "failures": []})
    assert "Every selected backend loaded (reported by the cycle)." in html


def test_board_cycle_not_running_message():
    html = _render({"ok": None, "source": "cycle_not_running", "failures": []})
    assert "Not known: the cycle is not running." in html


def test_board_not_reported_message():
    html = _render({"ok": None, "source": "not_reported", "failures": []})
    assert "Not known: the running cycle does not report backend loads." in html
    assert "—" not in "Not known: the running cycle does not report backend loads."
