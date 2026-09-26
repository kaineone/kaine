# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration tests of the real unattended gate stack.

These tests replace _boot_and_run with a recorder so no entity ever boots.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import socket
import threading
from pathlib import Path
from typing import Any

import pytest

if importlib.util.find_spec("pytest_timeout") is not None:
    pytestmark = pytest.mark.timeout(120)


def _set_plaintext_encryptor() -> None:
    from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "KAINE_CYCLE_OPERATOR_PRESENT",
        "KAINE_RESEARCH_MODE",
        "KAINE_CYCLE_UNATTENDED",
        "KAINE_PROFILE",
    ):
        monkeypatch.delenv(key, raising=False)


def _make_config(port: int) -> dict[str, Any]:
    return {
        "cycle": {"supervision_mode": "unattended"},
        "preservation": {
            "divergence_monitor": {"enabled": True},
            "welfare_response": {"enabled": True},
            # State encryption stays off in this fixture, so it must not be
            # required (condition 5 is exercised by the research-gate tests).
            "require_encryption": False,
        },
        "evaluation": {"enabled": True},
        "spot": {"enabled": True},
        "caretaker": {
            "channels": [{"kind": "http", "url": f"http://127.0.0.1:{port}/notify"}]
        },
        "perception_feed": {"mode": "seeded", "seed": 0},
        "modules": {"topos": True},
        "topos": {"capture_width": 64, "capture_height": 48},
    }


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]) -> None:
    def _load_config(profile: str | None = None) -> dict[str, Any]:
        return config

    monkeypatch.setattr("kaine.cycle.__main__._load_kaine_config", _load_config)


def _async_recorder(calls: list[dict[str, Any]]) -> Any:
    async def recorder(*, supervision_mode: str, gate_checks: dict[str, bool]) -> int:
        calls.append({"supervision_mode": supervision_mode, "gate_checks": gate_checks})
        return 0

    return recorder


def _read_gate_record(tmp_path: Path) -> dict[str, Any] | None:
    incidents = tmp_path / "state" / "cycle" / "incidents"
    if not incidents.exists():
        return None
    for path in sorted(incidents.glob("unattended_gate-*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                return json.loads(line)
    return None


def _set_nested(config: dict[str, Any], path: list[str], value: Any) -> None:
    d = config
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server():
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            self.server.posts.append(body)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args) -> None:  # type: ignore[override]
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.posts: list[bytes] = []
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, srv.server_address[1]
    srv.shutdown()
    thread.join()


def test_unattended_gate_healthy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, http_server, capsys
):
    server, port = http_server
    _set_plaintext_encryptor()
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    config = _make_config(port)
    _patch_config(monkeypatch, config)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "kaine.cycle.__main__._boot_and_run", _async_recorder(calls)
    )

    from kaine.cycle.__main__ import main

    rc = main([])
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["supervision_mode"] == "unattended"
    assert len(calls[0]["gate_checks"]) == 8
    assert all(calls[0]["gate_checks"].values())

    assert len(server.posts) == 1
    payload = json.loads(server.posts[0])
    assert payload.get("event") == "starting_unattended"

    record = _read_gate_record(tmp_path)
    assert record is not None
    assert record["transition"] == "gate"
    assert record["ok"] is True


@pytest.mark.parametrize(
    "path,value,number",
    [
        (["preservation", "divergence_monitor", "enabled"], False, 1),
        (["preservation", "welfare_response", "enabled"], False, 2),
        (["evaluation", "enabled"], False, 3),
        (["spot", "enabled"], False, 6),
        (["perception_feed", "mode"], "off", 8),
    ],
)
def test_unattended_gate_refuses_one_condition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    http_server,
    capsys,
    path: list[str],
    value: Any,
    number: int,
):
    server, port = http_server
    _set_plaintext_encryptor()
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    config = _make_config(port)
    _set_nested(config, path, value)
    _patch_config(monkeypatch, config)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "kaine.cycle.__main__._boot_and_run", _async_recorder(calls)
    )

    from kaine.cycle.__main__ import main

    rc = main([])
    assert rc == 6
    assert not calls

    err = capsys.readouterr().err
    assert str(number) in err

    assert len(server.posts) == 1
    payload = json.loads(server.posts[0])
    assert payload.get("event") == "unattended_refused"

    record = _read_gate_record(tmp_path)
    assert record is not None
    assert record["transition"] == "gate"
    assert record["ok"] is False


def test_unattended_gate_refuses_when_caretaker_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, http_server, capsys
):
    server, _ = http_server
    _set_plaintext_encryptor()
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)

    bad_port = _unused_port()
    config = _make_config(bad_port)
    _patch_config(monkeypatch, config)

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "kaine.cycle.__main__._boot_and_run", _async_recorder(calls)
    )

    from kaine.cycle.__main__ import main

    rc = main([])
    assert rc == 6
    assert not calls

    err = capsys.readouterr().err
    assert "7" in err
    assert not server.posts
