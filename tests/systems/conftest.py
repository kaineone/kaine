# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Auto-marker for all systems tests + env-var skip flags."""
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    systems_dir = "/systems/"
    marker = pytest.mark.systems
    for item in items:
        if systems_dir in str(item.fspath):
            item.add_marker(marker)


def has_env(name: str) -> bool:
    return os.environ.get(name) in ("1", "true", "TRUE")


@pytest.fixture
def has_unsloth() -> bool:
    return has_env("KAINE_HAS_UNSLOTH")


@pytest.fixture
def has_speaches() -> bool:
    return has_env("KAINE_HAS_SPEACHES")


@pytest.fixture
def has_chatterbox() -> bool:
    return has_env("KAINE_HAS_CHATTERBOX")


@pytest.fixture
def has_nar_binary() -> bool:
    return has_env("KAINE_HAS_NAR_BINARY")


@pytest.fixture
def has_qdrant() -> bool:
    return has_env("KAINE_HAS_QDRANT")
