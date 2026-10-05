# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import yaml

import kaine.cycle.preflight as pf
from kaine.defaults import MODEL_SERVER_API_KEY_ENV


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _make_fake_get(captured):
    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp({"data": [{"id": "m1"}]})

    return fake_get


def test_preflight_resident_models_sends_bearer_key(monkeypatch):
    monkeypatch.setenv(MODEL_SERVER_API_KEY_ENV, "k-test")
    captured = {}

    monkeypatch.setattr(pf.httpx, "get", _make_fake_get(captured))

    result = pf._server_resident_models("http://organ:8080/v1", 2.0)

    assert result == ["m1"]
    assert captured["url"] == "http://organ:8080/v1/models"
    assert captured["headers"] == {"Authorization": "Bearer k-test"}


def test_preflight_resident_models_without_key_sends_no_auth(monkeypatch):
    monkeypatch.delenv(MODEL_SERVER_API_KEY_ENV, raising=False)
    captured = {}

    monkeypatch.setattr(pf.httpx, "get", _make_fake_get(captured))

    result = pf._server_resident_models("http://organ:8080/v1", 2.0)

    assert result == ["m1"]
    assert "Authorization" not in (captured.get("headers") or {})


def test_organ_healthchecks_probe_public_health_endpoint():
    REPO = Path(__file__).resolve().parents[1]

    compose_text = (REPO / "compose" / "kaine.yml").read_text()
    compose = yaml.safe_load(compose_text)
    health_test = compose["services"]["kaine-model-server"]["healthcheck"]["test"]

    container_text = (REPO / "quadlet" / "kaine-model-server.container").read_text()
    health_cmd = next(
        line for line in container_text.splitlines() if line.startswith("HealthCmd=")
    )

    assert any("http://127.0.0.1:8080/health" in entry for entry in health_test)
    assert not any("/v1/models" in entry for entry in health_test)

    assert "http://127.0.0.1:8080/health" in health_cmd
    assert "/v1/models" not in health_cmd
