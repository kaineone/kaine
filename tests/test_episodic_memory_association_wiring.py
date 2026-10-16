# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the associative replay wiring into the bus-facing EpisodicMemory module."""

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.episodic_memory import make_episodic_memory
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.decommission import _episodic_memory_collection_names
from kaine.modules.episodic_memory import EpisodicMemory, FakeEmbedder
from kaine.modules.episodic_memory.associations import AssociationParams


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _base_config(**extras):
    return {
        "backend": "inmemory",
        "_embedder": FakeEmbedder(latent_dim=8),
        "strength": {
            "retention_per_day": 0.82,
            "prune_floor": 0.01,
            "traces_per_day": 288000.0,
        },
        **extras,
    }


async def test_association_defaults_when_no_subtable(bus):
    module = make_episodic_memory(bus, _base_config())
    assert module.core.association_params == AssociationParams()


async def test_association_subtable_reaches_core(bus):
    module = make_episodic_memory(
        bus,
        _base_config(
            association={
                "n_pair": 2,
                "sim_min": 0.6,
                "sim_dup": 0.9,
                "n_sch": 4,
                "n_link": 6,
            }
        ),
    )
    assert module.core.association_params == AssociationParams(
        n_pair=2, sim_min=0.6, sim_dup=0.9, n_sch=4, n_link=6
    )


async def test_association_validation_errors(bus):
    full = {"n_pair": 2, "sim_min": 0.6, "sim_dup": 0.9, "n_sch": 4, "n_link": 6}
    # Unknown keys fail through the shared key guard, which raises ValueError
    # as it does for every other table.
    with pytest.raises(ValueError, match="bogus"):
        make_episodic_memory(
            bus, _base_config(association={**full, "bogus": 1})
        )
    with pytest.raises(ConfigurationError):
        make_episodic_memory(
            bus, _base_config(association={**full, "n_pair": 0})
        )
    with pytest.raises(ConfigurationError):
        make_episodic_memory(
            bus, _base_config(association={**full, "n_link": True})
        )
    with pytest.raises(ConfigurationError):
        make_episodic_memory(
            bus,
            _base_config(
                association={**full, "sim_min": 0.95, "sim_dup": 0.5}
            ),
        )
    with pytest.raises(ConfigurationError):
        make_episodic_memory(
            bus,
            _base_config(association={**full, "sim_min": "0.5"}),
        )


async def test_retired_cross_period_candidates_logs_warning(bus, caplog):
    with caplog.at_level("WARNING"):
        module = make_episodic_memory(
            bus, _base_config(replay={"cross_period_candidates": 7})
        )
    assert "cross_period_candidates" in caplog.text
    assert not hasattr(module, "_cross_period_candidates")
    assert not hasattr(module, "select_cross_period_traces")


async def test_downscale_prune_forwarding_and_associate_prune(bus):
    class FakeCore:
        def __init__(self):
            self.downscale_kwargs = None
            self.associate_called = False
            self.prune_called = False

        async def downscale(self, triples, **kwargs):
            self.downscale_kwargs = kwargs
            return {}

        async def associate(self):
            self.associate_called = True
            return {"associate": True}

        async def prune(self):
            self.prune_called = True
            return {"prune": True}

    fake = FakeCore()
    module = EpisodicMemory(bus, core=fake)

    await module.downscale([])
    assert fake.downscale_kwargs == {}

    await module.downscale([], prune=False)
    assert fake.downscale_kwargs == {"prune": False}

    assert await module.associate() == {"associate": True}
    assert fake.associate_called

    assert await module.prune() == {"prune": True}
    assert fake.prune_called


def test_decommission_includes_association_collections():
    names = _episodic_memory_collection_names(None)
    assert "episodic_memory_links" in names
    assert "episodic_memory_schemas" in names
    assert "episodic_memory_episodic" in names
