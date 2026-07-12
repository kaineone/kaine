# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The minimal-experiment profile (workspace-mediation ablation configuration).

Verifies the overlay both resolves to the intended config AND boots through the
real ``build_registry`` to exactly the three modules — no disabled-module
dependency breaks the minimal set."""
from __future__ import annotations

import pytest

from kaine.boot import build_registry
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.config import load_kaine_config

_MISSING_OPERATOR = "/nonexistent-operator-for-tests.toml"


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _minimal_config():
    # Isolate from any local operator override so the test sees the shipped +
    # profile layers only (what "booting the overlay" means).
    return load_kaine_config(
        profile="minimal_experiment", operator_path=_MISSING_OPERATOR
    )


def test_overlay_resolves_to_the_minimal_knobs():
    cfg = _minimal_config()
    enabled = sorted(k for k, v in cfg["modules"].items() if v)
    assert enabled == ["chronos", "lingua", "soma"]
    # Competition capacity lowered so selection actually excludes on the minimal set.
    assert cfg["syneidesis"]["top_k"] == 2
    # Volition matches the paper's default policy (no drive-initiated intents).
    assert cfg["volition"]["drive_initiative"] is False
    # Greedy decoding so the observable carries no sampling noise.
    assert cfg["lingua"]["temperature"] == 0.0


def test_build_registry_boots_exactly_the_three_modules():
    """Booting the overlay registers exactly Soma/Chronos/Lingua and hits no
    disabled-module dependency (spec `minimal-run-configuration` clean boot)."""
    bus = _bus()
    registry = build_registry(bus, _minimal_config())
    names = sorted(m.name for m in registry.all_modules())
    assert names == ["chronos", "lingua", "soma"]
    # Disabled faculties are absent — the minimal set does not drag them in.
    for disabled in ("mnemos", "eidolon", "thymos", "perception", "audition", "topos"):
        assert disabled not in registry


def test_no_work_lost_reenabling_a_module_is_a_toggle():
    """Flipping a disabled module's toggle back on restores it — the minimal
    build is configuration, not deletion (spec scenario 'No work is lost')."""
    cfg = _minimal_config()
    cfg["modules"]["mnemos"] = True
    # In-memory backend so the re-enabled module constructs without Qdrant/secrets
    # (the point is that the toggle restores it, not the storage backend).
    cfg.setdefault("mnemos", {})["backend"] = "inmemory"
    registry = build_registry(_bus(), cfg)
    assert "mnemos" in registry
