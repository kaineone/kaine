# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for resume-releases-operator-freeze (named override of protective freezes)."""

import json
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kaine.cycle import control_state as cs
from kaine.nexus.config import NexusConfig
from kaine.nexus.cycle_control import build_cycle_control_router


def _app(tmp_path, *, read_only=False):
    ctrl = tmp_path / "control.json"
    audit = tmp_path / "audit.jsonl"
    app = FastAPI()
    app.state.config = NexusConfig(
        operator_token="test-token",
        host_allowlist=("127.0.0.1", "localhost", "testserver"),
        read_only=read_only,
    )
    app.include_router(
        build_cycle_control_router(control_path=ctrl, audit_path=audit)
    )
    return app, ctrl, audit


# ---- control state ----------------------------------------------------------


def test_stand_down_operator_leaves_welfare(tmp_path):
    p = tmp_path / "control.json"
    cs.freeze("op freeze", path=p, source="operator")
    cs.freeze("welfare pause", path=p, source="welfare")
    c = cs.stand_down(p, source="operator")
    assert c.frozen is True
    assert [h["source"] for h in c.holders] == ["welfare"]
    assert cs.read_control(p).frozen is True


def test_override_lifts_welfare_and_audits(tmp_path):
    p = tmp_path / "control.json"
    audit = tmp_path / "audit.jsonl"
    cs.freeze("op freeze", path=p, source="operator")
    cs.freeze("welfare pause", path=p, source="welfare")
    cs.stand_down(p, source="operator")
    c = cs.override(["welfare"], path=p, audit_path=audit)
    assert c.frozen is False
    assert c.holders == []
    assert cs.read_control(p).frozen is False
    lines = audit.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record.keys()) == {"at", "sources", "remaining"}
    assert record["sources"] == ["welfare"]
    assert record["remaining"] == []
    assert stat.S_IMODE(audit.stat().st_mode) == 0o600


def test_override_rejects_self_releasing_and_unknown(tmp_path):
    p = tmp_path / "control.json"
    with pytest.raises(ValueError, match="spot"):
        cs.override(["spot"], path=p)
    with pytest.raises(ValueError, match="preserve"):
        cs.override(["preserve"], path=p)
    with pytest.raises(ValueError, match="nonsense"):
        cs.override(["nonsense"], path=p)


def test_override_rejects_empty_sources(tmp_path):
    p = tmp_path / "control.json"
    with pytest.raises(ValueError):
        cs.override([], path=p)


def test_override_rejects_inactive_source(tmp_path):
    p = tmp_path / "control.json"
    cs.freeze("welfare pause", path=p, source="welfare")
    with pytest.raises(LookupError, match="gestation"):
        cs.override(["gestation"], path=p)


# ---- Nexus router -----------------------------------------------------------


def test_resume_leaves_welfare_and_returns_holders(tmp_path):
    app, ctrl, _ = _app(tmp_path)
    cs.freeze("op freeze", path=ctrl, source="operator")
    cs.freeze("welfare pause", path=ctrl, source="welfare")
    client = TestClient(app)
    r = client.post(
        "/diagnostics/cycle/freeze",
        json={"frozen": False},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["frozen"] is True
    assert [h["source"] for h in data["holders"]] == ["welfare"]
    assert cs.read_control(ctrl).frozen is True


def test_override_confirmed_lifts_welfare(tmp_path):
    app, ctrl, audit = _app(tmp_path)
    cs.freeze("welfare pause", path=ctrl, source="welfare")
    client = TestClient(app)
    r = client.post(
        "/diagnostics/cycle/override",
        json={"sources": ["welfare"], "confirm": "welfare"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["frozen"] is False
    assert data["holders"] == []
    assert cs.read_control(ctrl).frozen is False
    lines = audit.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record.keys()) == {"at", "sources", "remaining"}


def test_override_mismatched_confirm_is_refused(tmp_path):
    app, ctrl, _ = _app(tmp_path)
    cs.freeze("welfare pause", path=ctrl, source="welfare")
    client = TestClient(app)
    r = client.post(
        "/diagnostics/cycle/override",
        json={"sources": ["welfare"], "confirm": "not welfare"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "confirm must repeat the sources being overridden"
    assert cs.read_control(ctrl).frozen is True


def test_override_self_releasing_source_is_refused(tmp_path):
    app, _, _ = _app(tmp_path)
    client = TestClient(app)
    r = client.post(
        "/diagnostics/cycle/override",
        json={"sources": ["spot"], "confirm": "spot"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 422
    assert "spot" in r.json()["detail"]


def test_override_unknown_source_is_refused(tmp_path):
    app, _, _ = _app(tmp_path)
    client = TestClient(app)
    r = client.post(
        "/diagnostics/cycle/override",
        json={"sources": ["nonsense"], "confirm": "nonsense"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 422


def test_override_inactive_source_is_409(tmp_path):
    app, ctrl, _ = _app(tmp_path)
    cs.freeze("welfare pause", path=ctrl, source="welfare")
    client = TestClient(app)
    r = client.post(
        "/diagnostics/cycle/override",
        json={"sources": ["gestation"], "confirm": "gestation"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 409
    assert "gestation" in r.json()["detail"]
    assert cs.read_control(ctrl).frozen is True


def test_override_refused_in_read_only_mode():
    # Read-only mode is enforced by the real app's middleware, before any route.
    from unittest.mock import AsyncMock

    from kaine.nexus.app import create_app

    bridge = AsyncMock()

    async def history_loader(lookback):
        return []

    config = NexusConfig(access="open", read_only=True, operator_token="")
    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {},
    )
    client = TestClient(app, base_url="http://127.0.0.1:8088")
    r = client.post(
        "/diagnostics/cycle/override",
        json={"sources": ["welfare"], "confirm": "welfare"},
        headers={"Origin": "http://127.0.0.1:8088"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Nexus is in read-only mode: controls are off"
