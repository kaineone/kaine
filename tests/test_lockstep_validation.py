# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.registry import validate_lockstep_modules
from kaine.modules.base import BaseModule


class _Capable(BaseModule):
    name = "capable_mod"


class _Incapable(BaseModule):
    name = "incapable_mod"
    lockstep_capable = False


def test_lockstep_capable_default_is_true() -> None:
    assert BaseModule.lockstep_capable is True


def test_lockstep_rejects_incapable_module() -> None:
    mods = [_Capable.__new__(_Capable), _Incapable.__new__(_Incapable)]
    with pytest.raises(ConfigurationError, match="incapable_mod"):
        validate_lockstep_modules(mods, lockstep=True)


def test_lockstep_accepts_capable_modules() -> None:
    validate_lockstep_modules([_Capable.__new__(_Capable)], lockstep=True)


def test_incapable_ignored_when_lockstep_off() -> None:
    validate_lockstep_modules([_Incapable.__new__(_Incapable)], lockstep=False)
