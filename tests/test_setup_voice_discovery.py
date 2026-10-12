# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import httpx

from kaine.setup.__main__ import probe_services


class _FakeResp:
    def __init__(self, status_code: int, data: object) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> object:
        return self._data


def _voices_get(data: object):
    def fake_get(url: str, *, timeout: float, trust_env: bool):
        if url.endswith("/get_predefined_voices"):
            return _FakeResp(200, data)
        raise httpx.ConnectError(f"no route for {url}")

    return fake_get


def test_probe_services_real_chatterbox_shape(monkeypatch):
    fake_get = _voices_get(
        [
            {"display_name": "Abigail", "filename": "Abigail.wav"},
            {"display_name": "Henry", "filename": "Henry.wav"},
        ]
    )
    monkeypatch.setattr(httpx, "get", fake_get)
    result = probe_services(timeout_s=1.0)
    assert result["voices"] == ["Abigail.wav", "Henry.wav"]


def test_probe_services_plain_list_of_filenames(monkeypatch):
    monkeypatch.setattr(httpx, "get", _voices_get(["Abigail.wav", "Henry.wav"]))
    result = probe_services(timeout_s=1.0)
    assert result["voices"] == ["Abigail.wav", "Henry.wav"]


def test_probe_services_unexpected_payload_leaves_voices_empty(monkeypatch):
    monkeypatch.setattr(httpx, "get", _voices_get(123))
    result = probe_services(timeout_s=1.0)
    assert result["voices"] == []


def test_probe_services_unreachable_chatterbox_leaves_voices_empty(monkeypatch):
    def fake_get(url: str, *, timeout: float, trust_env: bool):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)
    result = probe_services(timeout_s=1.0)
    assert result["voices"] == []
