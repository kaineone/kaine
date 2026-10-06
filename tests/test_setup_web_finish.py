# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the browser setup server finish page (slice 4)."""

from __future__ import annotations

import contextlib
import html.parser
import inspect
import re
from types import SimpleNamespace

from starlette.testclient import TestClient

from kaine import secrets_file
from kaine.net import SERVICE_PORTS
from kaine.setup.wizard import ACK_PHRASE
from tests.test_setup_web import _defaults_from_form, _mk_app


@contextlib.contextmanager
def _saved_client(app):
    """Yield a TestClient whose session has reached the saved /jobs page.

    The full wizard step loop is driven with safe defaults, then /save is POSTed
    with the required Host/Origin headers.
    """
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
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

        r_save = client.post(
            "/save",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
            follow_redirects=False,
        )
        assert r_save.status_code == 303
        assert r_save.headers.get("location", "").endswith("/jobs")
        yield client


def test_finish_forbidden_before_save(tmp_path):
    app = _mk_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        token = app.state.setup.store.issue()
        r = client.get(
            f"/?token={token}",
            headers={"Host": "127.0.0.1:8000"},
            follow_redirects=False,
        )
        assert r.status_code in (302, 303)

        r2 = client.get("/finish", headers={"Host": "127.0.0.1:8000"})
        assert r2.status_code == 403


def test_finish_status_lights(tmp_path):
    app = _mk_app(
        tmp_path,
        services_up_fn=lambda: {"model_server": True, "chatterbox": False, "speaches": False},
    )
    with _saved_client(app) as client:
        r = client.get("/finish", headers={"Host": "127.0.0.1:8000"})
        assert r.status_code == 200
        text = r.text

        assert "model_server on port" in text and "running" in text
        assert "chatterbox" in text and "not running" in text
        assert "speaches" in text and "not running" in text
        for name, port in SERVICE_PORTS.items():
            assert f"{name} on port {port}" in text


def test_finish_start_nexus_button(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)
    nexus_port = 11111
    monkeypatch.setattr(
        "kaine.setup.web.app.load_nexus_config",
        lambda path, **kwargs: SimpleNamespace(port=nexus_port, operator_token="x" * 40),
    )

    with _saved_client(app) as client:
        monkeypatch.setattr(
            "kaine.setup.web.app.port_listening",
            lambda port, timeout_s=1.0: False,
        )
        r = client.get("/finish", headers={"Host": "127.0.0.1:8000"})
        assert r.status_code == 200
        assert "Start Nexus" in r.text

        monkeypatch.setattr(
            "kaine.setup.web.app.port_listening",
            lambda port, timeout_s=1.0: port == nexus_port,
        )
        r2 = client.get("/finish", headers={"Host": "127.0.0.1:8000"})
        assert r2.status_code == 200
        assert "Start Nexus" not in r2.text


def test_finish_token_reveal(tmp_path, monkeypatch):
    token = "operator-token-value-with-enough-characters-1234"
    app = _mk_app(tmp_path)
    monkeypatch.setattr(
        "kaine.setup.web.app.load_nexus_config",
        lambda path, **kwargs: SimpleNamespace(port=11111, operator_token=token),
    )

    with _saved_client(app) as client:
        r = client.post(
            "/finish/token",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "no-store"
        assert "location" not in r.headers
        assert token in r.text
        assert r.text.count(token) == 1
        for value in r.headers.values():
            assert token not in str(value)

        r_cross = client.post(
            "/finish/token",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://example.com",
            },
        )
        assert r_cross.status_code == 403

    with TestClient(app, base_url="http://127.0.0.1:8000") as client2:
        r_no_session = client2.post(
            "/finish/token",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
        )
        assert r_no_session.status_code == 403


def test_finish_token_missing(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)
    secrets_path = app.state.setup.secrets_path
    monkeypatch.setattr(
        "kaine.setup.web.app.load_nexus_config",
        lambda path, **kwargs: SimpleNamespace(port=11111, operator_token=""),
    )

    with _saved_client(app) as client:
        r = client.post(
            "/finish/token",
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
        )
        assert r.status_code == 200
        assert "No sign-in token is set" in r.text
        assert str(secrets_path) in r.text


def test_save_creates_token_and_note_omits_it(tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    app = _mk_app(tmp_path, secrets_path=secrets_path)

    with _saved_client(app) as client:
        assert secrets_path.exists()
        token = secrets_file.read_toml_field(secrets_path, "nexus", "operator_token")
        assert isinstance(token, str)
        assert len(token) >= 32

        sid = client.cookies.get("setup_session")
        assert sid
        token_note = app.state.setup.store.sessions[sid].get("token_note", [])
        note_text = "".join(token_note)
        assert token not in note_text
        assert str(secrets_path) in note_text or "Nexus sign-in token" in note_text

        r = client.get("/finish", headers={"Host": "127.0.0.1:8000"})
        assert r.status_code == 200
        assert token not in r.text


def test_jobs_page_links_to_finish(tmp_path):
    app = _mk_app(tmp_path)
    with _saved_client(app) as client:
        r = client.get("/jobs", headers={"Host": "127.0.0.1:8000"})
        assert r.status_code == 200
        assert "/finish" in r.text
        # The old POST form to close setup is gone.
        assert '<form method="post" action="/finish"' not in r.text
        assert '<form method="post" action="http://127.0.0.1:8000/finish"' not in r.text


class _HTMLChecker(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.inputs = []
        self.selects = []
        self.labels_for = set()
        self.tabindex_bad = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "h1":
            self.h1_count += 1
        if tag in ("input", "select"):
            self.inputs.append(attrs_dict) if tag == "input" else self.selects.append(attrs_dict)
        if tag == "label" and "for" in attrs_dict:
            self.labels_for.add(attrs_dict["for"])
        if int(attrs_dict.get("tabindex", 0)) > 0:
            self.tabindex_bad = True


def _check_page(text: str) -> _HTMLChecker:
    checker = _HTMLChecker()
    checker.feed(text)
    return checker


def _assert_accessible(text: str):
    checker = _check_page(text)
    assert checker.h1_count == 1, f"expected one h1, found {checker.h1_count}"
    assert not checker.tabindex_bad, "positive tabindex found"
    for inp in checker.inputs:
        if inp.get("type") == "hidden":
            continue
        input_id = inp.get("id")
        if input_id is None:
            if "aria-label" in inp or "aria-labelledby" in inp:
                continue
        assert input_id in checker.labels_for, f"input missing label for: {inp}"
    for sel in checker.selects:
        select_id = sel.get("id")
        assert select_id in checker.labels_for, f"select missing label for: {sel}"


def test_accessibility_across_pages(tmp_path):
    app = _mk_app(tmp_path)
    with _saved_client(app) as client:
        # Step page
        r_step = client.get("/step", headers={"Host": "127.0.0.1:8000"})
        assert r_step.status_code == 200
        _assert_accessible(r_step.text)

        # Review page
        r_review = client.get("/review", headers={"Host": "127.0.0.1:8000"})
        assert r_review.status_code == 200
        _assert_accessible(r_review.text)

        # Jobs page
        r_jobs = client.get("/jobs", headers={"Host": "127.0.0.1:8000"})
        assert r_jobs.status_code == 200
        _assert_accessible(r_jobs.text)

        # Finish page
        r_finish = client.get("/finish", headers={"Host": "127.0.0.1:8000"})
        assert r_finish.status_code == 200
        _assert_accessible(r_finish.text)


def test_no_route_starts_cycle(tmp_path):
    app = _mk_app(tmp_path)
    for route in app.routes:
        name = getattr(route, "name", "") or ""
        path = getattr(route, "path", "") or ""
        assert "spawn" not in name.lower()
        assert path != "/spawn"
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        try:
            source = inspect.getsource(endpoint)
        except (TypeError, OSError):
            continue
        assert "kaine.cycle" not in source, (
            f"route {name} at {path} may start kaine.cycle"
        )


def test_finish_token_reads_the_configured_secrets_file(tmp_path):
    """The token shown is the one in the secrets file setup writes to, not
    whatever a default location holds."""
    secrets_path = tmp_path / "custom-secrets.toml"
    token = "t" * 40
    secrets_path.write_text(f'[nexus]\noperator_token = "{token}"\n', encoding="utf-8")
    app = _mk_app(tmp_path, secrets_path=secrets_path)
    with _saved_client(app) as client:
        r = client.post(
            "/finish/token",
            headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"},
        )
        assert r.status_code == 200
        assert token in r.text
