# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Verify drive-source table is built from module declarations, matching the prior
hardcoded table exactly (OpenSpec ``drive-sources-from-modules``).
"""
from __future__ import annotations

import importlib
import inspect
from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from kaine.boot import ConfigurationError, drive_sources_for, make_salience_factors
from kaine.bus.client import AsyncBus
from kaine.cycle.affect_state import AffectStateProvider
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.workspace.strategies import DRIVES, build_drive_sources

# The previous hardcoded drive-to-source table. Behaviour must not change.
PREVIOUS = {
    "curiosity": frozenset({"perception", "topos", "audition", "mundus", "mnemos"}),
    "boredom": frozenset({"perception", "topos", "audition", "mundus", "mnemos", "nous", "phantasia", "lingua"}),
    "social_drive": frozenset({"audition", "empatheia", "vox", "lingua", "chronos"}),
    "restlessness": frozenset({"praxis", "volition", "vox", "mundus"}),
}

_MODULE_NAMES = [
    "perception",
    "topos",
    "mnemos",
    "audition",
    "mundus",
    "nous",
    "phantasia",
    "lingua",
    "empatheia",
    "chronos",
    "vox",
    "praxis",
    "soma",
    "thymos",
    "eidolon",
    "hypnos",
    "echo",
]


def _load_module_class(name: str) -> type[BaseModule]:
    # Most modules are packages with a ``module.py``; echo is a single file.
    try:
        mod = importlib.import_module(f"kaine.modules.{name}.module")
    except ModuleNotFoundError:
        mod = importlib.import_module(f"kaine.modules.{name}")
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if obj is BaseModule:
            continue
        if not issubclass(obj, BaseModule):
            continue
        if getattr(obj, "name", None) == name:
            return obj
    raise AssertionError(f"no BaseModule subclass named {name!r} found")


def test_drive_sources_from_modules_match_previous_table():
    tags_by_source = {
        cls.name: cls.relieves_drives
        for cls in (_load_module_class(n) for n in _MODULE_NAMES)
    }
    assert build_drive_sources(tags_by_source) == PREVIOUS


def test_all_declared_drive_tags_are_known_drives():
    for cls in (_load_module_class(n) for n in _MODULE_NAMES):
        for tag in cls.relieves_drives:
            assert tag in DRIVES, f"{cls.name} declares unknown drive {tag!r}"


def test_build_drive_sources_rejects_unknown_tag():
    with pytest.raises(ValueError, match="unknown drive tag"):
        build_drive_sources({"x": {"bogus"}})


def _fake_bus() -> AsyncBus:
    return MagicMock(spec=AsyncBus)


class _FakeModuleA(BaseModule):
    name: ClassVar[str] = "fake_a"
    relieves_drives: ClassVar[frozenset[str]] = frozenset({"curiosity"})

    async def on_workspace(self, snapshot):
        pass

    def serialize(self):
        return {}

    @classmethod
    def deserialize(cls, data, bus):
        return cls(bus)


class _FakeModuleB(BaseModule):
    name: ClassVar[str] = "fake_b"
    relieves_drives: ClassVar[frozenset[str]] = frozenset({"boredom", "social_drive"})

    async def on_workspace(self, snapshot):
        pass

    def serialize(self):
        return {}

    @classmethod
    def deserialize(cls, data, bus):
        return cls(bus)


def test_drive_sources_for_includes_registered_modules_and_scaffolding():
    registry = ModuleRegistry()
    registry.register(_FakeModuleA(_fake_bus()))
    registry.register(_FakeModuleB(_fake_bus()))

    sources = drive_sources_for(registry)
    assert sources["curiosity"] == frozenset({"fake_a"})
    assert sources["boredom"] == frozenset({"fake_b"})
    assert sources["social_drive"] == frozenset({"fake_b"})
    assert sources["restlessness"] == frozenset({"volition"})


def test_make_salience_factors_drive_relevance_requires_drive_sources():
    with pytest.raises(ConfigurationError, match="drive_relevance needs the registered modules"):
        make_salience_factors(
            {"syneidesis": {"salience_goal_factor": "drive_relevance"}},
            AffectStateProvider(),
        )
