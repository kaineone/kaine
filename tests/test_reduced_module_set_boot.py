# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Reduced module set boot checks.

This file checks that a reduced module set, set in code, builds through the
real ``build_registry`` with no disabled-module dependency, and that
re-enabling a module is a toggle (spec ``minimal-run-configuration``).
"""

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


def _reduced_config():
    # Isolate from any local operator override so the test sees the shipped
    # layers only.
    cfg = load_kaine_config(operator_path=_MISSING_OPERATOR)
    cfg["modules"] = {name: False for name in cfg["modules"]}
    for name in ("interoception", "sequence", "language"):
        cfg["modules"][name] = True
    return cfg


def test_build_registry_boots_exactly_the_three_modules(monkeypatch):
    """Booting the reduced set registers exactly the interoception, sequence and language modules and hits no
    disabled-module dependency (spec `minimal-run-configuration` clean boot)."""
    import base64
    import os

    monkeypatch.setenv("KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii"))
    bus = _bus()
    registry = build_registry(bus, _reduced_config())
    names = sorted(m.name for m in registry.all_modules())
    assert names == sorted(["sequence", "language", "interoception"])
    # Disabled faculties are absent; the reduced set does not drag them in.
    for disabled in ("episodic_memory", "self_model", "affect", "perceptual_locus", "audition", "vision"):
        assert disabled not in registry


def test_no_work_lost_reenabling_a_module_is_a_toggle(monkeypatch):
    """Flipping a disabled module's toggle back on restores it. The build is
    configuration, not deletion (spec scenario 'Re-enabling a module is a toggle')."""
    import base64
    import os

    monkeypatch.setenv("KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii"))
    cfg = _reduced_config()
    cfg["modules"]["episodic_memory"] = True
    # In-memory backend so the re-enabled module constructs without Qdrant/secrets
    # (the point is that the toggle restores it, not the storage backend).
    cfg.setdefault("episodic_memory", {})["backend"] = "inmemory"
    registry = build_registry(_bus(), cfg)
    assert "episodic_memory" in registry
