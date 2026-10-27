# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""control.json is a shared read-modify-write file: updates are locked, temp files unique."""
from __future__ import annotations

import json
import multiprocessing as mp
import threading
from pathlib import Path

from kaine.cycle import control_state
from kaine.state_io import update_json_locked, write_json_atomic


def _worker(path: str, source: str, n: int) -> None:
    p = Path(path)
    for _ in range(n):
        control_state.push_freeze("x", path=p, source=source)
        control_state.pop_freeze(path=p, source=source)


def test_two_processes_never_lose_a_freeze(tmp_path: Path) -> None:
    path = tmp_path / "control.json"
    control_state.push_freeze("w", path=path, source="welfare")
    ctx = mp.get_context("fork")
    procs = [ctx.Process(target=_worker, args=(str(path), s, 150)) for s in ("supervisor", "operator")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    stack = control_state.read_control(path).stack
    assert [e["source"] for e in stack] == ["welfare"]
    assert list(tmp_path.glob("*.tmp")) == []


def test_welfare_push_racing_operator_resume_keeps_welfare(tmp_path: Path, monkeypatch) -> None:
    """Both writers read the old stack before either writes (forced with a barrier);
    without the lock the later write would drop the other's change."""
    path = tmp_path / "control.json"
    control_state.push_freeze("op", path=path, source="operator")
    barrier = threading.Barrier(2, timeout=1)
    real_loads = json.loads

    def slow_loads(*a, **k):
        data = real_loads(*a, **k)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass  # locked: the other thread is waiting on the lock, so it cannot arrive
        return data

    monkeypatch.setattr("kaine.state_io.json.loads", slow_loads)
    t1 = threading.Thread(target=control_state.push_freeze, args=("w",), kwargs={"path": path, "source": "welfare"})
    t2 = threading.Thread(target=control_state.stand_down, kwargs={"path": path, "source": "operator"})
    t1.start()
    t2.start()
    t1.join(10)
    t2.join(10)
    monkeypatch.undo()
    assert [e["source"] for e in control_state.read_control(path).stack] == ["welfare"]


def test_write_json_atomic_concurrent_leaves_valid_file_and_no_temp(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    errors: list[BaseException] = []

    def run(i: int) -> None:
        try:
            for j in range(50):
                write_json_atomic(path, {"i": i, "j": j})
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    ts = [threading.Thread(target=run, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert set(json.loads(path.read_text())) == {"i", "j"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.json"]


def test_write_json_atomic_cleans_up_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    try:
        write_json_atomic(path, {"x": object()})
    except TypeError:
        pass
    assert list(tmp_path.iterdir()) == []


def test_update_json_locked_default_and_no_write_on_error(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    assert update_json_locked(path, lambda d: {**d, "n": 1}, default={}) == {"n": 1}
    try:
        update_json_locked(path, lambda d: 1 / 0, default={})
    except ZeroDivisionError:
        pass
    assert json.loads(path.read_text()) == {"n": 1}
