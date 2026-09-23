import io
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kaine.config import ConfigShapeError, validate_config_shape
from kaine.lifecycle.__main__ import main as decommission_main
from kaine.nexus.__main__ import _build_fork_manager
from kaine.nexus.diagnostics import build_diagnostics_router
from kaine.research.__main__ import main as research_main
from kaine.security import crypto as crypto_module


def test_validate_config_shape_rejects_bool_security():
    with pytest.raises(ConfigShapeError, match=r"security expected table, got bool"):
        validate_config_shape({"security": False})


def test_validate_config_shape_rejects_list_security():
    with pytest.raises(ConfigShapeError, match=r"security expected table, got list"):
        validate_config_shape({"security": []})


def test_validate_config_shape_rejects_string_deployment():
    with pytest.raises(ConfigShapeError, match=r"deployment expected table, got str"):
        validate_config_shape({"deployment": "tier1"})


def _write_configs(root: Path, base: str = "", operator: str = "") -> None:
    cfg_dir = root / "config"
    cfg_dir.mkdir()
    (cfg_dir / "kaine.toml").write_text(base, encoding="utf-8")
    if operator:
        (cfg_dir / "kaine.operator.toml").write_text(operator, encoding="utf-8")


def test_research_main_rejects_malformed_operator_overlay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_configs(
        tmp_path,
        base="[research_submission]\nenabled = false\n",
        operator='[modules]\nsoma = "false"\n',
    )

    out = io.StringIO()
    err = io.StringIO()
    code = research_main(
        ["--config", "config/kaine.toml", "--preview"],
        out=out,
        err=err,
    )

    assert code == 2
    assert "research: configuration error:" in err.getvalue()


def test_decommission_main_rejects_malformed_overlay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_configs(
        tmp_path,
        base="[research_submission]\nenabled = false\n",
        operator='[modules]\nsoma = "false"\n',
    )

    state_root = tmp_path / "state"
    state_root.mkdir()
    sentinel = state_root / "entity.dat"
    sentinel.write_text("keep", encoding="utf-8")

    backup_root = tmp_path / "backups"
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")

    out = io.StringIO()
    err = io.StringIO()
    code = decommission_main(
        [
            "--state-root",
            str(state_root),
            "--out-root",
            str(backup_root),
            "--dry-run",
        ],
        out=out,
        err=err,
    )

    assert code == 2
    assert "decommission: configuration error:" in err.getvalue()
    assert sentinel.exists()
    assert not backup_root.exists() or not any(backup_root.iterdir())


def test_decommission_main_rejects_missing_encryption_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_configs(
        tmp_path,
        base="[security]\n[security.state_encryption]\nenabled = true\n",
    )

    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    monkeypatch.setattr(crypto_module, "_load_key_from_keyring", lambda: None)

    state_root = tmp_path / "state"
    state_root.mkdir()
    sentinel = state_root / "entity.dat"
    sentinel.write_text("keep", encoding="utf-8")

    backup_root = tmp_path / "backups"
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")

    out = io.StringIO()
    err = io.StringIO()
    code = decommission_main(
        [
            "--state-root",
            str(state_root),
            "--out-root",
            str(backup_root),
            "--dry-run",
        ],
        out=out,
        err=err,
    )

    assert code == 2
    assert "state-encryption setup failed" in err.getvalue()
    assert sentinel.exists()
    assert not backup_root.exists() or not any(backup_root.iterdir())


def test_nexus_build_fork_manager_fails_closed_on_missing_key(monkeypatch, caplog):
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    monkeypatch.setattr(crypto_module, "_load_key_from_keyring", lambda: None)

    with caplog.at_level(logging.ERROR, logger="kaine.nexus"):
        result = _build_fork_manager(lambda: {}, lambda: {"enabled": True})

    assert result is None
    assert any("CryptoConfigError" in rec.message for rec in caplog.records)


def test_nexus_forks_json_reports_disabled_when_no_fork_manager():
    app = FastAPI()
    bridge = MagicMock()
    router = build_diagnostics_router(
        bridge,
        fork_manager=None,
        metrics_snapshot=lambda: {},
    )
    app.include_router(router)

    response = TestClient(app).get("/diagnostics/forks.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["forks"] == []
    assert payload["available"] is False
    assert "fork operations are disabled" in payload["reason"]
