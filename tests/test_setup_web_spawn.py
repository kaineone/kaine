# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the browser setup server spawn route (slice 5)."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

import kaine.hardware
import kaine.setup.web.spawn as spawn
from kaine.config import SHIPPED_CONFIG_PATH
from kaine.setup.web import guard
from kaine.setup.wizard import ACK_PHRASE
from tests.test_setup_web import _defaults_from_form, _mk_app


@pytest.fixture(autouse=True)
def _private_data_root(tmp_path, monkeypatch):
    """The saved test config may name the host's real data root (the storage
    step's default); spawn must never write acknowledgements or logs there."""
    monkeypatch.delenv("KAINE_DATA_ROOT", raising=False)
    monkeypatch.setattr(
        "kaine.setup.web.app.configured_data_root",
        lambda config, env=None: tmp_path / "data",
    )


@pytest.fixture(autouse=True)
def _isolated_guard(monkeypatch):
    """Never probe the host bus or process table during setup tests."""
    monkeypatch.setattr(guard, "load_bus_config", lambda *a, **k: object())
    monkeypatch.setattr(guard, "cycle_on_bus", lambda *a, **k: (False, "stub"))
    monkeypatch.setattr(
        guard, "cycle_process_details", lambda *a, **k: (False, None, None)
    )


def _canonical_app(tmp_path: Path, **overrides):
    """Build an app whose repo_root and config paths satisfy the default-path gate."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    shipped = config_dir / "kaine.toml"
    operator = config_dir / "kaine.operator.toml"

    real_shipped = Path(SHIPPED_CONFIG_PATH)
    if real_shipped.exists():
        shipped.write_text(real_shipped.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        shipped.write_text(
            "[lingua]\nmodel_id = 'model-a'\n[vox]\nbackend = 'chatterbox'\n"
            "predefined_voice_id = 'voice-a'\n[audition]\nbackend = 'speaches'\n"
            "stt_model = 'stt-a'\n",
            encoding="utf-8",
        )

    app = _mk_app(
        tmp_path,
        operator_path=operator,
        shipped_config_path=shipped,
        **overrides,
    )
    app.state.repo_root = tmp_path
    app.state.docker_probe = lambda: False
    return app


@contextlib.contextmanager
def _saved_client(tmp_path: Path, **overrides):
    """Yield a (TestClient, app) pair whose session has saved the operator file."""
    app = _canonical_app(tmp_path, **overrides)
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
        yield client, app


@pytest.fixture
def spawn_fakes(monkeypatch):
    """Patch spawn helpers so no real cycle or pre-boot is run."""
    calls: list[dict] = []

    async def fake_preboot(repo_root, *, timeout_s=600.0):
        return (True, [], "all good")

    def fake_start_cycle(repo_root, log_dir, *, keep_info, popen=subprocess.Popen, now=datetime.now):
        calls.append(
            {"repo_root": repo_root, "log_dir": log_dir, "keep_info": keep_info}
        )

        class Proc:
            pid = 12345

            def poll(self):
                return None

            def terminate(self):
                pass

            def kill(self):
                pass

        return (Proc(), log_dir / "cycle-test.log", log_dir / "cycle-test.stderr")

    async def fake_wait_ready(proc, runtime_path, *, timeout_s=30.0, poll_s=0.5):
        return ("ready", None)

    monkeypatch.setattr(spawn, "run_preboot", fake_preboot)
    monkeypatch.setattr(spawn, "start_cycle", fake_start_cycle)
    monkeypatch.setattr(spawn, "wait_ready", fake_wait_ready)

    return calls


def _spawn_post(client, affirmation=spawn.SPAWN_ACK_PHRASE, keep_info="false"):
    return client.post(
        "/spawn",
        data={"affirmation": affirmation, "keep_info": keep_info},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )


def _confirm_post(client, nonce):
    return client.post(
        "/spawn/confirm",
        data={"nonce": nonce},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )


def _extract_nonce(text: str) -> str:
    m = re.search(r'name="nonce" value="([^"]+)"', text)
    assert m, "nonce not found in confirmation page"
    return m.group(1)


def _mock_nexus(monkeypatch, port=12345):
    monkeypatch.setattr(
        "kaine.setup.web.app.load_nexus_config",
        lambda path, **kwargs: SimpleNamespace(port=port, operator_token="x" * 40),
    )


def test_spawn_refuses_wrong_affirmation(tmp_path, spawn_fakes):
    with _saved_client(tmp_path) as (client, _app):
        r = _spawn_post(client, affirmation="not the phrase")
        assert r.status_code == 400
        assert "acknowledgement" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_running_job(tmp_path, spawn_fakes, monkeypatch):
    with _saved_client(tmp_path) as (client, app):
        sid = client.cookies.get("setup_session")
        app.state.setup.store.sessions[sid].setdefault("job_ids", []).append("job-1")
        monkeypatch.setattr(
            app.state.runner, "status", lambda job_id: {"status": "running"}
        )

        r = _spawn_post(client)
        assert r.status_code == 409
        assert "job" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_already_spawned_live_pid(tmp_path, spawn_fakes, monkeypatch):
    with _saved_client(tmp_path) as (client, app):
        app.state.spawned = {"pid": os.getpid(), "log_path": Path("x"), "stderr_path": Path("y")}
        r = _spawn_post(client)
        assert r.status_code == 409
        assert "already" in r.text.lower()
        assert not spawn_fakes
        # The next request sees the stale spawned record cleaned up.
        app.state.spawned = {"pid": 999999999, "log_path": Path("x"), "stderr_path": Path("y")}
        r2 = _spawn_post(client)
        assert r2.status_code != 409 or "already" not in r2.text.lower()


def test_spawn_refuses_guard_reports_running(tmp_path, spawn_fakes, monkeypatch):
    with _saved_client(tmp_path) as (client, _app):
        monkeypatch.setattr(
            guard, "cycle_running_with_reason", lambda state_root: (True, "guard-test")
        )
        r = _spawn_post(client)
        assert r.status_code == 409
        assert "running" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_non_default_operator_path(tmp_path, spawn_fakes):
    app = _canonical_app(tmp_path)
    app.state.setup.operator_path = tmp_path / "other.operator.toml"
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        token = app.state.setup.store.issue()
        client.get(f"/?token={token}", headers={"Host": "127.0.0.1:8000"})
        sid = client.cookies.get("setup_session")
        app.state.setup.store.sessions[sid]["saved"] = True

        r = _spawn_post(client)
        assert r.status_code == 409
        assert "non-default" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_compose_inside_container(tmp_path, spawn_fakes, monkeypatch):
    with _saved_client(tmp_path) as (client, _app):
        monkeypatch.setattr(kaine.hardware, "_in_container", lambda: True)
        r = _spawn_post(client)
        assert r.status_code == 409
        assert "container" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_compose_network_target(tmp_path, spawn_fakes):
    with _saved_client(tmp_path) as (client, app):
        (tmp_path / "compose").mkdir()
        (tmp_path / "compose" / "kaine.yml").write_text(
            "services:\n  redis:\n    container_name: kaine-redis\n", encoding="utf-8"
        )
        operator = app.state.setup.operator_path
        text = operator.read_text(encoding="utf-8")
        operator.write_text(text + '\n[redis]\nhost = "kaine-redis"\n', encoding="utf-8")

        r = _spawn_post(client)
        assert r.status_code == 409
        assert "compose network" in r.text.lower()
        assert "kaine-redis" in r.text
        assert not spawn_fakes


def test_spawn_refuses_docker_probe_true(tmp_path, spawn_fakes):
    with _saved_client(tmp_path) as (client, app):
        app.state.docker_probe = lambda: True
        r = _spawn_post(client)
        assert r.status_code == 409
        assert "kaine-cycle container" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_docker_probe_unknown(tmp_path, spawn_fakes):
    with _saved_client(tmp_path) as (client, app):
        app.state.docker_probe = lambda: None
        r = _spawn_post(client)
        assert r.status_code == 409
        assert "docker" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_research_supervision(tmp_path, spawn_fakes):
    with _saved_client(tmp_path) as (client, app):
        operator = app.state.setup.operator_path
        text = operator.read_text(encoding="utf-8")
        operator.write_text(text + "\n[research]\nenabled = true\n", encoding="utf-8")

        r = _spawn_post(client)
        assert r.status_code == 409
        assert "research" in r.text.lower()
        assert not spawn_fakes


def test_spawn_refuses_ack_write_failure(tmp_path, spawn_fakes, monkeypatch):
    with _saved_client(tmp_path) as (client, _app):
        monkeypatch.setattr(
            spawn, "record_acknowledgement", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
        )
        r = _spawn_post(client)
        assert r.status_code == 409
        assert not spawn_fakes


def test_spawn_confirm_refuses_failing_preboot(tmp_path, monkeypatch):
    async def fake_preboot(repo_root, *, timeout_s=600.0):
        return (
            False,
            [
                {
                    "group": "SERVICES",
                    "name": "Nexus (live)",
                    "status": "FAIL",
                    "detail": "Nexus is not running on port 11111; start it before spawning",
                },
                {
                    "group": "ORGAN",
                    "name": "organ",
                    "status": "WARN",
                    "detail": "mute",
                },
            ],
            "VERDICT: FAIL",
        )

    monkeypatch.setattr(spawn, "run_preboot", fake_preboot)
    monkeypatch.setattr(spawn, "start_cycle", lambda *a, **k: None)

    with _saved_client(tmp_path) as (client, _app):
        r1 = _spawn_post(client)
        assert r1.status_code == 200
        nonce = _extract_nonce(r1.text)

        r2 = _confirm_post(client, nonce)
        assert r2.status_code == 409
        assert "Nexus (live)" in r2.text
        assert "mute" in r2.text


def test_spawn_full_run_starts_once(tmp_path, monkeypatch, spawn_fakes):
    _mock_nexus(monkeypatch)

    with _saved_client(tmp_path) as (client, _app):
        r1 = _spawn_post(client, keep_info="true")
        assert r1.status_code == 200
        nonce = _extract_nonce(r1.text)

        r2 = _confirm_post(client, nonce)
        assert r2.status_code == 200
        assert "Open Nexus" in r2.text

        assert len(spawn_fakes) == 1
        assert spawn_fakes[0]["keep_info"] is True


def test_spawn_double_submit_same_nonce(tmp_path, monkeypatch, spawn_fakes):
    _mock_nexus(monkeypatch)

    with _saved_client(tmp_path) as (client, _app):
        r1 = _spawn_post(client)
        assert r1.status_code == 200
        nonce = _extract_nonce(r1.text)

        r2 = _confirm_post(client, nonce)
        assert r2.status_code == 200

        r3 = _confirm_post(client, nonce)
        assert r3.status_code == 403
        assert len(spawn_fakes) == 1


def test_spawn_confirm_lock_serializes(tmp_path, monkeypatch, spawn_fakes):
    _mock_nexus(monkeypatch)

    with _saved_client(tmp_path) as (client, app):
        r1 = _spawn_post(client)
        nonce = _extract_nonce(r1.text)

        class _HeldLock:
            """A spawn already in progress: the route must refuse at once."""

            def locked(self) -> bool:
                return True

        real_lock = app.state.spawn_lock
        app.state.spawn_lock = _HeldLock()
        try:
            r2 = _confirm_post(client, nonce)
            assert r2.status_code == 409
            assert "already in progress" in r2.text.lower()
            assert len(spawn_fakes) == 0
        finally:
            app.state.spawn_lock = real_lock


def test_spawn_confirm_expired_nonce(tmp_path, monkeypatch, spawn_fakes):
    _mock_nexus(monkeypatch)

    with _saved_client(tmp_path) as (client, _app):
        r1 = _spawn_post(client)
        nonce = _extract_nonce(r1.text)

        monkeypatch.setattr(
            spawn, "NONCE_TTL_S", -1.0
        )
        r2 = _confirm_post(client, nonce)
        assert r2.status_code == 403
        assert "expired" in r2.text.lower()
        assert not spawn_fakes


def test_spawn_confirm_nonce_from_other_session(tmp_path, monkeypatch, spawn_fakes):
    _mock_nexus(monkeypatch)

    with _saved_client(tmp_path) as (client, app):
        r1 = _spawn_post(client)
        _extract_nonce(r1.text)  # consume the nonce in the normal session

        # A second client with a fresh session submits a made-up nonce.
        with TestClient(app, base_url="http://127.0.0.1:8000") as client2:
            token = app.state.setup.store.issue()
            client2.get(f"/?token={token}", headers={"Host": "127.0.0.1:8000"})
            r2 = client2.post(
                "/spawn/confirm",
                data={"nonce": "totally-fake-nonce"},
                headers={
                    "Host": "127.0.0.1:8000",
                    "Origin": "http://127.0.0.1:8000",
                },
            )
            assert r2.status_code == 403
            assert not spawn_fakes


def test_spawn_routes_require_session(tmp_path):
    app = _canonical_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        r1 = client.post(
            "/spawn",
            data={"affirmation": spawn.SPAWN_ACK_PHRASE},
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
        )
        assert r1.status_code == 403

        r2 = client.post(
            "/spawn/confirm",
            data={"nonce": "x"},
            headers={
                "Host": "127.0.0.1:8000",
                "Origin": "http://127.0.0.1:8000",
            },
        )
        assert r2.status_code == 403


def test_only_spawn_route_starts_cycle():
    import kaine.setup.web.app as app_mod
    import kaine.setup.web.spawn as spawn_mod

    spawn_source = inspect.getsource(spawn_mod)
    spawn_tree = ast.parse(spawn_source)

    literal_count = 0
    for node in ast.walk(spawn_tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in ast.walk(node):
                if isinstance(elt, ast.Constant) and elt.value == "kaine.cycle":
                    literal_count += 1
    assert literal_count == 1, (
        "exactly one list/tuple literal in kaine/setup/**/*.py may contain 'kaine.cycle'"
    )

    func = spawn_mod.start_cycle
    func_source = inspect.getsource(func)
    func_tree = ast.parse(func_source)
    func_literal = 0
    for node in ast.walk(func_tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            for elt in ast.walk(node):
                if isinstance(elt, ast.Constant) and elt.value == "kaine.cycle":
                    func_literal += 1
    assert func_literal == 1, "the 'kaine.cycle' literal must be inside spawn.start_cycle"

    app_source = inspect.getsource(app_mod)
    app_tree = ast.parse(app_source)

    endpoint_names: dict[str, str] = {}
    for node in ast.walk(app_tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.decorator_list:
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in ("get", "post")
                ):
                    name_kw = next((k for k in dec.keywords if k.arg == "name"), None)
                    if name_kw and isinstance(name_kw.value, ast.Constant):
                        endpoint_names[node.name] = name_kw.value.value

    start_refs = 0
    for node in ast.walk(app_tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in endpoint_names:
            for sub in ast.walk(node):
                if (
                    (isinstance(sub, ast.Name) and sub.id == "start_cycle")
                    or (
                        isinstance(sub, ast.Attribute)
                        and sub.attr == "start_cycle"
                    )
                ):
                    start_refs += 1
                    assert endpoint_names[node.name] == "spawn_confirm", (
                        f"only /spawn/confirm may call start_cycle, found "
                        f"{endpoint_names[node.name]}"
                    )
    assert start_refs == 1, "exactly one function body in app.py may reference start_cycle"


def test_start_cycle_arguments_and_env(tmp_path, monkeypatch):
    recorded = {}

    class FakePopen:
        def __init__(self, argv, **kwargs):
            recorded["argv"] = argv
            recorded["kwargs"] = kwargs
            self.pid = 4242

        def poll(self):
            return None

    log_dir = tmp_path / "logs"
    proc, log_path, stderr_path = spawn.start_cycle(
        tmp_path,
        log_dir,
        keep_info=False,
        popen=FakePopen,
        now=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    assert recorded["argv"] == [
        sys.executable,
        "-m",
        "kaine.cycle",
        "--log-file",
        str(log_path),
        "--log-level",
        "WARNING",
    ]
    assert recorded["kwargs"]["start_new_session"] is True
    assert recorded["kwargs"]["stdout"] is subprocess.DEVNULL
    assert recorded["kwargs"]["stdin"] is subprocess.DEVNULL
    assert "KAINE_CYCLE_OPERATOR_PRESENT" in recorded["kwargs"]["env"]
    assert recorded["kwargs"]["env"]["KAINE_CYCLE_OPERATOR_PRESENT"] == "1"
    assert os.environ.get("KAINE_CYCLE_OPERATOR_PRESENT") is None

    assert log_dir.stat().st_mode & 0o777 == 0o700
    assert stderr_path.exists()
    assert stat.S_IMODE(stderr_path.stat().st_mode) == 0o600


def test_start_cycle_prune_keeps_10(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(mode=0o700)

    for i in range(15):
        stamp = f"20260101T{i:02d}0000Z"
        (log_dir / f"cycle-{stamp}.log").write_text("x", encoding="utf-8")
        (log_dir / f"cycle-{stamp}.stderr").write_text("x", encoding="utf-8")

    spawn.prune_logs(log_dir, keep=10)
    remaining = sorted(p.name for p in log_dir.iterdir())
    assert len(remaining) == 20
    assert remaining[0] == "cycle-20260101T050000Z.log"
    assert remaining[-1] == "cycle-20260101T140000Z.stderr"


def test_wait_ready_exited(tmp_path):
    class Proc:
        def __init__(self, code):
            self._code = code
            self.pid = 1

        def poll(self):
            return self._code

    result = asyncio.run(
        spawn.wait_ready(Proc(7), tmp_path / "runtime.json", timeout_s=0.2, poll_s=0.05)
    )
    assert result == ("exited", 7)


def test_wait_ready_runtime_match(tmp_path):
    class Proc:
        pid = 4242

        def poll(self):
            return None

    runtime = tmp_path / "runtime.json"
    runtime.write_text('{"pid": 4242}', encoding="utf-8")

    result = asyncio.run(
        spawn.wait_ready(Proc(), runtime, timeout_s=0.5, poll_s=0.05)
    )
    assert result == ("ready", None)


def test_wait_ready_timeout(tmp_path):
    class Proc:
        pid = 4242

        def poll(self):
            return None

    result = asyncio.run(
        spawn.wait_ready(Proc(), tmp_path / "runtime.json", timeout_s=0.1, poll_s=0.05)
    )
    assert result == ("starting", None)


def test_error_summary_strips_message_content(tmp_path):
    log = tmp_path / "cycle.log"
    log.write_text(
        "2026-01-01 00:00:00,000 ERROR kaine.x: SECRET-CONTENT\n"
        "2026-01-01 00:00:01,000 CRITICAL kaine.y: ANOTHER-SECRET\n",
        encoding="utf-8",
    )

    summary = spawn.error_summary(log, max_lines=5)
    assert len(summary) == 2
    assert all("SECRET" not in line for line in summary)
    assert "ERROR kaine.x" in summary[0]
    assert "CRITICAL kaine.y" in summary[1]


def test_install_private_log_file(tmp_path, monkeypatch):
    import logging

    from kaine.cycle.private_log import install_private_log_file

    log_dir = tmp_path / "logs"
    path = log_dir / "entity.log"

    # Capture original handlers so we can restore them.
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    for h in original_handlers:
        root.removeHandler(h)

    handler = None
    try:
        handler = install_private_log_file(path, max_bytes=80, backup_count=2)
        log = logging.getLogger("kaine.test")
        log.warning("first message")
        log.warning("second message that is long enough to rotate the file")
        log.warning("third message that is long enough to rotate the file again")

        assert log_dir.stat().st_mode & 0o777 == 0o700
        for f in log_dir.iterdir():
            assert stat.S_IMODE(f.stat().st_mode) == 0o600, f

        stderr_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and getattr(h, "stream", None) is sys.stderr
        ]
        assert not stderr_handlers
    finally:
        root.removeHandler(handler)
        for h in original_handlers:
            root.addHandler(h)


def test_preboot_nexus_live_row(monkeypatch):
    import kaine.nexus.health.probes as probes
    import kaine.preboot as preboot

    class FakeProber:
        async def snapshot(self, force=True):
            return {"dependencies": []}

    monkeypatch.setattr(preboot, "load_health_prober", lambda **kwargs: FakeProber())
    monkeypatch.setattr(probes, "set_sherpa_probe_wait", lambda x: None)
    monkeypatch.setattr(probes, "get_sherpa_probe_wait", lambda: 0.0)

    class Cfg:
        port = 12345

    monkeypatch.setattr(preboot, "load_nexus_config", lambda *a, **k: Cfg())

    monkeypatch.setattr(preboot, "port_listening", lambda port, timeout_s=1.0: True)
    results = asyncio.run(preboot.check_services())
    nexus = next(r for r in results if r.name == "Nexus (live)")
    assert nexus.status == preboot.PASS
    assert "listening" in nexus.detail

    monkeypatch.setattr(preboot, "port_listening", lambda port, timeout_s=1.0: False)
    results = asyncio.run(preboot.check_services())
    nexus = next(r for r in results if r.name == "Nexus (live)")
    assert nexus.status == preboot.FAIL
    assert "not running" in nexus.detail

    monkeypatch.setattr(
        preboot,
        "load_nexus_config",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")),
    )
    results = asyncio.run(preboot.check_services())
    nexus = next(r for r in results if r.name == "Nexus (live)")
    assert nexus.status == preboot.FAIL
    assert "could not be read" in nexus.detail
    assert "ValueError" in nexus.detail


def test_preboot_json_output(monkeypatch, capsys):
    import kaine.preboot as preboot

    monkeypatch.setattr(preboot, "load_runtime_config", lambda shipped, operator: {})
    monkeypatch.setattr(
        "kaine.storage.install_data_root", lambda config: None
    )
    monkeypatch.setattr(preboot, "run_async_checks", AsyncMock(return_value=[]))
    monkeypatch.setattr(preboot, "check_config_sanity", lambda config: [])

    assert preboot.main(["--json"]) == 0
    out = capsys.readouterr().out
    report = preboot.json.loads(out)
    assert isinstance(report, dict)
    assert "ok" in report
    assert "verdict" in report
    assert "results" in report
    assert report["ok"] is True


def test_compose_markers_hides_redis_password(tmp_path):
    (tmp_path / "compose").mkdir()
    (tmp_path / "compose" / "kaine.yml").write_text(
        "services:\n  redis:\n    container_name: kaine-redis\n", encoding="utf-8"
    )

    markers = spawn.compose_markers(
        {},
        repo_root=tmp_path,
        env={"KAINE_REDIS_URL": "redis://u:SECRETPW@kaine-redis:6379/0"},
        docker_probe=lambda: False,
    )
    assert any("compose network" in m for m in markers)
    assert all("SECRETPW" not in m for m in markers)
    assert any("kaine-redis" in m for m in markers)


def test_spawn_guard_checks_the_saved_config_state_dir(tmp_path, monkeypatch, spawn_fakes):
    """The guard looks at the state dir the cycle will use, not setup's startup one."""
    seen: list[Path] = []

    def spy(state_root):
        seen.append(Path(state_root))
        return (False, None)

    with _saved_client(tmp_path) as (client, app):
        app.state.setup.state_root = tmp_path / "stale-startup-state"
        monkeypatch.setattr(guard, "cycle_running_with_reason", spy)
        r1 = _spawn_post(client)
        assert r1.status_code == 200
    assert seen, "the guard was not consulted"
    assert all(p != tmp_path / "stale-startup-state" for p in seen)
    assert seen[-1] == tmp_path / "data" / "state"


def test_spawn_exited_start_keeps_setup_open(tmp_path, monkeypatch, spawn_fakes):
    _mock_nexus(monkeypatch)

    async def exited(proc, runtime_path, *, timeout_s=30.0, poll_s=0.5):
        return ("exited", 1)

    monkeypatch.setattr(spawn, "wait_ready", exited)
    with _saved_client(tmp_path) as (client, app):
        nonce = _extract_nonce(_spawn_post(client).text)
        r = _confirm_post(client, nonce)
        assert r.status_code == 200
        assert app.state.finish_shutdown is False
        assert app.state.spawned is None


def test_spawn_ready_start_closes_setup(tmp_path, monkeypatch, spawn_fakes):
    _mock_nexus(monkeypatch)
    with _saved_client(tmp_path) as (client, app):
        nonce = _extract_nonce(_spawn_post(client).text)
        assert _confirm_post(client, nonce).status_code == 200
        assert app.state.finish_shutdown is True
        assert app.state.spawned is not None


def test_spawn_preboot_row_with_empty_detail_is_shown(tmp_path, monkeypatch, spawn_fakes):
    async def failing(repo_root, *, timeout_s=600.0):
        return (False, [{"group": "SERVICES", "name": "quiet", "status": "FAIL", "detail": ""}], "VERDICT: FAIL")

    monkeypatch.setattr(spawn, "run_preboot", failing)
    with _saved_client(tmp_path) as (client, _app):
        nonce = _extract_nonce(_spawn_post(client).text)
        r = _confirm_post(client, nonce)
        assert r.status_code == 409
        assert "quiet" in r.text
        assert len(spawn_fakes) == 0


def test_spawn_start_failure_is_refused_not_500(tmp_path, monkeypatch, spawn_fakes):
    def boom(*args, **kwargs):
        raise OSError("no exec")

    monkeypatch.setattr(spawn, "start_cycle", boom)
    with _saved_client(tmp_path) as (client, app):
        nonce = _extract_nonce(_spawn_post(client).text)
        r = _confirm_post(client, nonce)
        assert r.status_code == 409
        assert "could not be started (OSError)" in r.text
        assert app.state.spawned is None
        assert app.state.finish_shutdown is False
