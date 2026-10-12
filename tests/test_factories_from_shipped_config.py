# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Every module factory must build from the SHIPPED configuration.

A factory that copies config keys into constructor keyword arguments breaks when
a constructor parameter is renamed but the config key is not. This test loads the
shipped ``config/kaine.toml`` (alone, with the ``thesis_test`` profile, and with
each tier profile), injects a fake Qdrant API key where required, and attempts
to construct every known module with a mocked bus. A factory returning ``None``
because a backend is unavailable on the host is accepted; any exception is a
failure, and ``TypeError`` is reported as a config-key mismatch.
"""

import copy
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import kaine.boot.registry
import kaine.bus.client
import kaine.config
import kaine.modules.registry

REPO = Path(__file__).resolve().parents[1]


def _tier_cases():
    profiles_dir = REPO / "config" / "profiles"
    return [
        pytest.param(None, path.stem, id=path.stem)
        for path in sorted(profiles_dir.glob("tier*.toml"))
    ]


CONFIG_CASES = [
    pytest.param(None, None, id="shipped"),
    pytest.param("thesis_test", None, id="thesis_test"),
    *_tier_cases(),
]

MODULE_NAMES = kaine.boot.registry.known_module_names()


@pytest.fixture(autouse=True)
def _silence_noisy_logging():
    """Temporarily raise common noisy loggers to WARNING while factories run."""
    names = (
        "httpx",
        "qdrant_client",
        "sentence_transformers",
        "torch",
        "transformers",
        "urllib3",
    )
    loggers = [logging.getLogger(name) for name in names]
    old_levels = {logger: logger.level for logger in loggers}
    for logger in loggers:
        if logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)
    yield
    for logger, level in old_levels.items():
        logger.setLevel(level)


@pytest.mark.parametrize("profile, tier", CONFIG_CASES)
@pytest.mark.parametrize("name", MODULE_NAMES)
def test_factory_builds_from_shipped_config(name, profile, tier, tmp_path):
    """Construct ``name`` under the shipped config variant without exceptions."""
    tmp_operator_path = tmp_path / "operator.toml"
    assert not tmp_operator_path.exists()

    cfg = kaine.config.load_kaine_config(
        REPO / "config" / "kaine.toml",
        tmp_operator_path,
        profile=profile,
        tier=tier,
        profiles_dir=REPO / "config" / "profiles",
    )
    cfg = copy.deepcopy(cfg)

    for section_name in cfg:
        section = cfg[section_name]
        if not isinstance(section, dict):
            continue
        if "qdrant" in section or section_name in {"mnemos", "empatheia"}:
            cfg.setdefault(section_name, {}).setdefault("qdrant", {})["api_key"] = "test-key"

    bus = MagicMock(spec=kaine.bus.client.AsyncBus)

    try:
        kaine.boot.registry.construct_module(
            name,
            bus,
            cfg,
            registry=kaine.modules.registry.ModuleRegistry(),
        )
    except TypeError as exc:
        pytest.fail(
            f"module {name!r} factory passed a config key the constructor does not accept: {exc!r}"
        )
    except Exception as exc:
        pytest.fail(f"module {name!r} raised {type(exc).__name__}: {exc!r}")
