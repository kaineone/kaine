# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import types

import pytest

from kaine.boot import SIMPLE_FACTORIES, construct_module, make_soma


def test_make_soma_raises_without_snntorch(monkeypatch):
    monkeypatch.setattr(
        "kaine.oscillator.module_oscillator.snntorch_available", lambda: False
    )
    bus = types.SimpleNamespace()
    section = {"self_rhythm_enabled": True}
    with pytest.raises(ValueError, match="oscillator extra"):
        make_soma(bus, section)


@pytest.mark.asyncio
async def test_make_soma_builds_self_rhythm_with_womb_drive():
    pytest.importorskip("snntorch")
    from kaine.modules.womb_drive import MaternalDriveProvider

    bus = types.SimpleNamespace()
    section = {
        "self_rhythm_enabled": True,
        "perception_feed": {
            "mode": "womb",
            "seed": 3,
            "womb": {"external_drive_to_self_rhythm": True},
        },
    }
    soma = make_soma(bus, section)
    assert soma._self_rhythm is not None
    assert isinstance(soma._maternal_drive, MaternalDriveProvider)
    assert soma._self_rhythm_step_hz == 20.0


@pytest.mark.asyncio
async def test_make_soma_self_rhythm_without_womb_has_no_maternal_drive():
    pytest.importorskip("snntorch")
    bus = types.SimpleNamespace()
    section = {
        "self_rhythm_enabled": True,
        "perception_feed": {"mode": "live"},
    }
    soma = make_soma(bus, section)
    assert soma._self_rhythm is not None
    assert soma._maternal_drive is None


@pytest.mark.asyncio
async def test_make_soma_without_self_rhythm_has_none():
    bus = types.SimpleNamespace()
    section = {"self_rhythm_enabled": False}
    soma = make_soma(bus, section)
    assert soma._self_rhythm is None
    assert getattr(soma, "_maternal_drive", None) is None


def test_construct_module_injects_perception_feed_for_soma(monkeypatch):
    captured = {}

    def recorder(bus, section, *, entity_clock=None, injections=None):
        captured["section"] = section
        captured["entity_clock"] = entity_clock
        captured["injections"] = injections
        return object()

    monkeypatch.setitem(SIMPLE_FACTORIES, "soma", recorder)

    bus = types.SimpleNamespace()
    config = {
        "soma": {},
        "perception_feed": {"mode": "womb", "seed": 7},
    }
    registry = types.SimpleNamespace(get=lambda name: None)
    result = construct_module(
        "soma", bus, config, registry=registry, entity_clock=object()
    )

    assert result is captured["section"] is not None or result is not None
    assert "perception_feed" in captured["section"]
    assert captured["section"]["perception_feed"] == config["perception_feed"]


@pytest.mark.asyncio
async def test_maternal_drive_starts_at_the_usual_drive_never_the_bound():
    # Soma steps its self-rhythm from initialize(), long before the gestation
    # owner exists, so the provider must start at the configured usual drive
    # (the readout's baseline_drive_fraction), not at the bound (scale 1.0)
    # that a perturbation probe uses briefly and announces.
    pytest.importorskip("snntorch")
    bus = types.SimpleNamespace()
    default = make_soma(
        bus,
        {
            "self_rhythm_enabled": True,
            "perception_feed": {"mode": "womb", "seed": 3},
        },
    )
    assert default._maternal_drive.scale == 0.5
    configured = make_soma(
        bus,
        {
            "self_rhythm_enabled": True,
            "perception_feed": {
                "mode": "womb",
                "seed": 3,
                "womb": {"readout": {"baseline_drive_fraction": 0.3}},
            },
        },
    )
    assert configured._maternal_drive.scale == pytest.approx(0.3)
    with pytest.raises(ValueError):
        make_soma(
            bus,
            {
                "self_rhythm_enabled": True,
                "perception_feed": {
                    "mode": "womb",
                    "seed": 3,
                    "womb": {"readout": {"withdrawal_seconds": 99}},
                },
            },
        )
