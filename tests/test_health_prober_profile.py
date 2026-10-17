# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import pytest

from kaine.dashboard.health.config import load_health_prober


def _clear_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAINE_PROFILE", raising=False)
    monkeypatch.delenv("KAINE_TIER", raising=False)


def _write_base_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "kaine.toml").write_text(
        "[modules]\nsequence = false\nvision = false\n"
    )


def _write_profile(
    tmp_path: Path, name: str, *, sequence: bool, vision: bool
) -> None:
    profiles_dir = tmp_path / "config" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / name).write_text(
        f"[modules]\nsequence = {str(sequence).lower()}\n"
        f"vision = {str(vision).lower()}\n"
    )


def _load_prober(tmp_path: Path) -> object:
    return load_health_prober(
        kaine_toml=tmp_path / "config" / "kaine.toml",
        secrets_toml=tmp_path / "absent-secrets.toml",
    )


def test_health_prober_default_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_profile_env(monkeypatch)
    _write_base_config(tmp_path)
    _write_profile(tmp_path, "first_configuration.toml", sequence=True, vision=True)
    monkeypatch.chdir(tmp_path)

    prober = _load_prober(tmp_path)

    assert prober.modules_enabled["sequence"] is True
    assert prober.modules_enabled["vision"] is True


def test_health_prober_operator_overlay_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_env(monkeypatch)
    _write_base_config(tmp_path)
    _write_profile(tmp_path, "first_configuration.toml", sequence=True, vision=True)
    (tmp_path / "config" / "kaine.operator.toml").write_text(
        "[modules]\nvision = false\n"
    )
    monkeypatch.chdir(tmp_path)

    prober = _load_prober(tmp_path)

    assert prober.modules_enabled["sequence"] is True
    assert prober.modules_enabled["vision"] is False


def test_health_prober_explicit_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_env(monkeypatch)
    _write_base_config(tmp_path)
    _write_profile(tmp_path, "first_configuration.toml", sequence=True, vision=True)
    _write_profile(tmp_path, "other.toml", sequence=True, vision=False)
    monkeypatch.setenv("KAINE_PROFILE", "other")
    monkeypatch.chdir(tmp_path)

    prober = _load_prober(tmp_path)

    assert prober.modules_enabled["sequence"] is True
    assert prober.modules_enabled["vision"] is False


def test_health_prober_no_profiles_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_profile_env(monkeypatch)
    _write_base_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    prober = _load_prober(tmp_path)

    assert prober.modules_enabled["sequence"] is False
    assert prober.modules_enabled["vision"] is False
