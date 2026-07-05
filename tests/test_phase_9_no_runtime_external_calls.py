# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 9.1: the all-local runtime invariant.

Every URL the production code calls at runtime SHALL resolve to a
loopback host (`127.0.0.1` or `localhost`). The shipped
`config/kaine.toml` is parsed; the URL keys for Lingua / Audio-In /
Audio-Out are checked.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import urlparse

import pytest


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_URL_KEYS = {
    ("lingua", "chat_url"),
    ("audition", "speaches_url"),
    ("vox", "chatterbox_url"),
}


def _kaine_toml() -> dict:
    target = Path(__file__).parent.parent / "config" / "kaine.toml"
    return tomllib.loads(target.read_text())


@pytest.mark.parametrize("section,key", sorted(ALLOWED_URL_KEYS))
def test_default_url_is_loopback(section, key):
    config = _kaine_toml().get(section, {})
    url = config.get(key)
    assert url, f"{section}.{key} missing from default config"
    parsed = urlparse(url)
    host = parsed.hostname
    assert host in LOOPBACK_HOSTS, (
        f"{section}.{key} = {url!r} is not a loopback address"
    )


def test_no_other_url_keys_in_runtime_modules():
    """Catch the case where someone adds a new URL config key that
    isn't in the allowlist."""
    config = _kaine_toml()
    runtime_module_sections = {
        "soma", "chronos", "topos", "nous", "mnemos", "eidolon",
        "thymos", "praxis", "lingua", "vox", "audition", "hypnos",
    }
    new_url_keys: list[tuple[str, str]] = []
    for section in runtime_module_sections:
        sub = config.get(section, {})
        for key, value in (sub.items() if isinstance(sub, dict) else []):
            if not isinstance(value, str):
                continue
            if "://" not in value:
                continue
            new_url_keys.append((section, key))
    unexpected = set(new_url_keys) - ALLOWED_URL_KEYS
    assert not unexpected, (
        f"new URL key(s) added without updating the loopback allowlist: "
        f"{unexpected}. Add them to ALLOWED_URL_KEYS only if they are "
        f"truly loopback-only."
    )
