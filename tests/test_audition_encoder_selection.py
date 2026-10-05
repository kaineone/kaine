# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import logging

import pytest

from kaine.boot import build_registry, known_module_names
from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.audition import make_audition
from kaine.boot.registry import construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import Audition
from kaine.modules.audition.acoustic import FakeAcousticEncoder, SpectralAcousticEncoder
from kaine.modules.registry import ModuleRegistry
from kaine.plugins import INJECTABLE_SEAMS


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _close_module(module: Audition) -> None:
    await module.shutdown()
    for task in list(getattr(module, "_tasks", [])):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected: the task was cancelled just above.
                pass


@pytest.mark.asyncio
async def test_factory_default_encoder_is_spectral(bus):
    section = {"general_audition": True}
    audition = make_audition(bus, section)
    assert isinstance(audition._acoustic_encoder, SpectralAcousticEncoder)
    assert audition.general_audition
    await _close_module(audition)


@pytest.mark.parametrize("general", [True, False])
@pytest.mark.asyncio
async def test_factory_unknown_encoder_raises_configuration_error(bus, general):
    section = {"general_audition": general, "acoustic_encoder": "nope"}
    with pytest.raises(ConfigurationError) as exc_info:
        make_audition(bus, section)
    assert "nope" in str(exc_info.value)


@pytest.mark.asyncio
async def test_factory_honours_injected_encoder(bus):
    encoder = FakeAcousticEncoder(8)
    section = {"general_audition": True}
    audition = make_audition(bus, section, injections={"acoustic_encoder": encoder})
    assert audition._acoustic_encoder is encoder
    await _close_module(audition)


@pytest.mark.asyncio
async def test_factory_injected_encoder_conflicts_with_nondefault_config(bus):
    encoder = FakeAcousticEncoder(8)
    section = {"general_audition": True, "acoustic_encoder": "dasheng"}
    with pytest.raises(ConfigurationError) as exc_info:
        make_audition(bus, section, injections={"acoustic_encoder": encoder})
    msg = str(exc_info.value).lower()
    assert "seam" in msg or "plugin" in msg


@pytest.mark.asyncio
async def test_factory_injected_encoder_without_general_audition_raises(bus):
    encoder = FakeAcousticEncoder(8)
    section = {"general_audition": False}
    with pytest.raises(ConfigurationError) as exc_info:
        make_audition(bus, section, injections={"acoustic_encoder": encoder})
    msg = str(exc_info.value).lower()
    assert "plugin" in msg and "general" in msg


@pytest.mark.asyncio
async def test_construct_module_accepts_audition_injection(bus):
    encoder = FakeAcousticEncoder(8)
    registry = ModuleRegistry()
    config = {"audition": {"general_audition": True}, "perception_feed": {}}
    module = construct_module(
        "audition",
        bus,
        config,
        registry=registry,
        injections={"acoustic_encoder": encoder},
    )
    assert isinstance(module, Audition)
    assert module._acoustic_encoder is encoder
    await _close_module(module)


def test_injectable_seams_audition():
    assert INJECTABLE_SEAMS["audition"] == frozenset({"acoustic_encoder"})


class _FakeDist:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version


class _FakeEP:
    def __init__(self, name: str, factory, dist=None):
        self.name = name
        self._factory = factory
        self.dist = dist

    def load(self):
        return self._factory


def _eps(*eps):
    return lambda group="kaine.plugins": list(eps)


class _FakeAuditionEncoderPlugin:
    def __init__(self, encoder: FakeAcousticEncoder):
        self._encoder = encoder

    def seams(self, config):
        return frozenset({"audition.acoustic_encoder"})

    def injections(self, module, config):
        if module == "audition":
            return {"acoustic_encoder": self._encoder}
        return {}


@pytest.mark.asyncio
async def test_plugin_end_to_end_fills_audition_encoder(bus, caplog):
    encoder = FakeAcousticEncoder(12)
    plugin = _FakeAuditionEncoderPlugin(encoder)
    from kaine.plugins import load_plugins

    lp = load_plugins(
        {"plugins": {"enabled": ["fake_audition_encoder"]}},
        known_modules=known_module_names(),
        entry_points=_eps(
            _FakeEP(
                "fake_audition_encoder",
                lambda: plugin,
                dist=_FakeDist("pkg", "1.0.0"),
            )
        ),
    )
    with caplog.at_level(logging.WARNING, logger="kaine.plugins"):
        registry = build_registry(
            bus,
            {
                "modules": {"audition": True},
                "audition": {"general_audition": True},
                "perception_feed": {},
            },
            plugins=lp,
        )
    audition = registry.get("audition")
    assert isinstance(audition, Audition)
    assert audition._acoustic_encoder is encoder
    await _close_module(audition)
