# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for research-gate encryption wiring."""
from __future__ import annotations

import pytest

import kaine.cycle.research_gate as research_gate
import kaine.security.crypto as crypto


@pytest.fixture(autouse=True)
def _no_keyring(monkeypatch):
    monkeypatch.setattr(crypto, "_load_key_from_keyring", lambda: None)


def test_preflight_ok_when_encryption_enabled_and_key_present(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KAINE_STATE_KEY", "11" * 32)
    crypto.install_from_section({"enabled": True})
    ok, reason = research_gate.run_preflight_self_check(require_encryption=True)
    assert ok is True
    assert reason is None


def test_preflight_fails_when_encryption_required_but_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    crypto._active = crypto.StateEncryptor(crypto.CryptoConfig())
    ok, reason = research_gate.run_preflight_self_check(require_encryption=True)
    assert ok is False


def test_evaluate_safety_net_passes_require_encryption(monkeypatch):
    recorded = []

    def _recorder(*, require_encryption: bool = False):
        recorded.append(require_encryption)
        return True, None

    monkeypatch.setattr(research_gate, "run_preflight_self_check", _recorder)

    config_enabled = {
        "preservation": {
            "divergence_monitor": {"enabled": True},
            "welfare_response": {"enabled": True},
            "require_encryption": True,
        },
        "security": {"state_encryption": {"enabled": True}},
    }
    research_gate.evaluate_safety_net(config_enabled)
    assert recorded == [True]

    recorded.clear()
    config_disabled = {
        "preservation": {
            "divergence_monitor": {"enabled": True},
            "welfare_response": {"enabled": True},
            "require_encryption": True,
        },
        "security": {"state_encryption": {"enabled": False}},
    }
    research_gate.evaluate_safety_net(config_disabled)
    assert recorded == [False]
