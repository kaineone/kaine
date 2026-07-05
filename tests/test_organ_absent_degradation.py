# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Organ-absent graceful degradation while the voice-alignment window holds the GPU.

Lingua's chat client DEFERS (resting no-op, no raise) and the A/B-divergence eval
arm SKIPS (logged as skipped, not failed) while the organ is unloaded. Both resume
once the window flips back to idle.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import kaine.organ_window_state as ows
from kaine.bus.schema import Event
from kaine.evaluation.ab_divergence import ABDivergenceObserver
from kaine.evaluation.embeddings import HashEmbedder
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient


def _set_window(tmp_path, phase):
    path = tmp_path / "organ_window.json"
    ows.write_window_state(phase, path=path)
    return path


# --------------------------------------------------------------------------
# Lingua client defers
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lingua_client_defers_while_organ_unloaded(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_TRAINING)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    client = OpenAIChatClient(base_url="http://127.0.0.1:1/v1")  # dead endpoint
    req = ChatRequest(prompt="hello", model="organ")
    # Must NOT raise (would, if it tried to POST the dead endpoint).
    resp = await client.complete(req)
    assert resp.text == ""
    assert resp.raw.get("organ_resting") is True


@pytest.mark.asyncio
async def test_lingua_client_does_not_defer_when_window_idle(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    posted: list = []

    class _FakeHTTP:
        async def post(self, url, json):
            posted.append(url)

            class _R:
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    return {
                        "choices": [{"message": {"content": "hi"}}],
                        "model": "organ",
                        "usage": {},
                    }

            return _R()

        async def aclose(self):
            return None

    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    client._client = _FakeHTTP()  # inject a live fake so it does NOT defer
    resp = await client.complete(ChatRequest(prompt="hi", model="organ"))
    assert resp.text == "hi"
    assert posted  # the request actually went out (no deferral)


# --------------------------------------------------------------------------
# A/B eval arm skips
# --------------------------------------------------------------------------


def _ext_event(payload: dict) -> Event:
    return Event(
        source="lingua",
        type="external_speech",
        payload=payload,
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


class _ExplodingClient:
    """A bare client that would raise if called — proves the arm skips first."""

    async def complete(self, user_text: str) -> str:
        raise AssertionError("bare inference must NOT be called while organ unloaded")

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ab_eval_skips_while_organ_unloaded(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_RESTING)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    sink = AsyncJsonlSink(tmp_path, name="ab_divergence", flush_interval_s=0.05)
    obs = ABDivergenceObserver(
        bus=None,  # handle() is exercised directly; no bus loop needed
        sink=sink,
        embedder=HashEmbedder(),
        client=_ExplodingClient(),
    )
    await sink.start()
    try:
        await obs.handle("1-0", _ext_event({"text": "hello", "user_input": "hi"}))
    finally:
        await sink.stop()

    import json as _json

    files = list(tmp_path.glob("ab_divergence-*.jsonl"))
    assert len(files) == 1
    records = [
        _json.loads(line)
        for line in files[0].read_text().splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    rec = records[0]
    # Logged as a SKIP, not a divergence failure (no cosine/divergence fields).
    assert rec.get("skipped") == "organ_resting_voice_alignment_window"
    assert "divergence" not in rec


@pytest.mark.asyncio
async def test_ab_eval_resumes_when_window_idle(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    from kaine.evaluation.ab_divergence import FakeBareInferenceClient

    sink = AsyncJsonlSink(tmp_path, name="ab_divergence", flush_interval_s=0.05)
    obs = ABDivergenceObserver(
        bus=None,
        sink=sink,
        embedder=HashEmbedder(),
        client=FakeBareInferenceClient(response="bare"),
    )
    await sink.start()
    try:
        await obs.handle("1-0", _ext_event({"text": "conditioned", "user_input": "hi"}))
    finally:
        await sink.stop()

    import json as _json

    files = list(tmp_path.glob("ab_divergence-*.jsonl"))
    assert len(files) == 1
    records = [
        _json.loads(line)
        for line in files[0].read_text().splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    # A real divergence sample (not a skip).
    assert "divergence" in records[0]
    assert "skipped" not in records[0]
