# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.config import list_all_defaults, load_kaine_config


def _paths(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield prefix + (key,)
            yield from _paths(item, prefix + (key,))
    elif isinstance(value, list):
        for item in value:
            yield from _paths(item, prefix)


# The suite's conftest injects an isolated [storage].data_root; this test
# checks the shipped defaults, so it runs without that injection.
@pytest.mark.no_data_root
def test_every_runtime_config_key_appears_in_shipped_defaults():
    runtime = load_kaine_config()
    defaults = list_all_defaults()

    runtime_keys = set(_paths(runtime))
    default_keys = set(_paths(defaults))

    missing = sorted(runtime_keys - default_keys)
    assert not missing, f"runtime config keys missing from shipped defaults: {missing}"
