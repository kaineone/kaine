# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for idempotent state-encryption install."""
from __future__ import annotations

import pytest

import kaine.boot.security as boot_security
import kaine.security.crypto as crypto


@pytest.fixture(autouse=True)
def _no_keyring(monkeypatch):
    monkeypatch.setattr(crypto, "_load_key_from_keyring", lambda: None)


def _reset_active():
    crypto._active = None


def test_installing_twice_with_same_key_is_idempotent(monkeypatch):
    _reset_active()
    monkeypatch.setenv("KAINE_STATE_KEY", "11" * 32)
    boot_security.install_state_encryption(
        {"security": {"state_encryption": {"enabled": True}}}
    )
    first = crypto.get_state_encryptor()
    boot_security.install_state_encryption(
        {"security": {"state_encryption": {"enabled": True}}}
    )
    second = crypto.get_state_encryptor()
    assert first is second


def test_installing_with_changed_key_replaces_encryptor(monkeypatch):
    _reset_active()
    monkeypatch.setenv("KAINE_STATE_KEY", "11" * 32)
    boot_security.install_state_encryption(
        {"security": {"state_encryption": {"enabled": True}}}
    )
    first = crypto.get_state_encryptor()

    monkeypatch.setenv("KAINE_STATE_KEY", "22" * 32)
    boot_security.install_state_encryption(
        {"security": {"state_encryption": {"enabled": True}}}
    )
    second = crypto.get_state_encryptor()

    assert first is not second
    assert second.enabled is True


def test_installing_disabled_after_enabled_replaces_encryptor(monkeypatch):
    _reset_active()
    monkeypatch.setenv("KAINE_STATE_KEY", "11" * 32)
    boot_security.install_state_encryption(
        {"security": {"state_encryption": {"enabled": True}}}
    )
    first = crypto.get_state_encryptor()

    boot_security.install_state_encryption(
        {"security": {"state_encryption": {"enabled": False}}}
    )
    second = crypto.get_state_encryptor()

    assert first is not second
    assert second.enabled is False
