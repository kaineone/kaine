# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import types

import pytest

from kaine.lifecycle.womb_liveness import _check_local_womb


async def passing_probe(config):
    return [
        types.SimpleNamespace(name="video", status="PASS", detail=""),
        types.SimpleNamespace(name="audio", status="PASS", detail=""),
    ]


@pytest.mark.asyncio
async def test_refuses_when_soma_disabled():
    config = {
        "modules": {"topos": True, "audition": True, "soma": False},
        "soma": {"self_rhythm_enabled": True},
    }
    result = await _check_local_womb(config, passing_probe)
    assert not result.live
    assert "soma is disabled" in result.reason


@pytest.mark.asyncio
async def test_refuses_when_self_rhythm_off():
    config = {
        "modules": {"topos": True, "audition": True, "soma": True},
        "soma": {"self_rhythm_enabled": False},
    }
    result = await _check_local_womb(config, passing_probe)
    assert not result.live
    assert "self_rhythm_enabled is off" in result.reason


@pytest.mark.asyncio
async def test_refuses_when_snntorch_missing(monkeypatch):
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: False)
    config = {
        "modules": {"topos": True, "audition": True, "soma": True},
        "soma": {"self_rhythm_enabled": True},
    }
    result = await _check_local_womb(config, passing_probe)
    assert not result.live
    assert "oscillator extra" in result.reason


@pytest.mark.asyncio
async def test_passes_when_ready(monkeypatch):
    monkeypatch.setattr("kaine.oscillator.snntorch_available", lambda: True)
    config = {
        "modules": {"topos": True, "audition": True, "soma": True},
        "soma": {"self_rhythm_enabled": True},
    }
    result = await _check_local_womb(config, passing_probe)
    assert result.live
    assert result.provider == "local"
    assert result.reason == ""
