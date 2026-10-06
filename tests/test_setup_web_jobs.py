# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the browser setup server's consented jobs (slice 3)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from typing import Any

import pytest
from starlette.testclient import TestClient

from kaine.setup.web.job_specs import build_job_specs
from kaine.setup.web.jobs import JobRunner, JobSpec, _Job
from kaine.setup.wizard import ACK_PHRASE
from tests.test_setup_web import _defaults_from_form, _mk_app


def _wait_for_job(runner: JobRunner, name: str, timeout: float = 5.0) -> dict[str, Any]:
    job_id = runner.job_id_for_name(name)
    assert job_id is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = runner.status(job_id)
        if st["status"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError(f"job {name} did not finish within {timeout}s")


@contextmanager
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


class _FakeDetachedProcess:
    def __init__(self):
        self.stdout = None
        self.returncode = None
        self.pid = 1

    async def wait(self):
        await asyncio.Event().wait()


class _FakePopen:
    def __init__(self, poll_returns=()):
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.poll_returns = list(poll_returns)
        self.poll_index = 0
        self.returncode: int | None = None
        self.pid = 12345

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self

    def poll(self):
        if self.poll_index < len(self.poll_returns):
            ret = self.poll_returns[self.poll_index]
            self.poll_index += 1
            if ret is not None:
                self.returncode = ret
            return ret
        return self.returncode


def test_jobs_do_not_start_without_post(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    exec_calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def fake_create(*argv, **kwargs):
        exec_calls.append((argv, kwargs))
        return None

    monkeypatch.setattr(
        "kaine.setup.web.jobs.asyncio.create_subprocess_exec", fake_create
    )

    fake_popen = _FakePopen()
    monkeypatch.setattr("kaine.setup.web.jobs.subprocess.Popen", fake_popen)

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000"}
        r_jobs = client.get("/jobs", headers=h, follow_redirects=False)
        assert r_jobs.status_code == 200

        r_review = client.get("/review", headers=h)
        assert r_review.status_code in (200, 303)

        assert exec_calls == []
        assert fake_popen.calls == []


def test_post_starts_job_and_events_stream_succeeded(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    harmless = JobSpec(
        name="harmless",
        title="Harmless job",
        argv=(sys.executable, "-c", "print('a'); print('b')"),
        details="print test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [harmless],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/harmless/start", headers=h, follow_redirects=False)
        assert start.status_code == 303

        st = _wait_for_job(app.state.runner, "harmless")
        assert st["status"] == "succeeded"
        assert st["exit_code"] == 0

        job_id = app.state.runner.job_id_for_name("harmless")
        chunks: list[str] = []
        with client.stream(
            "GET", f"/jobs/{job_id}/events", headers={"Host": "127.0.0.1:8000"}
        ) as stream:
            for chunk in stream.iter_text():
                chunks.append(chunk)

        text = "".join(chunks)
        assert "data: a\n\n" in text
        assert "data: b\n\n" in text
        assert "event: done" in text


def test_failing_job_reports_status_and_last_lines(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    failing = JobSpec(
        name="failing",
        title="Failing job",
        argv=(sys.executable, "-c", "import sys; print('x'); sys.exit(3)"),
        details="failing test",
    )
    harmless = JobSpec(
        name="harmless",
        title="Harmless job",
        argv=(sys.executable, "-c", "print('ok')"),
        details="harmless test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [failing, harmless],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/failing/start", headers=h, follow_redirects=False)
        assert start.status_code == 303

        st = _wait_for_job(app.state.runner, "failing")
        assert st["status"] == "failed"
        assert st["exit_code"] == 3

        job_id = app.state.runner.job_id_for_name("failing")
        with client.stream(
            "GET", f"/jobs/{job_id}/events", headers={"Host": "127.0.0.1:8000"}
        ) as stream:
            text = "".join(stream.iter_text())
        assert "data: x" in text
        assert "event: done" in text

        messages = text.split("\n\n")
        done_messages = [m for m in messages if m.startswith("event: done")]
        assert done_messages
        done_data = done_messages[-1].split("\n", 1)[1]
        payload = json.loads(done_data[len("data: ") :])
        assert payload["last_lines"][-1] == "x"

        r_jobs = client.get("/jobs", headers={"Host": "127.0.0.1:8000"})
        assert r_jobs.status_code == 200
        assert "Failing job" in r_jobs.text
        assert "Harmless job" in r_jobs.text
        # Both jobs still offer their Start form after the failure.
        assert 'action="http://127.0.0.1:8000/jobs/failing/start"' in r_jobs.text
        assert 'action="http://127.0.0.1:8000/jobs/harmless/start"' in r_jobs.text


def test_running_job_holds_activity(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    slow = JobSpec(
        name="slow",
        title="Slow job",
        argv=(sys.executable, "-c", "import time; time.sleep(0.3); print('ok')"),
        details="slow test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [slow],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/slow/start", headers=h, follow_redirects=False)

        assert app.state.activity_hold > 0

        _wait_for_job(app.state.runner, "slow")
        assert app.state.activity_hold == 0


def test_detached_job_uses_new_session_and_probe(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    probe_calls: list[bool] = []

    def probe():
        probe_calls.append(True)
        return len(probe_calls) > 1

    detached = JobSpec(
        name="detached",
        title="Detached job",
        argv=(sys.executable, "-c", "import time; time.sleep(10)"),
        detach=True,
        ready_probe=probe,
        details="detached test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [detached],
    )

    fake_popen = _FakePopen()
    monkeypatch.setattr("kaine.setup.web.jobs.subprocess.Popen", fake_popen)

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/detached/start", headers=h, follow_redirects=False)
        assert start.status_code == 303

        st = _wait_for_job(app.state.runner, "detached")
        assert st["status"] == "succeeded"

        assert len(fake_popen.calls) == 1
        args, kwargs = fake_popen.calls[0]
        assert args == (list(detached.argv),)
        assert kwargs.get("start_new_session") is True
        assert kwargs.get("stdout") is subprocess.DEVNULL
        assert kwargs.get("stdin") is subprocess.DEVNULL
        assert kwargs.get("stderr") is subprocess.DEVNULL


def test_detached_job_probe_already_true_is_failed(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    fake_popen = _FakePopen()
    monkeypatch.setattr("kaine.setup.web.jobs.subprocess.Popen", fake_popen)

    detached = JobSpec(
        name="detached",
        title="Detached job",
        argv=(sys.executable, "-c", "print('ok')"),
        detach=True,
        ready_probe=lambda: True,
        details="detached test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [detached],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/detached/start", headers=h, follow_redirects=False)
        assert start.status_code == 303

        st = _wait_for_job(app.state.runner, "detached")
        assert st["status"] == "failed"

        job_id = app.state.runner.job_id_for_name("detached")
        with client.stream(
            "GET", f"/jobs/{job_id}/events", headers={"Host": "127.0.0.1:8000"}
        ) as stream:
            text = "".join(stream.iter_text())
        assert "port already in use" in text
        assert fake_popen.calls == []


def test_detached_fake_exits_before_listening_is_failed(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    probe_calls: list[bool] = []

    def probe():
        probe_calls.append(True)
        return False

    detached = JobSpec(
        name="detached",
        title="Detached job",
        argv=(sys.executable, "-c", "print('ok')"),
        detach=True,
        ready_probe=probe,
        details="detached test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [detached],
    )

    fake_popen = _FakePopen(poll_returns=[4])
    monkeypatch.setattr("kaine.setup.web.jobs.subprocess.Popen", fake_popen)

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/detached/start", headers=h, follow_redirects=False)
        assert start.status_code == 303

        st = _wait_for_job(app.state.runner, "detached")
        assert st["status"] == "failed"
        assert st["exit_code"] == 4

        job_id = app.state.runner.job_id_for_name("detached")
        with client.stream(
            "GET", f"/jobs/{job_id}/events", headers={"Host": "127.0.0.1:8000"}
        ) as stream:
            text = "".join(stream.iter_text())
        assert "exited before it was listening" in text


def test_no_route_or_job_starts_cycle(tmp_path):
    app = _mk_app(tmp_path)
    repo_root = app.state.repo_root
    shipped_config_path = app.state.shipped_config_path
    operator_path = app.state.setup.operator_path
    full_config = {
        "modules": {
            "lingua": True,
            "mnemos": True,
            "empatheia": True,
            "audition": True,
            "vox": True,
            "hypnos": True,
        },
        "nexus": {"port": 1234},
    }
    specs = build_job_specs(
        full_config,
        app.state.setup.shipped,
        repo_root=repo_root,
        shipped_config_path=shipped_config_path,
        operator_path=operator_path,
    )
    for spec in specs:
        for part in spec.argv:
            assert "kaine.cycle" not in part, (spec.name, part)

    forbidden = "kaine.cycle"
    for route in app.routes:
        for attr in ("path", "name"):
            value = getattr(route, attr, "")
            if isinstance(value, str):
                assert forbidden not in value, (attr, value, route)


def test_cross_origin_post_rejected_and_session_required(tmp_path):
    app = _mk_app(tmp_path)

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://evil.example"}
        r = client.post(
            "/jobs/extras/start",
            headers=h,
            follow_redirects=False,
        )
        assert r.status_code == 403

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://evil.example"}
        r = client.post(
            "/jobs/extras/start",
            headers=h,
            follow_redirects=False,
        )
        assert r.status_code == 403


def test_same_origin_post_no_session_gets_403(tmp_path):
    app = _mk_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r = client.post(
            "/jobs/extras/start",
            headers=h,
            follow_redirects=False,
        )
        assert r.status_code == 403


def test_finish_requires_a_saved_configuration(tmp_path):
    app = _mk_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        token = app.state.setup.store.issue()
        client.get(f"/?token={token}", headers={"Host": "127.0.0.1:8000"}, follow_redirects=False)
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r = client.post("/finish", headers=h, follow_redirects=False)
        assert r.status_code == 403
        assert app.state.finish_shutdown is False


def test_save_does_not_shutdown_finish_does(tmp_path):
    app = _mk_app(tmp_path)

    with _saved_client(app) as client:
        assert app.state.finish_shutdown is False
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r_finish = client.post("/finish", headers=h, follow_redirects=False)
        assert r_finish.status_code == 200
        assert app.state.finish_shutdown is True


def test_organ_cli_download_yes(tmp_path, monkeypatch, capsys):
    from kaine.setup import organ as organ_mod

    backend = organ_mod.OrganBackend(
        backend="cpu", available=True, path=None, summary="cpu"
    )
    artifact = organ_mod.OrganArtifact(
        repo="kaineone/Qwen3.5-4B-abliterated-GGUF",
        fmt="gguf",
        reason="test",
        size_gb=1.0,
        command=["echo", "test"],
    )
    plan = organ_mod.OrganDownloadPlan(
        needed=True,
        backend=backend,
        artifacts=(artifact,),
    )

    good = [
        organ_mod.OrganDownloadResult(
            repo=artifact.repo,
            fmt="gguf",
            ok=True,
            revision="abc123",
            detail="downloaded abc123",
        )
    ]
    bad = [
        organ_mod.OrganDownloadResult(
            repo=artifact.repo,
            fmt="gguf",
            ok=False,
            detail="network error",
        )
    ]

    def fake_load_kaine_config(shipped, operator_path=None):
        return {"modules": {"lingua": True}}

    monkeypatch.setattr("kaine.config.load_kaine_config", fake_load_kaine_config)
    monkeypatch.setattr("kaine.hardware.describe_host", lambda: {"backend": "cpu"})
    monkeypatch.setattr(
        "kaine.organ_server.served.detect_organ_backend",
        lambda backend: plan.backend,
    )

    monkeypatch.setattr(
        organ_mod, "plan_organ_download", lambda modules, backend, config=None: plan
    )

    written: list[list[organ_mod.OrganDownloadResult]] = []
    monkeypatch.setattr(
        organ_mod,
        "write_revision_state",
        lambda results: written.append(results) or str(tmp_path / "rev.json"),
    )

    runs: list[bool] = []
    monkeypatch.setattr(
        organ_mod,
        "run_organ_download",
        lambda _plan, consent, **kwargs: runs.append(consent) or good,
    )
    assert organ_mod.main(["download", "--yes"]) == 0
    assert runs == [True]
    assert len(written) == 1

    runs.clear()
    written.clear()
    monkeypatch.setattr(
        organ_mod,
        "run_organ_download",
        lambda _plan, consent, **kwargs: runs.append(consent) or bad,
    )
    assert organ_mod.main(["download", "--yes"]) == 1
    assert not written

    assert organ_mod.main(["download"]) == 2
    assert organ_mod.main(["download", "--yes-not"]) == 2

    # A failed provenance write is reported, not silent; the download stands.
    monkeypatch.setattr(
        organ_mod, "run_organ_download", lambda _plan, consent, **kwargs: good
    )
    monkeypatch.setattr(organ_mod, "write_revision_state", lambda results: None)
    assert organ_mod.main(["download", "--yes"]) == 0
    assert "could not be written" in capsys.readouterr().err

    unavailable_backend = organ_mod.OrganBackend(
        backend="cpu", available=False, path=None, summary="cpu (unavailable)"
    )
    unavailable_plan = organ_mod.OrganDownloadPlan(
        needed=True,
        backend=unavailable_backend,
        artifacts=(artifact,),
    )
    monkeypatch.setattr(
        "kaine.organ_server.served.detect_organ_backend",
        lambda backend: unavailable_plan.backend,
    )
    monkeypatch.setattr(
        organ_mod,
        "plan_organ_download",
        lambda modules, backend, config=None: unavailable_plan,
    )
    runs.clear()
    written.clear()
    assert organ_mod.main(["download", "--yes"]) == 1
    assert runs == []
    assert not written


def test_job_output_not_written_to_disk(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    job = JobSpec(
        name="printer",
        title="Printer",
        argv=(sys.executable, "-c", "print('hello')"),
        details="printer test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [job],
    )

    with _saved_client(app) as client:
        app.state.runner.repo_root = str(tmp_path)
        before = set(tmp_path.iterdir())

        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/printer/start", headers=h, follow_redirects=False)
        _wait_for_job(app.state.runner, "printer")

        after = set(tmp_path.iterdir())
        assert before == after


def test_deque_wrap_streams_drop_once_and_last_lines(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    lots = JobSpec(
        name="lots",
        title="Lots of lines",
        argv=(sys.executable, "-c", "for i in range(2500): print(i)"),
        details="lots test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [lots],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/lots/start", headers=h, follow_redirects=False)
        _wait_for_job(app.state.runner, "lots")

        job_id = app.state.runner.job_id_for_name("lots")
        chunks: list[str] = []
        with client.stream(
            "GET", f"/jobs/{job_id}/events", headers={"Host": "127.0.0.1:8000"}
        ) as stream:
            for chunk in stream.iter_text():
                chunks.append(chunk)

        text = "".join(chunks)
        drop_messages = [
            line for line in text.splitlines() if "earlier lines dropped" in line
        ]
        assert len(drop_messages) == 1
        assert "[500 earlier lines dropped]" in text

        data_lines = [
            line
            for line in text.splitlines()
            if line.startswith("data: ") and line[6:].isdigit()
        ]
        assert len(data_lines) == 2000
        assert data_lines[0] == "data: 500"
        assert data_lines[-1] == "data: 2499"


def test_progress_redraws_stream_last_segment(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    redraw = JobSpec(
        name="redraw",
        title="Redraw progress",
        argv=(sys.executable, "-c", "print('10%\\r50%\\r100%')"),
        details="redraw test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [redraw],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/redraw/start", headers=h, follow_redirects=False)
        _wait_for_job(app.state.runner, "redraw")

        job_id = app.state.runner.job_id_for_name("redraw")
        chunks: list[str] = []
        with client.stream(
            "GET", f"/jobs/{job_id}/events", headers={"Host": "127.0.0.1:8000"}
        ) as stream:
            for chunk in stream.iter_text():
                chunks.append(chunk)

        text = "".join(chunks)
        assert "data: 100%\n\n" in text
        assert "data: 10%" not in text
        assert "data: 50%" not in text


def test_finish_refuses_while_job_running(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    slow = JobSpec(
        name="slow",
        title="Slow job",
        argv=(sys.executable, "-c", "import time; time.sleep(2)"),
        details="slow test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [slow],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/slow/start", headers=h, follow_redirects=False)

        r_finish = client.post("/finish", headers=h, follow_redirects=False)
        assert r_finish.status_code == 409
        assert "a job is still running" in r_finish.text

        _wait_for_job(app.state.runner, "slow")

        r_finish2 = client.post("/finish", headers=h, follow_redirects=False)
        assert r_finish2.status_code == 200


def test_job_id_from_other_session_returns_404(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    harmless = JobSpec(
        name="harmless",
        title="Harmless job",
        argv=(sys.executable, "-c", "print('a')"),
        details="harmless test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [harmless],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/harmless/start", headers=h, follow_redirects=False)
        job_id = app.state.runner.job_id_for_name("harmless")

        # A second, genuinely authenticated session must not read it.
        with TestClient(app, base_url="http://127.0.0.1:8000") as other:
            token = app.state.setup.store.issue()
            r0 = other.get(
                f"/?token={token}",
                headers={"Host": "127.0.0.1:8000"},
                follow_redirects=False,
            )
            assert r0.status_code in (302, 303)
            r = other.get(
                f"/jobs/{job_id}/events",
                headers={"Host": "127.0.0.1:8000"},
                follow_redirects=False,
            )
            assert r.status_code == 404
            # The owning session can read it.
            ok = client.get(
                f"/jobs/{job_id}/events", headers={"Host": "127.0.0.1:8000"}
            )
            assert ok.status_code == 200


def test_default_specs_no_cycle_and_nexus_port_from_config(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True)
    shipped_config_path = config_dir / "kaine.toml"
    shipped_config_path.write_text("[nexus]\nport = 9123\n")
    operator_path = config_dir / "kaine.operator.toml"
    operator_path.write_text("")

    full_config = {
        "modules": {
            "lingua": True,
            "mnemos": True,
            "empatheia": True,
            "audition": True,
            "vox": True,
            "hypnos": True,
        },
    }

    recorded_ports: list[int] = []
    monkeypatch.setattr(
        "kaine.net.port_listening",
        lambda port: recorded_ports.append(port) or False,
    )

    specs = build_job_specs(
        full_config,
        {},
        repo_root=repo_root,
        shipped_config_path=shipped_config_path,
        operator_path=operator_path,
    )

    for spec in specs:
        for part in spec.argv:
            assert "kaine.cycle" not in part, (spec.name, part)

    organ_spec = next(s for s in specs if s.name == "organ_download")
    argv = list(organ_spec.argv)
    assert "--operator-config" in argv
    idx = argv.index("--operator-config")
    assert argv[idx + 1] == str(operator_path)

    nexus_spec = next(s for s in specs if s.name == "nexus")
    assert nexus_spec.ready_probe is not None
    nexus_spec.ready_probe()
    assert recorded_ports == [9123]


def test_detached_child_survives_runner_loop_close(tmp_path):
    if sys.platform == "win32":
        pytest.skip("start_new_session and killpg are POSIX-only")

    probe_results = [False, True]

    def probe():
        return probe_results.pop(0)

    async def run() -> tuple[JobRunner, str]:
        runner = JobRunner(tmp_path)
        spec = JobSpec(
            name="survivor",
            title="Survivor",
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
            detach=True,
            ready_probe=probe,
        )
        job_id = await runner.start("survivor", spec)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if runner.status(job_id)["status"] != "running":
                break
            await asyncio.sleep(0.05)
        assert runner.status(job_id)["status"] == "succeeded"
        return runner, job_id

    runner, job_id = asyncio.run(run())
    job = runner._jobs[job_id]
    try:
        assert job.popen is not None
        assert job.popen.poll() is None
    finally:
        if job.popen is not None:
            os.killpg(job.popen.pid, signal.SIGTERM)
            job.popen.wait(timeout=10)


def test_events_recompute_offsets_under_reader_writer_race(tmp_path):
    async def writer(job: _Job) -> None:
        for chunk_start in range(0, 2500, 100):
            for i in range(chunk_start, chunk_start + 100):
                job.add_line(str(i))
            await asyncio.sleep(0.02)
        job._done.set()
        job._new_line.set()

    async def reader(runner: JobRunner, job_id: str, out: list) -> None:
        async for item in runner.events(job_id):
            out.append(item)
            if isinstance(item, dict):
                return
            await asyncio.sleep(0.002)

    runner = JobRunner(tmp_path)
    spec = JobSpec(
        name="race",
        title="Race",
        argv=("true",),
        details="race test",
    )
    job = _Job(job_id="race-id", name="race", spec=spec)
    runner._jobs[job.job_id] = job
    runner._name_to_job_id[job.name] = job.job_id

    seen: list[str | dict[str, Any]] = []

    async def main() -> None:
        await asyncio.gather(writer(job), reader(runner, job.job_id, seen))

    asyncio.run(main())

    drop_re = re.compile(r"^\[(\d+) earlier lines dropped\]$")
    drop_messages = [x for x in seen if isinstance(x, str) and drop_re.match(x)]
    assert drop_messages, "expected at least one drop message"

    expected_index = 0
    for item in seen:
        if isinstance(item, dict):
            break
        m = drop_re.match(item)
        if m:
            expected_index += int(m.group(1))
            continue
        val = int(item)
        assert val == expected_index, f"expected line {expected_index}, got {val}"
        expected_index += 1

    assert expected_index == 2500


def test_job_is_done_only_after_all_its_output_is_read(tmp_path):
    """The exit status is published only once the reader has drained the pipe,
    so a fast-exiting job never loses its final lines."""
    script = "import sys; sys.stdout.write(''.join(f'{i}\\n' for i in range(3000)))"
    spec = JobSpec(name="burst", title="Burst", argv=(sys.executable, "-c", script))

    async def run() -> tuple[int, str]:
        runner = JobRunner(tmp_path)
        job_id = await runner.start("burst", spec)
        while runner.status(job_id)["status"] == "running":
            await asyncio.sleep(0)
        job = runner._jobs[job_id]
        # Captured at the instant the job reports done, before any more reads.
        return job.total, job.lines[-1]

    total, last = asyncio.run(run())
    assert total == 3000
    assert last == "2999"


def test_entity_guard_blocks_job_start(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    harmless = JobSpec(
        name="harmless",
        title="Harmless job",
        argv=(sys.executable, "-c", "print('ok')"),
        details="harmless test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [harmless],
    )

    with _saved_client(app) as client:
        # Patch the guard AFTER /save has created the session; /save itself must
        # still succeed.
        monkeypatch.setattr(
            "kaine.setup.web.app.guard.cycle_running_with_reason",
            lambda _root: (True, "test-reason"),
        )
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r = client.post("/jobs/harmless/start", headers=h, follow_redirects=False)
        assert r.status_code == 409
        assert "an entity is running" in r.text
        assert app.state.runner.job_id_for_name("harmless") is None

    monkeypatch.setattr(
        "kaine.setup.web.app.guard.cycle_running_with_reason",
        lambda _root: (False, None),
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r = client.post("/jobs/harmless/start", headers=h, follow_redirects=False)
        assert r.status_code == 303


def test_long_line_is_split_and_drained(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    long_line = JobSpec(
        name="long_line",
        title="Long line",
        argv=(sys.executable, "-c", "import sys; sys.stdout.write('x' * 200000)"),
        details="long line test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [long_line],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/long_line/start", headers=h, follow_redirects=False)
        assert start.status_code == 303

        st = _wait_for_job(app.state.runner, "long_line", timeout=10.0)
        assert st["status"] == "succeeded"

        job_id = app.state.runner.job_id_for_name("long_line")
        assert job_id is not None
        job = app.state.runner._jobs[job_id]
        assert all(len(line) <= 4000 for line in job.lines)


def test_redraws_are_rate_limited(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    script = (
        "import sys, time\n"
        "start = time.monotonic()\n"
        "while time.monotonic() - start < 1.5:\n"
        "    sys.stdout.write(f'{int((time.monotonic() - start) * 100)}%\\r')\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(0.01)\n"
        "sys.stdout.write('done\\n')\n"
        "sys.stdout.flush()\n"
    )
    redraw = JobSpec(
        name="redraw",
        title="Redraw progress",
        argv=(sys.executable, "-c", script),
        details="redraw test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [redraw],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/redraw/start", headers=h, follow_redirects=False)
        st = _wait_for_job(app.state.runner, "redraw", timeout=10.0)

        job_id = app.state.runner.job_id_for_name("redraw")
        job = app.state.runner._jobs[job_id]
        progress_lines = [ln for ln in job.lines if ln.endswith("%")]
        assert len(progress_lines) >= 2
        assert "done" in job.lines
        assert len(job.lines) < 50
        assert st["status"] == "succeeded"


def test_non_detached_job_timeout_kills_process(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    slow = JobSpec(
        name="slow",
        title="Slow job",
        argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        details="slow test",
        timeout_s=1.0,
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [slow],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/slow/start", headers=h, follow_redirects=False)
        assert start.status_code == 303

        st = _wait_for_job(app.state.runner, "slow", timeout=15.0)
        assert st["status"] == "failed"

        job_id = app.state.runner.job_id_for_name("slow")
        job = app.state.runner._jobs[job_id]
        assert any("timed out after 1" in ln for ln in job.lines)

        pid = job.proc.pid
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"timed-out process {pid} is still alive")


def test_cancel_route_kills_running_job(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    slow = JobSpec(
        name="slow",
        title="Slow job",
        argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        details="slow test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [slow],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        start = client.post("/jobs/slow/start", headers=h, follow_redirects=False)
        assert start.status_code == 303
        job_id = app.state.runner.job_id_for_name("slow")
        pid = app.state.runner._jobs[job_id].proc.pid

        r = client.post(f"/jobs/{job_id}/cancel", headers=h, follow_redirects=False)
        assert r.status_code == 200
        assert r.json() == {"status": "cancelled"}

        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if app.state.runner.status(job_id)["status"] == "cancelled":
                break
            time.sleep(0.05)
        assert app.state.runner.status(job_id)["status"] == "cancelled"

        with pytest.raises(OSError):
            os.killpg(pid, 0)

        r2 = client.post(f"/jobs/{job_id}/cancel", headers=h, follow_redirects=False)
        assert r2.status_code == 409


def test_cancel_other_session_job_returns_404(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    slow = JobSpec(
        name="slow",
        title="Slow job",
        argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        details="slow test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [slow],
    )

    with _saved_client(app) as client1:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client1.post("/jobs/slow/start", headers=h, follow_redirects=False)
        job_id = app.state.runner.job_id_for_name("slow")

        with _saved_client(app) as client2:
            r = client2.post(
                f"/jobs/{job_id}/cancel",
                headers=h,
                follow_redirects=False,
            )
            assert r.status_code == 404


def test_shutdown_kills_non_detached_and_grandchild(tmp_path):
    if sys.platform == "win32":
        pytest.skip("start_new_session and killpg are POSIX-only")

    async def run() -> tuple[JobRunner, str, int, int]:
        runner = JobRunner(tmp_path)
        script = (
            "import os, subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "print(os.getpid())\n"
            "print(child.pid)\n"
            "sys.stdout.flush()\n"
            "time.sleep(30)\n"
        )
        spec = JobSpec(
            name="family",
            title="Family",
            argv=(sys.executable, "-c", script),
            details="family test",
        )
        job_id = await runner.start("family", spec)
        job = runner._jobs[job_id]

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if job.lines:
                break
            await asyncio.sleep(0.05)

        parent_pid, child_pid = int(job.lines[0]), int(job.lines[1])

        await runner.shutdown()

        return runner, job_id, parent_pid, child_pid

    runner, job_id, parent_pid, child_pid = asyncio.run(run())

    with pytest.raises(OSError):
        os.kill(parent_pid, 0)
    with pytest.raises(OSError):
        os.kill(child_pid, 0)

    assert runner.status(job_id)["status"] == "failed"


def test_shutdown_leaves_detached_service_alive(tmp_path):
    if sys.platform == "win32":
        pytest.skip("start_new_session and killpg are POSIX-only")

    async def run() -> tuple[JobRunner, str]:
        runner = JobRunner(tmp_path)

        calls: list[int] = []
        def probe() -> bool:
            calls.append(1)
            return len(calls) > 1

        spec = JobSpec(
            name="detached",
            title="Detached",
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
            detach=True,
            ready_probe=probe,
        )
        job_id = await runner.start("detached", spec)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if runner.status(job_id)["status"] != "running":
                break
            await asyncio.sleep(0.05)
        await runner.shutdown()
        return runner, job_id

    runner, job_id = asyncio.run(run())
    job = runner._jobs[job_id]
    assert job.popen is not None
    assert job.popen.poll() is None
    os.killpg(job.popen.pid, signal.SIGTERM)
    job.popen.wait(timeout=10)


def test_abort_refuses_while_job_running(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    slow = JobSpec(
        name="slow",
        title="Slow job",
        argv=(sys.executable, "-c", "import time; time.sleep(5)"),
        details="slow test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [slow],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        client.post("/jobs/slow/start", headers=h, follow_redirects=False)

        r = client.post("/abort", headers=h, follow_redirects=False)
        assert r.status_code == 409
        assert "a job is still running" in r.text

        _wait_for_job(app.state.runner, "slow", timeout=8.0)


def test_extras_is_exclusive(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    extras_spec = JobSpec(
        name="extras",
        title="Extras",
        argv=(sys.executable, "-c", "print('extras')"),
        exclusive=True,
        details="extras test",
    )
    other_spec = JobSpec(
        name="other",
        title="Other",
        argv=(sys.executable, "-c", "import time; time.sleep(2)"),
        details="other test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [extras_spec, other_spec],
    )

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r1 = client.post("/jobs/other/start", headers=h, follow_redirects=False)
        assert r1.status_code == 303

        r2 = client.post("/jobs/extras/start", headers=h, follow_redirects=False)
        assert r2.status_code == 409

        _wait_for_job(app.state.runner, "other", timeout=8.0)

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r3 = client.post("/jobs/extras/start", headers=h, follow_redirects=False)
        assert r3.status_code == 303

        r4 = client.post("/jobs/other/start", headers=h, follow_redirects=False)
        assert r4.status_code == 409


def test_detached_log_path_captures_output(tmp_path):
    if sys.platform == "win32":
        pytest.skip("start_new_session and killpg are POSIX-only")

    log_path = tmp_path / "logs" / "service.log"

    async def run() -> JobRunner:
        runner = JobRunner(tmp_path)

        calls: list[int] = []
        def probe() -> bool:
            calls.append(1)
            return len(calls) > 1

        spec = JobSpec(
            name="logged",
            title="Logged service",
            argv=(
                sys.executable,
                "-c",
                "import sys, time\nsys.stdout.write('hello\\n')\nsys.stdout.flush()\ntime.sleep(30)\n",
            ),
            detach=True,
            ready_probe=probe,
            log_path=log_path,
        )
        job_id = await runner.start("logged", spec)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if runner.status(job_id)["status"] != "running":
                break
            await asyncio.sleep(0.05)
        await runner.shutdown()
        return runner

    runner = asyncio.run(run())
    # Detached services survive shutdown by design; stop this one by its own
    # process group, never by a name pattern.
    for job in runner._jobs.values():
        if job.popen is not None and job.popen.poll() is None:
            os.killpg(job.popen.pid, signal.SIGKILL)
            job.popen.wait(timeout=10)

    assert log_path.exists()
    assert "hello" in log_path.read_text()
    assert (log_path.stat().st_mode & 0o777) == 0o600
    assert (log_path.parent.stat().st_mode & 0o777) == 0o700



def test_probe_timeout_kills_non_listening_detached_child(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("start_new_session and killpg are POSIX-only")

    monkeypatch.setattr("kaine.setup.web.jobs.READY_TIMEOUT_S", 1.0)

    async def run() -> tuple[JobRunner, str]:
        runner = JobRunner(tmp_path)
        spec = JobSpec(
            name="sleeper",
            title="Sleeper",
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
            detach=True,
            ready_probe=lambda: False,
        )
        job_id = await runner.start("sleeper", spec)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if runner.status(job_id)["status"] != "running":
                break
            await asyncio.sleep(0.05)
        return runner, job_id

    runner, job_id = asyncio.run(run())
    job = runner._jobs[job_id]
    assert job.status == "failed"
    assert "not listening within 1 s" in job.lines[-1]
    # poll() reaps the child; os.kill(pid, 0) would also succeed on a zombie.
    assert job.popen.poll() is not None, "detached process survived probe timeout"


def test_main_no_revision_prints_no_rerun_warning(capsys, monkeypatch, tmp_path):
    from kaine.setup import organ

    fake_backend = type(
        "B",
        (),
        {
            "backend": "cpu",
            "available": True,
            "path": None,
            "summary": "cpu test backend",
        },
    )()
    fake_artifact = type(
        "Ar",
        (),
        {
            "repo": "kaineone/test",
            "fmt": "gguf",
            "reason": "test",
            "size_gb": 1.0,
            "command": (
                "hf",
                "download",
                "kaineone/test",
                "model.gguf",
                "--local-dir",
                str(tmp_path / "dir"),
            ),
        },
    )()
    fake_plan = type(
        "P",
        (),
        {
            "needed": True,
            "backend": fake_backend,
            "artifacts": [fake_artifact],
        },
    )()
    fake_result = type(
        "R",
        (),
        {
            "repo": "kaineone/test",
            "fmt": "gguf",
            "ok": True,
            "revision": None,
            "detail": "ok",
        },
    )()

    monkeypatch.setattr(
        "kaine.organ_server.served.detect_organ_backend",
        lambda _b, **kw: fake_backend,
    )
    monkeypatch.setattr(
        "kaine.hardware.describe_host", lambda: {"backend": "cpu"}
    )
    monkeypatch.setattr(organ, "plan_organ_download", lambda _m, _b, **kw: fake_plan)
    monkeypatch.setattr(
        organ,
        "run_organ_download",
        lambda *_a, **_kw: [fake_result],
    )
    monkeypatch.setattr(organ, "write_revision_state", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        "kaine.config.load_kaine_config",
        lambda *_a, **_kw: {"modules": {"lingua": True}},
    )

    rc = organ.main(
        [
            "download",
            "--yes",
            "--config",
            str(tmp_path / "s.toml"),
            "--operator-config",
            str(tmp_path / "o.toml"),
        ]
    )
    assert rc == 0
    out, err = capsys.readouterr()
    assert "did not report a revision" in out
    assert "nothing was recorded for provenance" in out
    assert "rerun" not in (out + err).lower()
    assert "Warning" not in (out + err)


def test_revision_from_local_dir_metadata(tmp_path):
    from kaine.setup import organ

    cmd = (
        "hf",
        "download",
        "kaineone/test",
        "model.gguf",
        "--local-dir",
        str(tmp_path / "weights"),
    )
    assert organ._revision_from_local_dir_metadata(cmd) is None

    metadata_dir = tmp_path / "weights" / ".cache" / "huggingface" / "download"
    metadata_dir.mkdir(parents=True)
    metadata_file = metadata_dir / "model.gguf.metadata"

    metadata_file.write_text("not-a-hash\n")
    assert organ._revision_from_local_dir_metadata(cmd) is None

    good_hash = "a" * 40
    metadata_file.write_text(f"{good_hash}\n")
    assert organ._revision_from_local_dir_metadata(cmd) == good_hash

    metadata_file.write_text(f"{good_hash}\nmore\n")
    assert organ._revision_from_local_dir_metadata(cmd) == good_hash


def test_run_organ_download_streams_output_and_extracts_revision(tmp_path, monkeypatch):
    from kaine.setup.organ import run_organ_download

    sha = "a" * 40
    hf_dir = tmp_path / "bin"
    hf_dir.mkdir()
    hf_script = hf_dir / "hf"
    hf_script.write_text(
        "#!/bin/sh\n"
        f"echo 'downloading /snapshots/{sha}/model.gguf progress'\n"
    )
    hf_script.chmod(0o755)
    monkeypatch.setenv("PATH", str(hf_dir) + os.pathsep + os.environ.get("PATH", ""))

    fake_artifact = type(
        "Ar",
        (),
        {
            "repo": "kaineone/test",
            "fmt": "gguf",
            "command": ("hf", "download", "kaineone/test", "model.gguf", "--local-dir", str(tmp_path / "dir")),
        },
    )()
    fake_plan = type("P", (), {"needed": True, "artifacts": [fake_artifact]})()

    seen: list[str] = []
    results = run_organ_download(fake_plan, consent=True, stream=lambda s: seen.append(s))
    assert any(sha in chunk for chunk in seen)
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].revision == sha


def test_pinned_job_route_behaviour(tmp_path, monkeypatch):
    app = _mk_app(tmp_path)

    harmless = JobSpec(
        name="harmless",
        title="Harmless job",
        argv=(sys.executable, "-c", "print('a')"),
        details="harmless test",
    )
    monkeypatch.setattr(
        "kaine.setup.web.job_specs.build_job_specs",
        lambda _c, _s, **_kw: [harmless],
    )

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        h = {"Host": "127.0.0.1:8000"}
        assert client.get("/jobs", headers=h).status_code == 403
        r = client.post(
            "/jobs/harmless/start",
            headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"},
            follow_redirects=False,
        )
        assert r.status_code == 403
        # Without a session the middleware rejects the request before routing.
        assert client.get("/jobs/harmless/start", headers=h).status_code == 403

    with _saved_client(app) as client:
        h = {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
        r1 = client.post("/jobs/harmless/start", headers=h, follow_redirects=False)
        assert r1.status_code == 303

        # With a session, GET on a POST-only start route is a method mismatch.
        assert client.get("/jobs/harmless/start", headers=h).status_code == 405

        r2 = client.post("/jobs/harmless/start", headers=h, follow_redirects=False)
        assert r2.status_code == 409

        r3 = client.post("/jobs/unknown/start", headers=h, follow_redirects=False)
        assert r3.status_code == 404


def test_build_job_specs_malformed_operator_toml_returns_no_nexus(tmp_path):
    shipped = tmp_path / "shipped.toml"
    shipped.write_text("[modules]\nlingua = false\n")
    operator = tmp_path / "operator.toml"
    operator.write_text("[[this is not valid toml")

    specs = build_job_specs(
        {"modules": {}},
        {},
        repo_root=tmp_path,
        shipped_config_path=shipped,
        operator_path=operator,
    )
    assert not any(s.name == "nexus" for s in specs)
