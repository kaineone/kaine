# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the browser first-run setup server (slice 2)."""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

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

    r = client.get(
        "/static/style.css",
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert app.state.last_activity == 0.0


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

    # Valid Origin.
    r4 = client.post(
        "/step",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r4.status_code in (302, 303)


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
    monkeypatch.setattr(guard, "cycle_running", lambda _root: True)

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
    """Extract default form submission from a rendered step page."""
    data: dict[str, list[str] | str] = {}

    # Bool: include only checked checkboxes.
    for m in re.finditer(
        r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"[^>]*value="true"([^>]*)>',
        html,
    ):
        name = m.group(1)
        attrs = m.group(2)
        if "checked" in attrs:
            data[name] = "true"

    # Radio / single-choice: include checked value.
    for m in re.finditer(
        r'<input[^>]*type="radio"[^>]*name="([^"]+)"[^>]*value="([^"]+)"([^>]*)>',
        html,
    ):
        attrs = m.group(3)
        if "checked" in attrs:
            data[m.group(1)] = m.group(2)

    # Multi-choice checkboxes: include checked values.
    for m in re.finditer(
        r'<input[^>]*type="checkbox"[^>]*name="([^"]+)"[^>]*value="([^"]+)"([^>]*)>',
        html,
    ):
        attrs = m.group(3)
        if "checked" in attrs:
            name = m.group(1)
            val = m.group(2)
            if name == "true":
                # skip bool handled above
                continue
            existing = data.get(name)
            if existing is None:
                data[name] = [val]
            elif isinstance(existing, list):
                existing.append(val)
            else:
                data[name] = [existing, val]

    # Text / number inputs: include the rendered value.
    for m in re.finditer(
        r'<input[^>]*type="(?:text|number)"[^>]*name="([^"]+)"[^>]*value="([^"]*)"[^>]*>',
        html,
    ):
        data[m.group(1)] = m.group(2)

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
        return (True, "/usr/bin/python3:3.12")

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
    app = _mk_app(tmp_path, probe_trainer=probe_trainer)
    client = _session_client(app)
    _exchange_token(client, app)
    seen: list[str] = []
    config_no = walk(app, client, seen_ids=seen)
    assert "trainer-provisioning" in seen
    assert config_no.get("hypnos", {}).get("voice_alignment", {}).get("trainer_python") is None

    # Ticked: the step records the probed interpreter.
    app2 = _mk_app(tmp_path, probe_trainer=probe_trainer)
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
        == "/usr/bin/python3"
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

    # First real step is orientation (no fields), second is the ack step.
    client.post(
        "/step",
        data={},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    r2 = client.post(
        "/step",
        data={"ack": "wrong phrase"},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303)
    assert "/abort" in r2.headers.get("location", "")

    r3 = client.get(
        r2.headers["location"],
        headers={"Host": "127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert r3.status_code == 200
    assert "no configuration was written" in r3.text.lower()

    assert not app.state.setup.operator_path.exists()


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
        data={},
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
        data={"ack": ACK_PHRASE},
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
