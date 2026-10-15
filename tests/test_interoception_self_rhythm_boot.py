# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import types

import pytest

from kaine.boot import SIMPLE_FACTORIES, construct_module, make_interoception


def test_make_interoception_raises_without_snntorch(monkeypatch):
    monkeypatch.setattr(
        "kaine.oscillator.module_oscillator.snntorch_available", lambda: False
    )
    bus = types.SimpleNamespace()
    section = {"self_rhythm_enabled": True}
    with pytest.raises(ValueError, match="oscillator extra"):
        make_interoception(bus, section)


@pytest.mark.asyncio
async def test_make_interoception_builds_self_rhythm_with_stimulus_source_drive():
    pytest.importorskip("snntorch")
    from kaine.modules.stimulus_source_drive import MaternalDriveProvider

    bus = types.SimpleNamespace()
    section = {
        "self_rhythm_enabled": True,
        "perception_feed": {
            "mode": "stimulus_source",
            "seed": 3,
            "stimulus_source": {"external_drive_to_self_rhythm": True},
        },
    }
    interoception = make_interoception(bus, section)
    assert interoception._self_rhythm is not None
    assert isinstance(interoception._maternal_drive, MaternalDriveProvider)
    assert interoception._self_rhythm_step_hz == 20.0


@pytest.mark.asyncio
async def test_make_interoception_self_rhythm_without_stimulus_source_has_no_maternal_drive():
    pytest.importorskip("snntorch")
    bus = types.SimpleNamespace()
    section = {
        "self_rhythm_enabled": True,
        "perception_feed": {"mode": "live"},
    }
    interoception = make_interoception(bus, section)
    assert interoception._self_rhythm is not None
    assert interoception._maternal_drive is None


@pytest.mark.asyncio
async def test_make_interoception_without_self_rhythm_has_none():
    bus = types.SimpleNamespace()
    section = {"self_rhythm_enabled": False}
    interoception = make_interoception(bus, section)
    assert interoception._self_rhythm is None
    assert getattr(interoception, "_maternal_drive", None) is None


def test_construct_module_injects_perception_feed_for_interoception(monkeypatch):
    captured = {}

    def recorder(bus, section, *, entity_clock=None, injections=None):
        captured["section"] = section
        captured["entity_clock"] = entity_clock
        captured["injections"] = injections
        return object()

    monkeypatch.setitem(SIMPLE_FACTORIES, "interoception", recorder)

    bus = types.SimpleNamespace()
    config = {
        "interoception": {},
        "perception_feed": {"mode": "stimulus_source", "seed": 7},
    }
    registry = types.SimpleNamespace(get=lambda name: None)
    result = construct_module(
        "interoception", bus, config, registry=registry, entity_clock=object()
    )

    assert result is captured["section"] is not None or result is not None
    assert "perception_feed" in captured["section"]
    assert captured["section"]["perception_feed"] == config["perception_feed"]


@pytest.mark.asyncio
async def test_maternal_drive_starts_at_the_usual_drive_never_the_bound():
    # the interoception module steps its self-rhythm from initialize(), long before the developmental phase
    # owner exists, so the provider must start at the configured usual drive
    # (the readout's baseline_drive_fraction), not at the bound (scale 1.0)
    # that a perturbation probe uses briefly and announces.
    pytest.importorskip("snntorch")
    bus = types.SimpleNamespace()
    default = make_interoception(
        bus,
        {
            "self_rhythm_enabled": True,
            "perception_feed": {"mode": "stimulus_source", "seed": 3},
        },
    )
    assert default._maternal_drive.scale == 0.5
    configured = make_interoception(
        bus,
        {
            "self_rhythm_enabled": True,
            "perception_feed": {
                "mode": "stimulus_source",
                "seed": 3,
                "stimulus_source": {"readout": {"baseline_drive_fraction": 0.3}},
            },
        },
    )
    assert configured._maternal_drive.scale == pytest.approx(0.3)
    with pytest.raises(ValueError):
        make_interoception(
            bus,
            {
                "self_rhythm_enabled": True,
                "perception_feed": {
                    "mode": "stimulus_source",
                    "seed": 3,
                    "stimulus_source": {"readout": {"withdrawal_seconds": 99}},
                },
            },
        )
