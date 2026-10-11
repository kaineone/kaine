# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus perception router availability: resilient to missing system libraries."""

from __future__ import annotations

import importlib.machinery
import sys

import httpx
import pytest
from fastapi import FastAPI

from kaine.nexus.config import NexusConfig
from kaine.nexus.perception import _availability, build_perception_router


def _isolated_router(tmp_path):
    runtime = tmp_path / "runtime.json"
    desired = tmp_path / "desired.json"
    app = FastAPI()
    app.state.config = NexusConfig(
        operator_token="test-token",
        host_allowlist=("127.0.0.1", "localhost", "t"),
    )
    app.include_router(build_perception_router(runtime_path=runtime, desired_path=desired))
    return app, runtime, desired


class _OSErrorLoader:
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise OSError("PortAudio library not found")


class _OSErrorFinder:
    def __init__(self, name):
        self.name = name

    def find_spec(self, name, path=None, target=None):
        if name == self.name:
            return importlib.machinery.ModuleSpec(name, _OSErrorLoader())
        return None


def test_audio_unavailable_when_portaudio_missing(monkeypatch):
    finder = _OSErrorFinder("sounddevice")
    monkeypatch.setattr(sys, "meta_path", [finder] + sys.meta_path)
    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    result = _availability()
    assert result["audio_available"] is False


def test_video_unavailable_when_system_library_missing(monkeypatch):
    finder = _OSErrorFinder("cv2")
    monkeypatch.setattr(sys, "meta_path", [finder] + sys.meta_path)
    monkeypatch.delitem(sys.modules, "cv2", raising=False)
    result = _availability()
    assert result["video_available"] is False


@pytest.mark.asyncio
async def test_perception_json_answers_200_without_portaudio(tmp_path, monkeypatch):
    finder = _OSErrorFinder("sounddevice")
    monkeypatch.setattr(sys, "meta_path", [finder] + sys.meta_path)
    monkeypatch.delitem(sys.modules, "sounddevice", raising=False)
    app, _, _ = _isolated_router(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/perception.json")
    assert r.status_code == 200
    data = r.json()
    assert data["audio_available"] is False
