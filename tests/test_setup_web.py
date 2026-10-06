# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the browser first-run setup server (slice 2)."""
from __future__ import annotations

import copy
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from kaine.bus.config import load_bus_config, load_bus_endpoint
from kaine.bus.errors import BusConfigError
from kaine.config import SHIPPED_CONFIG_PATH
from kaine.hardware import describe_host
from kaine.setup.web import create_setup_app, guard, serve
from kaine.setup.wizard import ACK_PHRASE, run_wizard


def _shipped_config(tmp_path: Path) -> Path:
    """Return a real shipped config path, or a minimal fallback."""
    real = Path(SHIPPED_CONFIG_PATH)
    if real.exists():
        return real
    fallback = tmp_path / "kaine.toml"
    fallback.write_text(
        "[lingua]\nmodel_id = 'model-a'\n[vox]\nbackend = 'chatterbox'\n"
        "predefined_voice_id = 'voice-a'\n[audition]\nbackend = 'speaches'\n"
        "stt_model = 'stt-a'\n"
    )
    return fallback


def _mk_app(tmp_path: Path, **overrides) -> object:
    state_root = tmp_path / "state"
    operator_path = tmp_path / "kaine.operator.toml"
    shipped = _shipped_config(tmp_path)

    kwargs = {
        "state_root": state_root,
        "operator_path": operator_path,
        "shipped_config_path": shipped,
        "host": describe_host(),
        "probe_services": lambda: {},
        "recommend_tier_fn": lambda: None,
        "device_consumers_fn": lambda: [],
        "services_up_fn": lambda: {},
        "storage_old_root": tmp_path,
    }
    kwargs.update(overrides)
    return create_setup_app(**kwargs)


@pytest.fixture(autouse=True)
def _isolated_guard(monkeypatch):
    monkeypatch.setattr(guard, "load_bus_config", lambda *a, **k: object())
    monkeypatch.setattr(
        guard, "cycle_on_bus", lambda *a, **k: (False, "stub: no cycle on the bus")
    )
    monkeypatch.setattr(
        guard, "cycle_process_details", lambda *a, **k: (False, None, None)
    )


def _session_client(app, base_url="http://127.0.0.1:8000"):
    return TestClient(app, base_url=base_url)


def _exchange_token(client, app, headers=None):
    token = app.state.setup.store.issue()
    port = getattr(app.state, "port", 8000)
    h = {"Host": f"127.0.0.1:{port}"}
    if headers:
        h.update(headers)
    r = client.get(f"/?token={token}", headers=h, follow_redirects=False)
    return r, token


def test_token_exchange_creates_strict_session(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, token = _exchange_token(client, app)
    assert r.status_code in (302, 303)
    set_cookie = r.headers.get("set-cookie", "")
    assert "setup_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie

    # Reuse is rejected.
    r2 = client.get(
        f"/?token={token}",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r2.status_code == 403
    assert "expired" in r2.text.lower() or "already" in r2.text.lower()


def test_token_expires_after_two_minutes(tmp_path):
    class Clock:
        def __init__(self):
            self.t = 0.0

        def now(self):
            return self.t

    clock = Clock()
    app = _mk_app(tmp_path, now=clock.now)
    client = _session_client(app)
    token = app.state.setup.store.issue()
    clock.t += 130
    r = client.get(
        f"/?token={token}",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_routes_require_session(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)

    for path in ["/step", "/static/style.css", "/review"]:
        r = client.get(
            path,
            headers={"Host": "127.0.0.1:8000"},
            follow_redirects=False,
        )
        assert r.status_code == 403, path
        assert "session required" in r.text.lower()


def test_unauthenticated_request_does_not_refresh_activity(tmp_path):
    class Clock:
        def __init__(self):
            self.t = 0.0

        def now(self):
            return self.t

    clock = Clock()
    app = _mk_app(tmp_path, now=clock.now)
    client = _session_client(app)

    clock.t = 50.0
    r = client.get(
        "/static/style.css",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert app.state.last_activity == 0.0

    # Nor does a failed token exchange.
    clock.t = 55.0
    r = client.get("/?token=not-a-real-token", headers={"Host": "127.0.0.1:8000"}, follow_redirects=False)
    assert r.status_code == 403
    assert app.state.last_activity == 0.0

    # An authenticated request does refresh it.
    clock.t = 60.0
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)
    assert app.state.last_activity == 60.0
    clock.t = 100.0
    r = client.get("/step", headers={"Host": "127.0.0.1:8000"}, follow_redirects=False)
    assert r.status_code == 200
    assert app.state.last_activity == 100.0


def test_host_check_rejects_evil_host(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r2 = client.get(
        "/step",
        headers={"Host": "evil.example:8000"},
        follow_redirects=False,
    )
    assert r2.status_code == 403
    assert "host not allowed" in r2.text.lower()


def test_host_check_uses_bound_port_when_set(tmp_path):
    app = _mk_app(tmp_path)
    app.state.port = 9999
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r2 = client.get(
        "/step",
        headers={"Host": "127.0.0.1:9999"},
        follow_redirects=False,
    )
    assert r2.status_code == 200


def test_state_changing_requires_origin(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    # Missing Origin.
    r2 = client.post(
        "/step",
        data={},
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r2.status_code == 403

    # Foreign Origin.
    r3 = client.post(
        "/step",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://evil.example",
        },
        follow_redirects=False,
    )
    assert r3.status_code == 403

    # Valid Origin: include the current step id so the POST is accepted.
    r_step = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r_step.status_code == 200
    m = re.search(r'data-step-id="([^"]+)"', r_step.text)
    assert m
    step_id = m.group(1)
    r4 = client.post(
        "/step",
        data={"_step_id": step_id},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r4.status_code in (302, 303)


def test_post_wrong_step_id_returns_409_and_leaves_session(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r_orient = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r_orient.status_code == 200
    m = re.search(r'data-step-id="([^"]+)"', r_orient.text)
    assert m
    orientation_id = m.group(1)

    r2 = client.post(
        "/step",
        data={"_step_id": orientation_id},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303)

    r3 = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r3.status_code == 200
    m = re.search(r'data-step-id="([^"]+)"', r3.text)
    assert m
    current_id = m.group(1)
    # A double-submit of the orientation form arrives while a later step is shown.
    assert current_id != orientation_id
    sid = client.cookies["setup_session"]
    sess = app.state.setup.store.sessions[sid]
    before_index = sess["step_index"]
    before_config = copy.deepcopy(sess["config"])

    r4 = client.post(
        "/step",
        data={"_step_id": orientation_id},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r4.status_code == 409
    assert "different step" in r4.text.lower()
    assert "no-store" in r4.headers.get("cache-control", "")
    assert sess["step_index"] == before_index
    assert sess["config"] == before_config


def test_post_missing_step_id_returns_409(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    sid = client.cookies["setup_session"]
    sess = app.state.setup.store.sessions[sid]
    before_index = sess["step_index"]

    r2 = client.post(
        "/step",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 409
    assert sess["step_index"] == before_index


def test_absent_boolean_field_uses_default(tmp_path):
    def probe_trainer(configured, backend):
        return (True, "/fake/trainer/python3:3.12")

    host = describe_host()
    host["accelerators"] = [{"type": "cuda", "model": "Fake GPU"}]
    host["cuda"] = True
    host["gpu"] = True
    host["backend"] = "cuda"

    app = _mk_app(tmp_path, host=host, probe_trainer=probe_trainer)
    client = _session_client(app)
    _exchange_token(client, app)

    for _ in range(200):
        r = client.get(
            "/step",
            headers={"Host": "127.0.0.1:8000"},
            follow_redirects=False,
        )
        if r.status_code in (302, 303):
            if "/review" in r.headers.get("location", ""):
                break
            continue
        assert r.status_code == 200
        m = re.search(r'data-step-id="([^"]+)"', r.text)
        assert m
        step_id = m.group(1)

        data = _defaults_from_form(r.text, step_id)
        data["_step_id"] = step_id
        if step_id == "welfare-acknowledgement":
            data["ack"] = ACK_PHRASE
        if step_id == "module-preset":
            data["preset"] = "b"
        if step_id == "trainer-provisioning":
            data["set_up_trainer"] = "yes"
            data.pop("record_trainer", None)
        r2 = client.post(
            "/step",
            data=data,
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
            follow_redirects=False,
        )
        assert r2.status_code in (302, 303), r2.text
        if r2.status_code in (302, 303):
            loc = r2.headers.get("location", "")
            if "/review" in loc or "/abort" in loc:
                break
    else:
        raise AssertionError("web driver did not reach review/abort")

    sid = client.cookies["setup_session"]
    config = app.state.setup.store.sessions[sid]["config"]
    assert (
        config.get("hypnos", {}).get("voice_alignment", {}).get("trainer_python")
        == "/fake/trainer/python3"
    )


def test_boolean_field_values_from_the_form():
    """Absent means the field's default; the hidden companion alone means an
    unchecked box (false); companion plus checkbox means ticked (true)."""
    from kaine.setup.steps import Field
    from kaine.setup.web.driver import form_value

    on_by_default = Field("enabled", "enable?", "bool", default=True)
    off_by_default = Field("opt_in", "opt in?", "bool", default=False)
    assert form_value({}, on_by_default) == "true"
    assert form_value({}, off_by_default) == "false"
    assert form_value({"enabled": ["false"]}, on_by_default) == "false"
    assert form_value({"opt_in": ["false", "true"]}, off_by_default) == "true"


def test_absent_choice_field_uses_its_default():
    from kaine.setup.steps import Field
    from kaine.setup.web.driver import form_value

    field = Field("record_trainer", "record?", "choice", default="yes", choices=("yes", "no"))
    assert form_value({}, field) == "yes"
    assert form_value({"record_trainer": ["no"]}, field) == "no"


def test_cache_control_no_store_on_step_page(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r2 = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r2.status_code == 200
    assert r2.headers.get("cache-control") == "no-store"


def test_save_forbidden_before_acknowledgement(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r2 = client.post(
        "/save",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 403
    assert not app.state.setup.operator_path.exists()


def test_review_forbidden_before_completion(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r2 = client.get(
        "/review",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r2.status_code == 403


def test_review_forbidden_after_ack_but_before_finish(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    # Orientation step has no fields.
    client.post(
        "/step",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    # Acknowledge welfare.
    client.post(
        "/step",
        data={"ack": ACK_PHRASE},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    r3 = client.get(
        "/review",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r3.status_code == 403


def test_save_refused_when_cycle_running(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)
    monkeypatch.setattr(
        guard, "cycle_running_with_reason", lambda _root: (True, "a KAINE cycle is connected to the bus")
    )

    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)
    sid = client.cookies["setup_session"]
    app.state.setup.store.sessions[sid]["config"] = {
        "lingua": {"model_id": "model-a"}
    }
    app.state.setup.store.sessions[sid]["step_index"] = len(app.state.setup.steps)
    app.state.setup.store.sessions[sid]["acknowledged"] = True

    r2 = client.post(
        "/save",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 409
    assert "cycle" in r2.text.lower()


def test_cycle_running_logic(tmp_path):
    state_root = tmp_path / "state"
    runtime_dir = state_root / "cycle"
    runtime_dir.mkdir(parents=True)

    runtime = runtime_dir / "runtime.json"

    # No file -> False.
    assert guard.cycle_running(state_root) is False

    # File with a dead PID.
    runtime.write_text('{"pid": 9999999}')
    assert guard.cycle_running(state_root) is False

    # File with this process's PID but a cmdline that does not mention kaine.cycle.
    runtime.write_text(f'{{"pid": {os.getpid()}}}')
    assert guard.cycle_running(state_root) is False


def test_cycle_running_unparseable_counts_running(tmp_path):
    state_root = tmp_path / "state"
    runtime = state_root / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("not json")
    assert guard.cycle_running(state_root) is True


def test_cycle_running_non_int_pid_counts_running(tmp_path):
    state_root = tmp_path / "state"
    runtime = state_root / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text('{"pid": "123"}')
    assert guard.cycle_running(state_root) is True


def test_cycle_running_permission_error_on_kill_counts_running(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    runtime = state_root / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text('{"pid": 1}')

    def kill(pid, sig):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "kill", kill)
    assert guard.cycle_running(state_root) is True


def test_cycle_running_unreadable_cmdline_counts_running(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    runtime = state_root / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(f'{{"pid": {os.getpid()}}}')

    def fake_read_text(*args, **kwargs):
        raise OSError("cannot read")

    monkeypatch.setattr("kaine.setup.web.guard.Path.read_text", fake_read_text)
    assert guard.cycle_running(state_root) is True


def test_static_style_is_nexus_stylesheet(tmp_path):
    import kaine.nexus

    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r2 = client.get(
        "/static/style.css",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r2.status_code == 200
    nexus_css = Path(kaine.nexus.__file__).parent / "static" / "style.css"
    assert r2.content == nexus_css.read_bytes()


def test_setup_css_uses_only_design_tokens(tmp_path):
    css_path = (
        Path(__file__).parent.parent
        / "kaine"
        / "setup"
        / "web"
        / "static"
        / "setup.css"
    )
    text = css_path.read_text()
    assert not re.search(r"#[0-9a-fA-F]{3,8}", text)
    assert "rgb(" not in text.lower()
    assert "hsl(" not in text.lower()
    # Only var(--…) font-family references are allowed.
    for line in text.splitlines():
        if "font-family" in line:
            assert "var(--" in line, line


def _defaults_from_form(html: str, step_id: str) -> dict[str, list[str] | str]:
    """Extract default form submission from a rendered step page.

    Values are collected in document order so that multi-valued fields (for
    example a bool hidden ``false`` companion followed by a checked
    ``true`` checkbox) keep every submitted value; the driver's ``form_value``
    uses the last one.
    """
    ordered: list[tuple[str, str]] = []

    # Hidden inputs first (they appear before visible fields in the template).
    for m in re.finditer(
        r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"[^>]*>',
        html,
    ):
        ordered.append((m.group(1), m.group(2)))

    # Bool checkboxes and multi-choice checkboxes.
    for m in re.finditer(
        r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"[^>]*value="([^"]+)"([^>]*)>',
        html,
    ):
        attrs = m.group(3)
        if "checked" in attrs:
            ordered.append((m.group(1), m.group(2)))

    # Radio buttons.
    for m in re.finditer(
        r'<input[^>]*type="radio"[^>]*name="([^"]+)"[^>]*value="([^"]+)"([^>]*)>',
        html,
    ):
        attrs = m.group(3)
        if "checked" in attrs:
            ordered.append((m.group(1), m.group(2)))

    # Text / number inputs.
    for m in re.finditer(
        r'<input[^>]*type="(?:text|number)"[^>]*name="([^"]+)"[^>]*value="([^"]*)"[^>]*>',
        html,
    ):
        ordered.append((m.group(1), m.group(2)))

    data: dict[str, list[str] | str] = {}
    for name, val in ordered:
        existing = data.get(name)
        if existing is None:
            data[name] = val
        elif isinstance(existing, list):
            existing.append(val)
        else:
            data[name] = [existing, val]

    return data


def _drive_web(app, overrides: dict[str, Any]) -> dict:
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    token = app.state.setup.store.issue()
    r = client.get(
        f"/?token={token}",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    for _ in range(200):
        r = client.get(
            "/step",
            headers={"Host": "127.0.0.1:8000"},
            follow_redirects=False,
        )
        if r.status_code in (302, 303):
            loc = r.headers.get("location", "")
            if "/review" in loc or "/abort" in loc:
                break
            continue
        assert r.status_code == 200

        m = re.search(r'data-step-id="([^"]+)"', r.text)
        assert m, "step id not found in rendered page"
        step_id = m.group(1)

        data: dict[str, Any] = _defaults_from_form(r.text, step_id)
        data["_step_id"] = step_id
        if step_id == "welfare-acknowledgement":
            data["ack"] = overrides.get("ack", ACK_PHRASE)
        if step_id == "module-preset":
            data["preset"] = overrides.get("preset", "b")
        if step_id == "research-opt-in":
            data["opt_in"] = "true" if overrides.get("metrics", False) else "false"

        r2 = client.post(
            "/step",
            data=data,
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
            follow_redirects=False,
        )
        assert r2.status_code in (302, 303), r2.text
    else:
        raise AssertionError("web driver did not reach review/abort")

    sid = client.cookies["setup_session"]
    return app.state.setup.store.sessions[sid]["config"]


def _run_terminal(host, shipped_path, tmp_path, **overrides) -> dict:
    shipped = _load_toml(shipped_path)

    def input_fn(prompt: str) -> str:
        p = prompt.lower()
        if "ack" in p or "welfare" in p:
            return ACK_PHRASE
        if "modules" in p and "[b]" in p:
            return overrides.get("preset", "b")
        if "opt in" in p:
            return "yes" if overrides.get("metrics", False) else ""
        return ""

    out_lines = []
    result = run_wizard(
        input_fn=input_fn,
        out=out_lines.append,
        host=host,
        shipped_config=shipped,
        probe_services=None,
        recommend_tier_fn=lambda: None,
        device_consumers_fn=lambda: [],
        services_up_fn=lambda: {},
        defaults=False,
        storage_old_root=tmp_path,
        existing_config={},
    )
    assert result.acknowledged
    return result.config


def _load_toml(path: Path) -> dict:
    import tomllib

    with path.open("rb") as fh:
        return tomllib.load(fh)


@pytest.mark.parametrize(
    "overrides",
    [
        {"preset": "b", "metrics": False},
        {"preset": "c", "metrics": True},
    ],
)
def test_parity_web_and_terminal(tmp_path, overrides):
    host = describe_host()
    shipped_path = _shipped_config(tmp_path)
    web_app = _mk_app(
        tmp_path,
        host=host,
        shipped_config_path=shipped_path,
    )
    web_config = _drive_web(web_app, overrides)
    terminal_config = _run_terminal(host, shipped_path, tmp_path, **overrides)
    assert web_config == terminal_config


def test_web_and_terminal_step_order_match(tmp_path, monkeypatch):
    from kaine.setup import wizard as wizard_mod

    terminal_ids: list[str] = []
    original_run_step = wizard_mod.run_step

    def logging_run_step(step, ctx, **kwargs):
        # run_step is also called for steps that do not apply and returns at
        # once; record only the steps the operator is actually shown.
        if step.applies(ctx):
            terminal_ids.append(step.id)
        return original_run_step(step, ctx, **kwargs)

    monkeypatch.setattr(wizard_mod, "run_step", logging_run_step)

    host = describe_host()
    shipped_path = _shipped_config(tmp_path)
    _run_terminal(host, shipped_path, tmp_path, preset="b", metrics=False)

    web_ids: list[str] = []
    app = _mk_app(tmp_path, host=host, shipped_config_path=shipped_path)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    token = app.state.setup.store.issue()
    r = client.get(
        f"/?token={token}",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)

    for _ in range(200):
        r = client.get(
            "/step",
            headers={"Host": "127.0.0.1:8000"},
            follow_redirects=False,
        )
        if r.status_code in (302, 303):
            loc = r.headers.get("location", "")
            if "/review" in loc or "/abort" in loc:
                break
            continue
        assert r.status_code == 200

        m = re.search(r'data-step-id="([^"]+)"', r.text)
        assert m, "step id not found in rendered page"
        step_id = m.group(1)
        web_ids.append(step_id)

        data = _defaults_from_form(r.text, step_id)
        if step_id == "welfare-acknowledgement":
            data["ack"] = ACK_PHRASE
        if step_id == "module-preset":
            data["preset"] = "b"
        if step_id == "research-opt-in":
            data["opt_in"] = "false"

        r2 = client.post(
            "/step",
            data=data,
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
            follow_redirects=False,
        )
        assert r2.status_code in (302, 303), r2.text
    else:
        raise AssertionError("web driver did not reach review/abort")

    assert web_ids == terminal_ids


def test_bool_explicit_false_is_false_and_missing_is_false():
    from kaine.setup.steps import Field
    from kaine.setup.web.driver import form_value

    field = Field("opt_in", "opt in?", "bool", default=False)

    assert form_value({"opt_in": "false"}, field) == "false"
    assert form_value({"opt_in": "False"}, field) == "false"
    assert form_value({"opt_in": "0"}, field) == "false"
    assert form_value({"opt_in": "off"}, field) == "false"
    assert form_value({"opt_in": "no"}, field) == "false"
    assert form_value({}, field) == "false"

    assert form_value({"opt_in": "true"}, field) == "true"
    assert form_value({"opt_in": "yes"}, field) == "true"
    assert form_value({"opt_in": "on"}, field) == "true"
    assert form_value({"opt_in": "1"}, field) == "true"

    # The last submitted value wins.
    assert form_value({"opt_in": ["true", "false"]}, field) == "false"
    assert form_value({"opt_in": ["false", "true"]}, field) == "true"


def test_trainer_step_appears_and_records_when_ticked(tmp_path):
    def probe_trainer(configured, backend):
        return (True, "/fake/trainer/python3:3.12")

    host = describe_host()
    # Ensure the trainer-provisioning helper step applies regardless of the real host.
    host["accelerators"] = [{"type": "cuda", "model": "Fake GPU"}]
    host["cuda"] = True
    host["gpu"] = True
    host["backend"] = "cuda"

    def walk(app, client, overrides=None, seen_ids=None):
        overrides = overrides or {}
        if seen_ids is None:
            seen_ids = []
        for _ in range(200):
            r = client.get(
                "/step",
                headers={"Host": "127.0.0.1:8000"},
                follow_redirects=False,
            )
            if r.status_code in (302, 303):
                loc = r.headers.get("location", "")
                if "/review" in loc or "/abort" in loc:
                    break
                continue
            assert r.status_code == 200

            m = re.search(r'data-step-id="([^"]+)"', r.text)
            assert m, "step id not found in rendered page"
            step_id = m.group(1)
            seen_ids.append(step_id)

            data = _defaults_from_form(r.text, step_id)
            data["_step_id"] = step_id
            if step_id == "welfare-acknowledgement":
                data["ack"] = ACK_PHRASE
            if step_id == "module-preset":
                data["preset"] = "b"
            data.update(overrides.get(step_id, {}))

            r2 = client.post(
                "/step",
                data=data,
                headers={
                    "Host": "127.0.0.1:8000",
                    "Origin": "http://127.0.0.1:8000",
                },
                follow_redirects=False,
            )
            assert r2.status_code in (302, 303), r2.text
        else:
            raise AssertionError("web driver did not reach review/abort")

        sid = client.cookies["setup_session"]
        return app.state.setup.store.sessions[sid]["config"]

    # Unticked: the step is shown but trainer_python is not recorded.
    app = _mk_app(tmp_path, host=host, probe_trainer=probe_trainer)
    client = _session_client(app)
    _exchange_token(client, app)
    seen: list[str] = []
    config_no = walk(app, client, seen_ids=seen)
    assert "trainer-provisioning" in seen
    assert config_no.get("hypnos", {}).get("voice_alignment", {}).get("trainer_python") is None

    # Ticked: the step records the probed interpreter.
    app2 = _mk_app(tmp_path, host=host, probe_trainer=probe_trainer)
    client2 = _session_client(app2)
    _exchange_token(client2, app2)
    config_yes = walk(
        app2,
        client2,
        overrides={
            "trainer-provisioning": {
                "set_up_trainer": "yes",
                "record_trainer": "yes",
            }
        },
    )
    assert (
        config_yes.get("hypnos", {}).get("voice_alignment", {}).get("trainer_python")
        == "/fake/trainer/python3"
    )
    assert (
        config_yes.get("hypnos", {}).get("voice_alignment", {}).get("trainer_backend")
        == "subprocess"
    )


def test_wrong_acknowledgement_aborts_and_writes_no_file(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    # Orientation step (no fields).
    r_orient = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r_orient.status_code == 200
    m = re.search(r'data-step-id="([^"]+)"', r_orient.text)
    assert m
    orientation_id = m.group(1)
    client.post(
        "/step",
        data={"_step_id": orientation_id},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    # Welfare-acknowledgement step.
    r_ack = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r_ack.status_code == 200
    m = re.search(r'data-step-id="([^"]+)"', r_ack.text)
    assert m
    ack_step_id = m.group(1)
    r2 = client.post(
        "/step",
        data={"_step_id": ack_step_id, "ack": "wrong phrase"},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 200
    assert "no configuration was written" in r2.text.lower()

    assert not app.state.setup.operator_path.exists()


def test_abort_post_same_origin_finishes_setup(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    _exchange_token(client, app)

    r = client.post(
        "/abort",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "aborting" in r.text.lower()
    assert app.state.finish_shutdown is True


def test_abort_post_cross_origin_rejected(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    _exchange_token(client, app)

    r = client.post(
        "/abort",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8001",
        },
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert not app.state.finish_shutdown


def test_abort_get_returns_405(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    _exchange_token(client, app)

    r = client.get(
        "/abort",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code == 405


def test_cycle_running_falls_back_to_bus_when_runtime_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "load_bus_config", lambda: object())
    monkeypatch.setattr(guard, "cycle_on_bus", lambda cfg: (True, "cycle connected"))
    assert guard.cycle_running(tmp_path) is True

    monkeypatch.setattr(guard, "cycle_on_bus", lambda cfg: (None, "unknown"))
    assert guard.cycle_running(tmp_path) is True

    monkeypatch.setattr(guard, "cycle_on_bus", lambda cfg: (False, "not on bus"))
    assert guard.cycle_running(tmp_path) is False


def test_cycle_running_bus_config_error_refuses_when_the_bus_is_up(tmp_path, monkeypatch):
    from kaine.bus.errors import BusConfigError

    monkeypatch.setattr(
        guard,
        "load_bus_config",
        lambda *a, **k: (_ for _ in ()).throw(BusConfigError("no bus config")),
    )
    monkeypatch.setattr(
        guard,
        "load_bus_endpoint",
        lambda *a, **k: ("127.0.0.1", 6479),
    )
    monkeypatch.setattr(guard, "_probe_endpoint", lambda h, p: True)
    running, reason = guard.cycle_running_with_reason(tmp_path)
    assert running is True
    assert "credentials" in reason


def test_save_refused_when_cycle_on_bus(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)
    monkeypatch.setattr(guard, "load_bus_config", lambda: object())
    reason = "containerized cycle connected to bus"
    monkeypatch.setattr(guard, "cycle_on_bus", lambda cfg: (True, reason))
    _drive_web(app, {})

    sid = list(app.state.setup.store.sessions.keys())[0]
    client = _session_client(app)
    client.cookies["setup_session"] = sid

    r = client.post(
        "/save",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r.status_code == 409
    assert reason in r.text


def test_malformed_operator_file_raises_on_app_creation(tmp_path):
    operator_path = tmp_path / "kaine.operator.toml"
    operator_path.write_text("[[invalid toml")
    with pytest.raises(ValueError, match=str(operator_path)):
        _mk_app(tmp_path, operator_path=operator_path)


def test_probes_run_only_after_acknowledgement(tmp_path):
    calls: list[str] = []
    app = _mk_app(
        tmp_path,
        probe_services=lambda: calls.append("probe_services") or {},
        recommend_tier_fn=lambda: calls.append("recommend_tier") or None,
        device_consumers_fn=lambda: calls.append("device_consumers") or [],
        services_up_fn=lambda: calls.append("services_up") or {},
    )
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)
    assert calls == []

    # Orientation step.
    r2 = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r2.status_code == 200
    assert calls == []

    client.post(
        "/step",
        data={"_step_id": "orientation"},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    r3 = client.get(
        "/step",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert "welfare-acknowledgement" in r3.text

    client.post(
        "/step",
        data={"ack": ACK_PHRASE, "_step_id": "welfare-acknowledgement"},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    assert calls == [
        "probe_services",
        "recommend_tier",
        "device_consumers",
        "services_up",
    ]

    sid = client.cookies["setup_session"]
    extra = app.state.setup.store.sessions[sid]["extra"]
    assert "catalogue" in extra
    assert "floor_gb" in extra
    assert "min_free_gb" in extra
    assert "old_root" in extra
    assert "tier_rec" in extra


def test_serve_refuses_non_loopback_host(tmp_path):
    app = _mk_app(tmp_path)
    with pytest.raises(ValueError, match="loopback"):
        serve("0.0.0.0", 0, app=app, idle_seconds=1)


def test_serve_binds_loopback_and_shuts_down(tmp_path):
    app = _mk_app(tmp_path, idle_seconds=0.2)

    result = {"port": None, "alive": True}

    def run():
        serve("127.0.0.1", 0, app=app, idle_seconds=0.2)
        result["alive"] = False

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "server did not idle-shutdown"
    assert result["alive"] is False


def test_idle_shutdown_honours_activity_hold(tmp_path):
    class Clock:
        def __init__(self):
            self.t = 0.0

        def now(self):
            return self.t

    clock = Clock()
    app = _mk_app(tmp_path, now=clock.now, idle_seconds=1.0)

    class FakeServer:
        def __init__(self):
            self.should_exit = False

    server = FakeServer()
    app.state.server = server

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        token = app.state.setup.store.issue()
        client.get(
            f"/?token={token}",
            headers={"Host": "127.0.0.1:8000"},
            follow_redirects=False,
        )

        app.state.activity_hold = 1
        clock.t += 2.0
        time.sleep(0.2)
        assert server.should_exit is False

        app.state.activity_hold = 0
        clock.t += 2.0
        # The watcher checks every second; give it time.
        time.sleep(1.5)
        assert server.should_exit is True


def test_post_naming_a_step_that_does_not_apply_is_refused(tmp_path):
    """A POST names its step. One naming a step the terminal would skip, such
    as the deployment-tier step when no tier recommendation exists, is refused
    and answers nothing, and that step never appears in the flow."""
    app = _mk_app(tmp_path, recommend_tier_fn=lambda: None)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)
    headers = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}

    client.post("/step", data={"_step_id": "orientation"}, headers=headers, follow_redirects=False)
    r = client.post(
        "/step",
        data={"ack": ACK_PHRASE, "_step_id": "welfare-acknowledgement"},
        headers=headers,
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    sid = client.cookies["setup_session"]
    before = dict(app.state.setup.store.sessions[sid])

    refused = client.post(
        "/step", data={"_step_id": "deployment-tier"}, headers=headers, follow_redirects=False
    )
    assert refused.status_code == 409
    assert app.state.setup.store.sessions[sid]["step_index"] == before["step_index"]

    seen: list[str] = []
    for _ in range(100):
        page = client.get("/step", headers={"Host": "127.0.0.1:8000"}, follow_redirects=False)
        if page.status_code in (302, 303):
            if "/review" in page.headers.get("location", ""):
                break
            continue
        step_id = re.search(r'data-step-id="([^"]+)"', page.text).group(1)
        seen.append(step_id)
        data = _defaults_from_form(page.text, step_id)
        data["_step_id"] = step_id
        if step_id == "module-preset":
            data["preset"] = "b"
        posted = client.post("/step", data=data, headers=headers, follow_redirects=False)
        assert posted.status_code in (302, 303), posted.text
    else:
        raise AssertionError("never reached review")
    assert "deployment-tier" not in seen
    assert app.state.setup.store.sessions[sid]["step_index"] == len(app.state.setup.steps)


def test_launch_redirect_file_is_private_and_redirects(tmp_path, monkeypatch):
    """The browser is opened on an owner-only redirect file, so the launch
    token never appears on a process command line."""
    import stat
    import tempfile

    from kaine.setup.__main__ import _launch_redirect_file

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    url = "http://127.0.0.1:43123/?token=abc&x=1"
    target = _launch_redirect_file(url)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    text = target.read_text()
    assert 'content="0;url=http://127.0.0.1:43123/?token=abc&amp;x=1"' in text
    assert target.as_uri().startswith("file://")
    assert "abc" not in target.as_uri()


def test_run_web_refuses_when_state_dir_cannot_be_resolved(tmp_path, monkeypatch, capsys):
    """The running-cycle guard must check the real state directory; when it
    cannot be resolved, setup refuses to start instead of guarding cwd/state."""
    import argparse

    import kaine.storage
    from kaine.setup import __main__ as setup_main_mod

    def broken_resolve(_path):
        raise RuntimeError("data root unavailable")

    started = []
    monkeypatch.setattr(kaine.storage, "resolve", broken_resolve)
    # _run_web imports the server lazily from kaine.setup.web.
    monkeypatch.setattr("kaine.setup.web.serve", lambda *a, **k: started.append(1))
    args = argparse.Namespace(
        operator_path=tmp_path / "op.toml",
        config_path=Path(__file__).resolve().parent.parent / "config" / "kaine.toml",
    )
    rc = setup_main_mod._run_web(args, describe_host(), tmp_path)
    assert rc == 1
    assert not started
    assert "state directory cannot be resolved" in capsys.readouterr().err



def test_cycle_running_bus_config_error_means_not_running_when_bus_refused(
    tmp_path, monkeypatch
):
    from kaine.bus.errors import BusConfigError

    monkeypatch.setattr(
        guard,
        "load_bus_config",
        lambda *a, **k: (_ for _ in ()).throw(BusConfigError("no bus config")),
    )
    monkeypatch.setattr(
        guard,
        "load_bus_endpoint",
        lambda *a, **k: ("127.0.0.1", 6479),
    )
    monkeypatch.setattr(guard, "_probe_endpoint", lambda h, p: False)
    assert guard.cycle_running(tmp_path) is False


def test_cycle_running_bus_config_error_means_running_when_probe_unknown(
    tmp_path, monkeypatch
):
    from kaine.bus.errors import BusConfigError

    monkeypatch.setattr(
        guard,
        "load_bus_config",
        lambda *a, **k: (_ for _ in ()).throw(BusConfigError("no bus config")),
    )
    monkeypatch.setattr(
        guard,
        "load_bus_endpoint",
        lambda *a, **k: ("127.0.0.1", 6479),
    )
    monkeypatch.setattr(guard, "_probe_endpoint", lambda h, p: None)
    running, reason = guard.cycle_running_with_reason(tmp_path)
    assert running is True
    assert "probed" in reason


def test_cycle_running_bus_config_error_means_running_when_endpoint_unreadable(
    tmp_path, monkeypatch
):
    from kaine.bus.errors import BusConfigError

    monkeypatch.setattr(
        guard,
        "load_bus_config",
        lambda *a, **k: (_ for _ in ()).throw(BusConfigError("no bus config")),
    )
    monkeypatch.setattr(
        guard,
        "load_bus_endpoint",
        lambda *a, **k: (_ for _ in ()).throw(BusConfigError("bad endpoint")),
    )
    running, reason = guard.cycle_running_with_reason(tmp_path)
    assert running is True
    assert "cannot be read here" in reason


def test_cycle_running_process_scan_detects_live_cycle_before_bus(
    tmp_path, monkeypatch
):
    called = []

    def crashing_on_bus(_cfg):
        called.append("cycle_on_bus")
        raise RuntimeError("should not be consulted")

    monkeypatch.setattr(guard, "cycle_process_details", lambda: (True, 4242, ["python", "-m", "kaine.cycle"]))
    monkeypatch.setattr(guard, "cycle_on_bus", crashing_on_bus)
    running, reason = guard.cycle_running_with_reason(tmp_path)
    assert running is True
    assert "kaine.cycle process is running" in reason
    assert called == []


def test_save_refused_when_bus_config_missing_and_bus_is_up(
    tmp_path, monkeypatch
):
    from kaine.bus.errors import BusConfigError

    app = _mk_app(tmp_path)
    _drive_web(app, {})

    monkeypatch.setattr(
        guard,
        "load_bus_config",
        lambda *a, **k: (_ for _ in ()).throw(BusConfigError("no bus config")),
    )
    monkeypatch.setattr(
        guard,
        "load_bus_endpoint",
        lambda *a, **k: ("127.0.0.1", 6479),
    )
    monkeypatch.setattr(guard, "_probe_endpoint", lambda h, p: True)

    sid = list(app.state.setup.store.sessions.keys())[0]
    client = _session_client(app)
    client.cookies["setup_session"] = sid

    r = client.post(
        "/save",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r.status_code == 409
    assert "credentials" in r.text
    assert not app.state.setup.operator_path.exists()


def test_probe_endpoint_reports_listening_and_refused():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    _host, port = sock.getsockname()[:2]
    assert guard._probe_endpoint("127.0.0.1", port) is True
    sock.close()

    sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock2.bind(("127.0.0.1", 0))
    free_port = sock2.getsockname()[1]
    sock2.close()
    assert guard._probe_endpoint("127.0.0.1", free_port) is False


def test_load_bus_endpoint_reads_host_without_password(tmp_path):
    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text('[redis]\nhost = "h"\nport = 1234\n')
    endpoint = guard.load_bus_endpoint(
        kaine_toml=kaine_toml,
        secrets_toml=tmp_path / "missing-secrets.toml",
        env={},
        operator_toml=tmp_path / "missing-op.toml",
    )
    assert endpoint == ("h", 1234)


def test_load_bus_endpoint_reads_url_override_without_exposing_password(
    tmp_path,
):
    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text("[redis]\n")
    env = {"KAINE_REDIS_URL": "redis://u:p@x:4321/0"}
    endpoint = guard.load_bus_endpoint(
        kaine_toml=kaine_toml,
        secrets_toml=tmp_path / "missing-secrets.toml",
        env=env,
        operator_toml=tmp_path / "missing-op.toml",
    )
    assert endpoint == ("x", 4321)


def test_validate_fields_rejects_empty_multichoice(tmp_path):
    from kaine.setup.hardware_steps import consent_step
    from kaine.setup.steps import StepContext
    from kaine.setup.web.driver import validate_fields

    ctx = StepContext(host={"cpu_count": 4}, config={}, extra={"consumers": []})
    fields = consent_step.fields(ctx)
    _answers, errors = validate_fields(
        fields, {"_step_id": "hardware-consent", "allowed_devices": ""}
    )
    assert errors.get("allowed_devices") == "at least one choice is required"


def _consent_step_index(app) -> int:
    for idx, step in enumerate(app.state.setup.steps):
        if step.id == "hardware-consent":
            return idx
    raise AssertionError("hardware-consent step not found")


def test_multichoice_empty_submission_requires_one_choice(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)
    sid = client.cookies["setup_session"]
    app.state.setup.store.sessions[sid]["step_index"] = _consent_step_index(app)

    r2 = client.get(
        "/step", headers={"Host": "127.0.0.1:8000"}, follow_redirects=False
    )
    assert r2.status_code == 200
    assert '<input type="hidden" name="allowed_devices" value="">' in r2.text

    r3 = client.post(
        "/step",
        data={
            "_step_id": "hardware-consent",
            "allowed_devices": "",
            "cpu_threads": "1",
        },
        headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r3.status_code == 400  # a validation error re-renders the step
    assert "at least one choice is required" in r3.text
    sess = app.state.setup.store.sessions[sid]
    assert "hardware" not in sess["config"]


def test_non_ascii_token_is_rejected_with_403(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r = client.get(
        "/?token=é",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_non_utf8_form_body_returns_400_with_session(tmp_path):
    app = _mk_app(tmp_path)
    client = _session_client(app)
    r, _token = _exchange_token(client, app)
    assert r.status_code in (302, 303)

    r2 = client.post(
        "/step",
        content=b"\xff\xfe",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 400
    assert "valid UTF-8" in r2.text


def test_process_positive_wins_over_refused_bus(monkeypatch, tmp_path):
    bus_calls = []

    def raising_load_bus_config(*args, **kwargs):
        bus_calls.append((args, kwargs))
        raise BusConfigError("stub: no bus config")

    monkeypatch.setattr(guard, "cycle_process_details", lambda: (True, 4242, ["python", "-m", "kaine.cycle"]))
    monkeypatch.setattr(guard, "load_bus_config", raising_load_bus_config)
    monkeypatch.setattr(
        guard, "load_bus_endpoint", lambda *a, **k: ("127.0.0.1", 6379)
    )
    monkeypatch.setattr(guard, "_probe_endpoint", lambda *a, **k: False)

    running, reason = guard.cycle_running_with_reason(tmp_path / "state")
    assert running is True
    assert "kaine.cycle process is running" in reason
    assert bus_calls == []


def test_unknown_process_state_refuses(monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "cycle_process_details", lambda: (None, None, None))

    running, reason = guard.cycle_running_with_reason(tmp_path / "state")
    assert running is True
    assert reason is not None
    assert "process list" in reason


def test_bus_endpoint_matches_cycle_bus_config(tmp_path):
    from urllib.parse import urlsplit

    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text("[redis]\nhost = 'h1'\nport = 1111\n")
    operator_toml = tmp_path / "kaine.operator.toml"
    operator_toml.write_text("[redis]\nport = 2222\n")
    secrets_toml = tmp_path / "secrets.toml"
    secrets_toml.write_text("[redis]\npassword = 'pw'\n")

    endpoint = load_bus_endpoint(
        kaine_toml=kaine_toml,
        secrets_toml=secrets_toml,
        env={},
        operator_toml=operator_toml,
    )
    cfg = load_bus_config(
        kaine_toml=kaine_toml,
        secrets_toml=secrets_toml,
        env={},
        operator_toml=operator_toml,
    )
    assert endpoint == (cfg.host, cfg.port) == ("h1", 2222)

    env = {"KAINE_REDIS_URL": "redis://u:pw@x:4321/0"}
    endpoint2 = load_bus_endpoint(
        kaine_toml=kaine_toml,
        secrets_toml=secrets_toml,
        env=env,
        operator_toml=operator_toml,
    )
    cfg2 = load_bus_config(
        kaine_toml=kaine_toml,
        secrets_toml=secrets_toml,
        env=env,
        operator_toml=operator_toml,
    )
    assert endpoint2 == ("x", 4321)
    parsed = urlsplit(cfg2.url_override)
    assert (parsed.hostname, parsed.port) == ("x", 4321)


def test_non_ascii_token_exchange_never_raises(tmp_path):
    app = _mk_app(tmp_path)
    # A real token must be outstanding, or compare_digest is never reached.
    app.state.setup.store.issue()
    assert app.state.setup.store.exchange("é" * 43) is None


def test_process_reason_names_the_cycle_process(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "_runtime_file_reason", lambda p: (False, None))
    monkeypatch.setattr(guard, "_bus_reason", lambda p: (False, None))
    monkeypatch.setattr(
        guard,
        "cycle_process_details",
        lambda *a, **k: (True, 123, ["python", "-m", "kaine.cycle"]),
    )
    running, reason = guard.cycle_running_with_reason(tmp_path)
    assert running is True
    assert "pid 123" in reason
    assert "kaine.cycle" in reason


def test_credentials_reason_names_endpoint_and_env_var(tmp_path, monkeypatch):
    def raise_no_config(*a, **k):
        raise BusConfigError("no credentials")

    monkeypatch.setattr(guard, "load_bus_config", raise_no_config)
    monkeypatch.setattr(
        guard, "load_bus_endpoint", lambda *a, **k: ("127.0.0.1", 6479)
    )
    monkeypatch.setattr(guard, "_probe_endpoint", lambda *a, **k: True)
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", "hunter2-secret")
    running, reason = guard._bus_reason(tmp_path / "runtime.json")
    assert running is True
    assert "127.0.0.1:6479" in reason
    assert "KAINE_REDIS_PASSWORD" in reason
    assert "hunter2-secret" not in reason


def test_probe_failure_reason_names_endpoint(tmp_path, monkeypatch):
    def raise_no_config(*a, **k):
        raise BusConfigError("no credentials")

    def raise_probe(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(guard, "load_bus_config", raise_no_config)
    monkeypatch.setattr(
        guard, "load_bus_endpoint", lambda *a, **k: ("some.host", 9999)
    )
    monkeypatch.setattr(guard, "_probe_endpoint", raise_probe)
    running, reason = guard._bus_reason(tmp_path / "runtime.json")
    assert running is True
    assert "some.host:9999" in reason
    assert "RuntimeError" in reason


def test_cycle_process_details_finds_pid_and_argv(tmp_path):
    from kaine.lifecycle.liveness import cycle_process_details

    proc = tmp_path / "proc"
    proc.mkdir()
    d = proc / "7"
    d.mkdir()
    (d / "cmdline").write_bytes(b"python\0-m\0kaine.cycle\0")
    state, pid, argv = cycle_process_details(proc_root=str(proc))
    assert state is True
    assert pid == 7
    assert argv == ["python", "-m", "kaine.cycle"]
