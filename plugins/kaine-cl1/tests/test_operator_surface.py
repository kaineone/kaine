# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for what the plugin tells and requires of the operator.

Covers the cl-sdk requirement, simulator-only targets, and the explicit
simulator data source.
"""

import os

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import logging
from typing import Any

import kaine_cl1.plugin as plugin_mod
import numpy as np
import pytest
from kaine_cl1.config import overlay_from_mapping
from kaine_cl1.plugin import CLOUD_MESSAGE, REQUIREMENTS_MESSAGE, Cl1Plugin
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession


def _cfg(**substrate_overrides):
    substrate = {
        "target": "simulator",
        "accelerated_time": True,
        "ticks_per_second": 100,
        "cognitive_rate": 3.333,
        "territories": {"chronos": 8},
    }
    substrate.update(substrate_overrides)
    return {"substrate": substrate, "backends": {"chronos": "cl1"}}


@pytest.fixture
def clean_source():
    """Clear any simulator data source registration around a test."""
    import cl.sim

    cl.sim.clear_simulator_data_source()
    yield
    cl.sim.clear_simulator_data_source()


def test_missing_cl_sdk_stops_the_plugin(monkeypatch):
    monkeypatch.setattr(plugin_mod, "_cl_sdk_installed", lambda: False)
    plugin = Cl1Plugin()
    for cfg in (_cfg(), {}):
        with pytest.raises(ValueError) as exc_info:
            plugin.seams(cfg)
        msg = str(exc_info.value)
        assert msg == REQUIREMENTS_MESSAGE
        assert "pip install cl-sdk" in msg
        assert "CC BY-NC 4.0" in msg
        assert "non-learning" in msg


def test_missing_cl_sdk_through_kaines_loader(monkeypatch):
    pytest.importorskip("kaine.plugins")
    from kaine.boot import known_module_names
    from kaine.plugins import PluginError, load_plugins

    monkeypatch.setattr(plugin_mod, "_cl_sdk_installed", lambda: False)

    config = {
        "modules": {"chronos": True},
        "plugins": {"enabled": ["cl1"], "cl1": _cfg()},
    }
    with pytest.raises(PluginError, match="pip install cl-sdk"):
        load_plugins(config, known_modules=known_module_names())


def test_cloud_target_refused():
    with pytest.raises(ValueError) as exc_info:
        Cl1Plugin().seams(_cfg(target="cloud"))
    assert str(exc_info.value) == CLOUD_MESSAGE


def test_hardware_target_refused():
    with pytest.raises(ValueError, match="simulator") as exc_info:
        Cl1Plugin().seams(_cfg(target="hardware"))
    assert "simulator" in str(exc_info.value)


def test_unknown_target_rejected_by_parser():
    with pytest.raises(ValueError, match="target"):
        overlay_from_mapping(_cfg(target="mars"))


def test_data_source_defaults_to_reference_culture():
    overlay = overlay_from_mapping(_cfg())
    assert overlay.substrate.data_source == "reference_culture"


def test_data_source_values_parse():
    assert overlay_from_mapping(_cfg(data_source="sdk")).substrate.data_source == "sdk"

    replay_cfg = _cfg(data_source="replay", replay_path="x.h5")
    assert overlay_from_mapping(replay_cfg).substrate.data_source == "replay"

    with pytest.raises(ValueError, match="replay_path"):
        overlay_from_mapping(_cfg(data_source="replay"))

    with pytest.raises(ValueError, match="data_source"):
        overlay_from_mapping(_cfg(data_source="wetware"))


def test_seams_warns_that_the_substrate_is_simulated(caplog):
    plugin = Cl1Plugin()
    with caplog.at_level(logging.WARNING, logger="kaine_cl1.plugin"):
        plugin.seams(_cfg())

    messages = " ".join(record.message for record in caplog.records)
    assert "SIMULATED" in messages
    assert "reference_culture" in messages
    assert "chronos" in messages

    caplog.clear()
    plugin.seams({})
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == "kaine_cl1.plugin"
    ]
    assert not warnings


def test_session_registers_the_reference_culture(clean_source, monkeypatch):
    import cl.sim

    calls: list[tuple[Any, Any]] = []
    original = cl.sim.set_simulator_data_source

    def recorder(factory, config):
        calls.append((factory, config))
        return original(factory, config)

    monkeypatch.setattr(cl.sim, "set_simulator_data_source", recorder)

    session = SubstrateSession(
        SubstrateConfig(
            accelerated_time=True,
            data_source="reference_culture",
            random_seed=5,
        )
    )
    try:
        session.open()
    finally:
        session.close()

    assert len(calls) == 1
    factory, cfg = calls[0]
    assert factory == "kaine_cl1.substrate.sources:make_reference_culture"
    assert cfg == {"seed": 5}


def test_session_sdk_source_clears_registration(clean_source, monkeypatch):
    import os

    import cl.sim

    count = 0
    original = cl.sim.clear_simulator_data_source

    def wrapper():
        nonlocal count
        count += 1
        return original()

    monkeypatch.setattr(cl.sim, "clear_simulator_data_source", wrapper)
    monkeypatch.setenv("CL_SDK_REPLAY_PATH", "stale.h5")

    session = SubstrateSession(
        SubstrateConfig(accelerated_time=True, data_source="sdk")
    )
    try:
        session.open()
    finally:
        session.close()

    assert count >= 1
    assert "CL_SDK_REPLAY_PATH" not in os.environ


def test_session_leaves_source_alone_when_unset(clean_source, monkeypatch):
    import cl.sim

    set_calls: list[tuple[Any, Any]] = []
    clear_calls: list[Any] = []

    original_set = cl.sim.set_simulator_data_source
    original_clear = cl.sim.clear_simulator_data_source

    def set_recorder(factory, config):
        set_calls.append((factory, config))
        return original_set(factory, config)

    def clear_recorder():
        clear_calls.append(True)
        return original_clear()

    monkeypatch.setattr(cl.sim, "set_simulator_data_source", set_recorder)
    monkeypatch.setattr(cl.sim, "clear_simulator_data_source", clear_recorder)

    session = SubstrateSession(SubstrateConfig(accelerated_time=True))
    try:
        session.open()
    finally:
        session.close()

    assert not set_calls
    assert not clear_calls


def test_default_source_responds_to_stimulation(clean_source):
    p = Cl1Plugin()
    try:
        net = p.injections("chronos", _cfg())["network"]
        quiet = np.mean([np.sum(net.tick([-10.0] * 8)) for _ in range(6)])
        loud = np.mean([np.sum(net.tick([10.0] * 8)) for _ in range(6)])
        assert loud > quiet
    finally:
        p.close()

