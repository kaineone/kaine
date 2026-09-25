# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.cycle.caretaker — content-free caretaker notices."""
from __future__ import annotations

import http.server
import json
import logging
import socket
import subprocess
import threading
from functools import partial
from pathlib import Path

import pytest

from kaine.cycle.caretaker import (
    NOTICE_FIELDS,
    CaretakerConfig,
    CaretakerConfigError,
    ChannelConfig,
    ChannelResult,
    build_notice,
    check_caretaker_condition,
    is_allowed_address,
    load_token,
    notify,
    render_text,
    send_desktop,
    send_http,
    send_refusal_notice,
)


def test_config_defaults():
    cfg = CaretakerConfig.from_section({})
    assert cfg.install_label == "kaine"
    assert cfg.channels == ()
    assert cfg.reminder_interval_s == 14400.0
    assert cfg.input_loss_after_s == 60.0
    assert cfg.nexus_url == "http://127.0.0.1:8088/"


def test_config_unknown_key():
    with pytest.raises(CaretakerConfigError):
        CaretakerConfig.from_section({"unknown": 1})


@pytest.mark.parametrize(
    "label",
    ["", "a" * 65, "bad!label", " ", " lab", "lab "],
)
def test_config_bad_label(label):
    with pytest.raises(CaretakerConfigError, match="install_label"):
        CaretakerConfig.from_section({"install_label": label})


def test_config_good_label_with_inner_space():
    cfg = CaretakerConfig.from_section({"install_label": "my lab"})
    assert cfg.install_label == "my lab"


def test_config_reminder_interval_too_short():
    with pytest.raises(CaretakerConfigError, match="reminder_interval_s"):
        CaretakerConfig.from_section({"reminder_interval_s": 899})


def test_config_reminder_interval_bool_rejected():
    with pytest.raises(CaretakerConfigError, match="reminder_interval_s"):
        CaretakerConfig.from_section({"reminder_interval_s": True})


def test_config_input_loss_non_positive():
    with pytest.raises(CaretakerConfigError, match="input_loss_after_s"):
        CaretakerConfig.from_section({"input_loss_after_s": 0})


def test_config_input_loss_bool_rejected():
    with pytest.raises(CaretakerConfigError, match="input_loss_after_s"):
        CaretakerConfig.from_section({"input_loss_after_s": True})


def test_config_http_public_ip_literal_rejected():
    with pytest.raises(CaretakerConfigError, match="public|disallowed"):
        CaretakerConfig.from_section(
            {"channels": [{"kind": "http", "url": "http://8.8.8.8/x"}]}
        )


def test_config_http_private_ip_literal_accepted():
    cfg = CaretakerConfig.from_section(
        {"channels": [{"kind": "http", "url": "http://10.0.0.5/x"}]}
    )
    assert cfg.channels == (ChannelConfig(kind="http", url="http://10.0.0.5/x"),)


def test_config_http_url_with_credentials_rejected():
    with pytest.raises(CaretakerConfigError, match="credentials|token_name"):
        CaretakerConfig.from_section(
            {"channels": [{"kind": "http", "url": "http://user:pw@10.0.0.5/x"}]}
        )


def test_config_http_hostname_accepted_at_config_time():
    cfg = CaretakerConfig.from_section(
        {"channels": [{"kind": "http", "url": "https://ntfy.example.lan/kaine"}]}
    )
    assert cfg.channels[0].url == "https://ntfy.example.lan/kaine"


@pytest.mark.parametrize(
    "token_name",
    ["", "UPPER", "has-space", "a" * 65],
)
def test_config_bad_token_name(token_name):
    with pytest.raises(CaretakerConfigError, match="token_name"):
        CaretakerConfig.from_section(
            {
                "channels": [
                    {
                        "kind": "http",
                        "url": "http://10.0.0.1/x",
                        "token_name": token_name,
                    }
                ]
            }
        )


def test_config_token_name_error_message():
    with pytest.raises(CaretakerConfigError) as excinfo:
        CaretakerConfig.from_section(
            {
                "channels": [
                    {"kind": "http", "url": "http://10.0.0.5/x", "token_name": "BAD"}
                ]
            }
        )
    msg = str(excinfo.value)
    assert "must match ^[a-z0-9_]{1,64}$" in msg
    assert "{1,64}" in msg
    assert "{{1,64}}" not in msg


def test_config_desktop_with_url_rejected():
    with pytest.raises(CaretakerConfigError, match="desktop channel"):
        CaretakerConfig.from_section(
            {"channels": [{"kind": "desktop", "url": "http://10.0.0.1/x"}]}
        )


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("127.0.0.1", True),
        ("10.1.2.3", True),
        ("172.16.0.1", True),
        ("172.32.0.1", False),
        ("192.168.1.1", True),
        ("100.64.0.1", True),
        ("100.128.0.1", False),
        ("8.8.8.8", False),
        ("::1", True),
        ("fd00::1", True),
        ("fe80::1", False),
        ("::ffff:10.0.0.1", True),
        ("::ffff:8.8.8.8", False),
        ("garbage", False),
    ],
)
def test_is_allowed_address(ip, expected):
    assert is_allowed_address(ip) is expected


def test_build_notice_has_exactly_notice_fields():
    cfg = CaretakerConfig(install_label="lab", nexus_url="http://127.0.0.1:8088/")
    notice = build_notice(
        "starting_unattended", cfg, conditions={"1_x": True, "2_y": False}
    )
    assert set(notice.keys()) == set(NOTICE_FIELDS)
    assert notice["event"] == "starting_unattended"
    assert notice["conditions"] == {"1_x": True, "2_y": False}
    assert notice["time"].endswith("+00:00") or notice["time"].endswith("Z")


def test_build_notice_rejects_unknown_event():
    cfg = CaretakerConfig()
    with pytest.raises(ValueError, match="unknown caretaker event"):
        build_notice("not_an_event", cfg)


def test_build_notice_rejects_free_text_argument():
    cfg = CaretakerConfig()
    with pytest.raises(TypeError):
        build_notice("starting_unattended", cfg, free_text="hello")


def test_render_text_names_failed_conditions():
    notice = build_notice(
        "unattended_refused",
        CaretakerConfig(),
        conditions={"1_a": True, "2_b": False, "3_c": False},
    )
    title, message = render_text(notice)
    assert title == "KAINE kaine: unattended start refused"
    assert "2_b" in message
    assert "3_c" in message
    assert "1_a" not in message
    assert notice["nexus_url"] in message


def test_render_text_without_conditions():
    notice = build_notice("boot_failed", CaretakerConfig())
    title, message = render_text(notice)
    assert title == "KAINE kaine: boot failed"
    assert "Failed gate conditions" not in message
    assert notice["nexus_url"] in message


def _gvariant_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def test_send_desktop_accepted():
    notice = build_notice("starting_unattended", CaretakerConfig())

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="(uint32 7,)\n", stderr=""
        )

    result = send_desktop(notice, runner=runner)
    assert result.accepted
    assert result.detail == ""


def test_send_desktop_rejected_on_nonzero_exit():
    notice = build_notice("starting_unattended", CaretakerConfig())

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(
            args=argv, returncode=1, stdout="", stderr="no session bus"
        )

    result = send_desktop(notice, runner=runner)
    assert not result.accepted
    assert "exit 1" in result.detail


def test_send_desktop_argv_carries_gvariant_quoted_title():
    notice = build_notice("starting_unattended", CaretakerConfig())
    captured = []

    def runner(argv, **kwargs):
        captured.append(argv)
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout="(uint32 1,)\n", stderr=""
        )

    send_desktop(notice, runner=runner)
    title, message = render_text(notice)
    # Title is at argv index 12; message is at index 13.
    assert captured[0][12] == _gvariant_string(title)
    assert captured[0][13] == _gvariant_string(message)


def test_send_desktop_gdbus_missing(monkeypatch):
    monkeypatch.setattr("kaine.cycle.caretaker.shutil.which", lambda _bin: None)
    notice = build_notice("starting_unattended", CaretakerConfig())
    result = send_desktop(notice)
    assert not result.accepted
    assert result.detail == "gdbus not installed"


def test_send_desktop_timeout():
    notice = build_notice("starting_unattended", CaretakerConfig())

    def runner(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

    result = send_desktop(notice, runner=runner)
    assert not result.accepted
    assert result.detail == "TimeoutExpired"


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    def __init__(self, store, status, *args, **kwargs):
        self.store = store
        self.status = status
        super().__init__(*args, **kwargs)

    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.store["method"] = self.command
        self.store["path"] = self.path
        self.store["headers"] = {k.lower(): v for k, v in self.headers.items()}
        self.store["body"] = body
        self.send_response(self.status)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _start_server(store, status=200):
    handler = partial(_RecordingHandler, store, status)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_send_http_accepted():
    store: dict = {}
    server = _start_server(store)
    try:
        _, port = server.server_address
        cfg = CaretakerConfig(install_label="lab", nexus_url="http://127.0.0.1:8088/")
        notice = build_notice(
            "starting_unattended", cfg, conditions={"1_x": True}
        )
        url = f"http://127.0.0.1:{port}/notify"
        result = send_http(notice, url, token=None)
        assert result.accepted

        assert store["method"] == "POST"
        payload = json.loads(store["body"])
        assert "title" in payload
        assert "message" in payload
        for field in NOTICE_FIELDS:
            assert field in payload
        assert store["headers"]["host"] == f"127.0.0.1:{port}"
    finally:
        server.shutdown()


def test_send_http_host_header_with_explicit_port():
    store: dict = {}
    server = _start_server(store)
    try:
        _, port = server.server_address
        notice = build_notice("starting_unattended", CaretakerConfig())
        url = f"http://127.0.0.1:{port}/notify"
        result = send_http(notice, url, token=None)
        assert result.accepted
        assert store["headers"]["host"] == f"127.0.0.1:{port}"
    finally:
        server.shutdown()


def test_send_http_includes_bearer_token_and_no_token_in_result(caplog):
    caplog.set_level(logging.INFO, logger="kaine.cycle.caretaker")
    store: dict = {}
    server = _start_server(store)
    try:
        _, port = server.server_address
        notice = build_notice("starting_unattended", CaretakerConfig())
        url = f"http://127.0.0.1:{port}/notify"
        token = "secret-token-xyz"
        result = send_http(notice, url, token=token)
        assert result.accepted
        assert store["headers"]["authorization"] == f"Bearer {token}"
        assert token not in result.detail
        assert token not in caplog.text
    finally:
        server.shutdown()


def test_send_http_500_not_accepted():
    store: dict = {}
    server = _start_server(store, status=500)
    try:
        _, port = server.server_address
        notice = build_notice("starting_unattended", CaretakerConfig())
        result = send_http(notice, f"http://127.0.0.1:{port}/notify", token=None)
        assert not result.accepted
        assert "500" in result.detail
    finally:
        server.shutdown()


def test_send_http_url_with_credentials_not_sent(caplog):
    caplog.set_level(logging.INFO, logger="kaine.cycle.caretaker")
    store: dict = {}
    server = _start_server(store)
    try:
        _, port = server.server_address
        notice = build_notice("starting_unattended", CaretakerConfig())
        url = f"http://user:pw@127.0.0.1:{port}/notify"
        result = send_http(notice, url, token="secret-token")
        assert not result.accepted
        assert result.detail == "url contains credentials"
        assert "method" not in store
        assert "pw" not in result.detail
        assert "pw" not in caplog.text
    finally:
        server.shutdown()


def test_send_http_public_resolver_rejects_and_sends_nothing():
    store: dict = {}
    server = _start_server(store)

    def resolver(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", port))]

    try:
        _, port = server.server_address
        notice = build_notice("starting_unattended", CaretakerConfig())
        url = f"http://example.lan:{port}/notify"
        result = send_http(notice, url, token="secret-token", resolver=resolver)
        assert not result.accepted
        assert "public address" in result.detail
        assert "method" not in store
        assert "secret-token" not in result.detail
    finally:
        server.shutdown()


def test_send_http_mixed_addresses_rejects_and_sends_nothing():
    def resolver(host, port, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", port)),
        ]

    notice = build_notice("starting_unattended", CaretakerConfig())
    result = send_http(notice, "http://example.lan/notify", token=None, resolver=resolver)
    assert not result.accepted
    assert "public address" in result.detail


def test_send_http_empty_resolver_answer():
    def resolver(host, port, **kwargs):
        return []

    notice = build_notice("starting_unattended", CaretakerConfig())
    result = send_http(notice, "http://example.lan/notify", token=None, resolver=resolver)
    assert not result.accepted
    assert result.detail == "could not resolve host"


def test_load_token_from_secrets_file(tmp_path):
    secrets = tmp_path / "config" / "secrets.toml"
    secrets.parent.mkdir(parents=True)
    secrets.write_text('[caretaker.tokens]\nntfy = "my-token"\n', encoding="utf-8")
    assert load_token("ntfy", secrets_path=secrets) == "my-token"
    assert load_token("missing", secrets_path=secrets) is None
    assert load_token(None, secrets_path=secrets) is None


def test_load_token_malformed_secrets_logs_warning(tmp_path, caplog):
    secrets = tmp_path / "config" / "secrets.toml"
    secrets.parent.mkdir(parents=True)
    secrets.write_text("not valid toml = = =\n", encoding="utf-8")
    caplog.set_level(logging.WARNING, logger="kaine.cycle.caretaker")
    assert load_token("ntfy", secrets_path=secrets) is None
    assert "malformed secrets file" in caplog.text


def test_check_caretaker_condition_invalid_config():
    result = check_caretaker_condition(
        {"install_label": "bad!name"},
        prerequisites_ok=True,
        conditions={},
    )
    assert not result.ok
    assert "invalid [caretaker]" in result.reason


def test_check_caretaker_condition_no_channels():
    result = check_caretaker_condition(
        {"channels": []},
        prerequisites_ok=True,
        conditions={},
    )
    assert not result.ok
    assert result.reason == "no channel configured"


def test_check_caretaker_condition_prerequisites_not_ok_does_not_notify():
    calls = []

    def fake_notify(*args, **kwargs):
        calls.append(True)
        return []

    result = check_caretaker_condition(
        {"channels": [{"kind": "desktop"}]},
        prerequisites_ok=False,
        conditions={},
        notify_fn=fake_notify,
    )
    assert not result.ok
    assert "not attempted" in result.reason
    assert not calls


def test_check_caretaker_condition_one_channel_accepted():
    def fake_notify(*args, **kwargs):
        return [
            ChannelResult(kind="desktop", accepted=False, detail="no gdbus"),
            ChannelResult(kind="http", accepted=True, detail=""),
        ]

    result = check_caretaker_condition(
        {"channels": [{"kind": "desktop"}, {"kind": "http", "url": "http://10.0.0.1/x"}]},
        prerequisites_ok=True,
        conditions={},
        notify_fn=fake_notify,
    )
    assert result.ok


def test_check_caretaker_condition_no_channel_accepted():
    def fake_notify(*args, **kwargs):
        return [
            ChannelResult(kind="desktop", accepted=False, detail="no gdbus"),
            ChannelResult(kind="http", accepted=False, detail="timeout"),
        ]

    result = check_caretaker_condition(
        {"channels": [{"kind": "desktop"}, {"kind": "http", "url": "http://10.0.0.1/x"}]},
        prerequisites_ok=True,
        conditions={},
        notify_fn=fake_notify,
    )
    assert not result.ok
    assert "desktop: no gdbus" in result.reason
    assert "http: timeout" in result.reason


def test_send_refusal_notice_swallows_raising_notify_fn():
    def bad_notify(*args, **kwargs):
        raise RuntimeError("boom")

    # Must not raise.
    send_refusal_notice(
        {"channels": [{"kind": "desktop"}]},
        {"1_x": False},
        notify_fn=bad_notify,
    )


def test_send_refusal_notice_invalid_config_is_silent():
    # Must not raise.
    send_refusal_notice({"bad_key": 1}, {})


def test_notify_logs_each_channel_result(caplog):
    caplog.set_level(logging.INFO, logger="kaine.cycle.caretaker")

    cfg = CaretakerConfig(
        channels=(
            ChannelConfig(kind="desktop"),
            ChannelConfig(kind="http", url="http://10.0.0.1/x", token_name="ntfy"),
        )
    )
    notice = build_notice("starting_unattended", cfg)

    def fake_desktop(n):
        return ChannelResult(kind="desktop", accepted=False, detail="no gdbus")

    def fake_http(n, url, token):
        return ChannelResult(kind="http", accepted=False, detail="timeout")

    results = notify(
        cfg,
        notice,
        secrets_path=Path("/nonexistent/secrets.toml"),
        desktop_sender=fake_desktop,
        http_sender=fake_http,
    )
    assert len(results) == 2
    assert "desktop" in caplog.text
    assert "http" in caplog.text
    assert "no gdbus" in caplog.text
    assert "timeout" in caplog.text
