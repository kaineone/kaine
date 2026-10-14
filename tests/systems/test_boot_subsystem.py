# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot subsystem: `build_registry` constructs modules from config."""
from __future__ import annotations

import pytest

from kaine.boot import build_registry
from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_build_registry_from_minimal_config():
    async with SubsystemHarness() as h:
        registry = build_registry(
            h.bus,
            {
                "modules": {"interoception": True, "sequence": True, "vision": False},
                "interoception": {
                    "read_interval_s": 1.0,
                    "cycle_latency_target_ms": 300.0,
                    "baseline_salience": 0.1,
                    "alert_salience": 0.7,
                },
                "sequence": {
                    "cfc_units": 32,
                    "baseline_salience": 0.1,
                    "alert_salience": 0.7,
                    "anomaly_alert_threshold": 3.0,
                },
            },
        )
        assert "interoception" in registry
        assert "sequence" in registry
        assert "vision" not in registry


@pytest.mark.asyncio
async def test_build_registry_empty_modules_returns_empty():
    async with SubsystemHarness() as h:
        registry = build_registry(h.bus, {"modules": {}})
        assert len(registry) == 0


@pytest.mark.asyncio
async def test_build_registry_rejects_unknown_config_key():
    async with SubsystemHarness() as h:
        with pytest.raises(ValueError, match="unknown config keys"):
            build_registry(
                h.bus,
                {
                    "modules": {"interoception": True},
                    "interoception": {
                        "baseline_salience": 0.1,
                        "bogus_key": True,
                    },
                },
            )
