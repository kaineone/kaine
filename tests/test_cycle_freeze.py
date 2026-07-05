# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator freeze: control state, the freeze-watch loop (resume-while-paused),
and the Nexus freeze router."""
import asyncio

import httpx
import pytest

from kaine.cycle import control_state as cs


# ---- control state ----------------------------------------------------------

def test_control_round_trip(tmp_path):
    p = tmp_path / "control.json"
    assert cs.read_control(p).frozen is False           # missing → unfrozen
    c = cs.freeze("gpu maintenance", path=p)
    assert c.frozen and c.reason == "gpu maintenance" and c.frozen_at
    assert cs.read_control(p).frozen is True
    cs.unfreeze(path=p)
    got = cs.read_control(p)
    assert got.frozen is False and got.reason is None


def test_control_corrupt_file_defaults_unfrozen(tmp_path):
    p = tmp_path / "control.json"
    p.write_text("{ not json")
    assert cs.read_control(p).frozen is False


# ---- freeze-watch loop ------------------------------------------------------

class _FakeCycle:
    def __init__(self):
        self._paused = False

    @property
    def is_paused(self):
        return self._paused

    async def pause(self):
        self._paused = True

    async def resume(self):
        self._paused = False


async def _wait_until(pred, timeout=2.0):
    waited = 0.0
    while waited < timeout:
        if pred():
            return True
        await asyncio.sleep(0.02)
        waited += 0.02
    return pred()


@pytest.mark.asyncio
async def test_freeze_watch_pauses_and_resumes(tmp_path, monkeypatch):
    import kaine.cycle.__main__ as m

    ctrl = tmp_path / "control.json"
    monkeypatch.setattr(m, "read_control", lambda: cs.read_control(ctrl))
    # don't touch real perception files
    monkeypatch.setattr(m, "write_desired_audio", lambda *a, **k: None)
    monkeypatch.setattr(m, "write_desired_video", lambda *a, **k: None)

    cycle = _FakeCycle()
    stop = asyncio.Event()
    task = asyncio.create_task(m._freeze_watch_loop(cycle, stop))
    try:
        cs.freeze("test", path=ctrl)
        assert await _wait_until(lambda: cycle.is_paused) is True
        # The core requirement: resume works from a paused state.
        cs.unfreeze(path=ctrl)
        assert await _wait_until(lambda: not cycle.is_paused) is True
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)


# ---- Nexus router -----------------------------------------------------------

@pytest.mark.asyncio
async def test_cycle_control_router(tmp_path):
    from fastapi import FastAPI

    from kaine.nexus.cycle_control import build_cycle_control_router

    ctrl = tmp_path / "control.json"
    app = FastAPI()
    app.include_router(build_cycle_control_router(control_path=ctrl))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/diagnostics/cycle/control.json")).json()["frozen"] is False
        r = await client.post(
            "/diagnostics/cycle/freeze", json={"frozen": True, "reason": "gpu work"}
        )
        assert r.status_code == 200 and r.json()["frozen"] is True
        snap = (await client.get("/diagnostics/cycle/control.json")).json()
        assert snap["reason"] == "gpu work"
        # carries only operational fields — no sensory content keys
        assert set(snap.keys()) <= {"frozen", "frozen_at", "reason"}
        r = await client.post("/diagnostics/cycle/freeze", json={"frozen": False})
        assert r.json()["frozen"] is False


def test_freeze_banner_renders_only_when_frozen():
    from kaine.nexus.conversation import _templates

    env = _templates().env
    tpl = env.get_template("_freeze_banner.html")
    frozen = tpl.render(cycle_control={"frozen": True, "reason": "gpu work"})
    assert "FROZEN" in frozen and "gpu work" in frozen
    assert "FROZEN" not in tpl.render(cycle_control={"frozen": False})
    assert tpl.render(cycle_control=None).strip() == ""
