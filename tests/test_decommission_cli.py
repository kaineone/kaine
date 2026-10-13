# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>



from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import redis

from kaine.bus.client import CYCLE_CLIENT_NAME
from kaine.bus.errors import BusConfigError
from kaine.lifecycle.__main__ import (
    _bus_shows_live_entity,
    main,
)
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    Ledger,
    save_ledger,
)
from kaine.lifecycle.liveness import argv_is_cycle as _argv_is_cycle
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    set_state_encryptor,
)


class _FakeClient:
    def __init__(
        self,
        entries=None,
        clients=None,
        exc=None,
        ping_exc=None,
        list_exc=None,
    ):
        self.entries = entries or []
        self.clients = clients or []
        self.exc = exc
        self.ping_exc = ping_exc
        self.list_exc = list_exc

    def ping(self):
        if self.ping_exc:
            raise self.ping_exc

    def client_list(self):
        if self.list_exc:
            raise self.list_exc
        return self.clients

    def xrevrange(self, name, count=1):
        if self.exc:
            raise self.exc
        return self.entries

    def close(self):
        pass


def _seed_state(state_root: Path, *, name: str = "Kaine Nova") -> None:
    (state_root / "eidolon").mkdir(parents=True, exist_ok=True)
    (state_root / "eidolon" / "self_model.json").write_text(
        json.dumps({"name": name, "drift_count": 0, "identity_history": []}),
        encoding="utf-8",
    )
    (state_root / "lingua").mkdir(parents=True, exist_ok=True)
    (state_root / "lingua" / "intent_expression.jsonl").write_text(
        '{"x":1}\n', encoding="utf-8"
    )


def _scripted_input(answers):
    it = iter(answers)

    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            return ""

    return _input


pytest = __import__("pytest")


@pytest.fixture(autouse=True)
def _isolated_operator_overlay(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "kaine.config.OPERATOR_CONFIG_PATH",
        tmp_path / "config" / "kaine.operator.toml",
    )


@pytest.fixture(autouse=True)
def _hermetic_liveness_signals(monkeypatch):
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._bus_shows_live_entity",
        lambda config: (False, "test: no bus"),
    )
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._cycle_process_running",
        lambda: False,
    )


@pytest.fixture(autouse=True)
def _disabled_state_encryption():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _hermetic_bus_client(monkeypatch):
    """Provide an isolated in-memory Redis client for decommission tests."""
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis()
    client.xadd("thymos.out", {"data": "1"})
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._open_bus_client",
        lambda: client,
    )


def _args(tmp_path, *, dry_run=False, eval_root=None, extra_config=""):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "kaine.toml"
    cfg_path.write_text(
        "# minimal config\n[research_submission]\nenabled = false\n" + extra_config,
        encoding="utf-8",
    )
    a = [
        "--state-root",
        str(tmp_path / "state"),
        "--fork-root",
        str(tmp_path / "forks"),
        "--eval-root",
        str(eval_root or (tmp_path / "data" / "evaluation")),
        "--out-root",
        str(tmp_path / "backups"),
        "--config",
        str(cfg_path),
    ]
    if dry_run:
        a.append("--dry-run")
    return a


def test_operator_present_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", raising=False)
    err = io.StringIO()
    rc = main(_args(tmp_path), input_fn=_scripted_input([]), out=io.StringIO(), err=err)
    assert rc == 2
    assert "operator must be present" in err.getvalue()
    assert "4.2" in err.getvalue()


def test_running_cycle_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    runtime = tmp_path / "state" / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    import os

    runtime.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    err = io.StringIO()
    rc = main(_args(tmp_path), input_fn=_scripted_input([]), out=io.StringIO(), err=err)
    assert rc == 3
    assert "running" in err.getvalue().lower()


def test_non_diverged_ack_path_deletes(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",  # ack
        "Kaine Nova",  # confirmation token (entity name)
    ]
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(answers),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    assert not (tmp_path / "state" / "eidolon").exists()
    assert "Entity state deleted" in out.getvalue()
    # Backup was written.
    assert list((tmp_path / "backups").glob("entity_*"))
    assert "cleared stream: thymos.out" in out.getvalue()
    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    assert audit_path.exists()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["outcome"] == "deleted"
    assert "thymos.out" in record["cleared_streams"]
    text = audit_path.read_text(encoding="utf-8")
    assert '{"x":1}' not in text
    assert "Kaine Nova" not in text


def test_guardian_notice_shown_on_every_path(tmp_path, monkeypatch):
    """The CAL 4.2(a) reminder is printed before the first prompt and in a dry run, and the audit notes it."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    answers = iter([
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ])

    def _input(prompt=""):
        # Mark each prompt in the output so the test can see what was shown before it.
        out.write("<<PROMPT>>")
        return next(answers, "")

    rc = main(
        _args(tmp_path),
        input_fn=_input,
        out=out,
        err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    text = out.getvalue()
    notice_idx = text.find("CAL Article 4.2(a)")
    final_idx = text.find("<<PROMPT>>")
    assert notice_idx != -1
    assert final_idx != -1
    assert notice_idx < final_idx
    assert "Article 7.0" in text

    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    record = json.loads(audit_path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert record["guardian_notice_reminder"] == "shown"

    dry_root = tmp_path / "dry"
    _seed_state(dry_root / "state")
    out2 = io.StringIO()
    rc2 = main(
        _args(dry_root, dry_run=True),
        input_fn=_scripted_input([]),
        out=out2,
        err=io.StringIO(),
    )
    assert rc2 == 0, out2.getvalue()
    assert "CAL Article 4.2(a)" in out2.getvalue()
    assert "Article 7.0" in out2.getvalue()


def test_running_voice_alignment_job_refuses(tmp_path, monkeypatch):
    """A voice-alignment job still training stops decommission before anything is deleted."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    monkeypatch.setattr(
        "kaine.lifecycle.__main__.cancel_voice_alignment_jobs",
        lambda path: (["j1"], ["j1"]),
    )

    out = io.StringIO()
    err = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ]
    rc = main(
        _args(
            tmp_path,
            extra_config=f'[hypnos.voice_alignment]\ntrainer_jobs_dir = "{jobs_dir}"\n',
        ),
        input_fn=_scripted_input(answers),
        out=out,
        err=err,
    )
    assert rc == 3, out.getvalue() + err.getvalue()
    assert (tmp_path / "state" / "eidolon").exists()
    assert "voice-alignment job is still training" in err.getvalue()


def test_qdrant_unreachable_fails_before_deletion(tmp_path, monkeypatch):
    """Qdrant that cannot be reached at deletion time fails the run with nothing deleted."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")

    class FailingQdrant:
        def get_collections(self):
            raise RuntimeError("connection refused")

        def close(self):
            pass

    class WorkingQdrant:
        def get_collections(self):
            return SimpleNamespace(collections=[])

        def close(self):
            pass

    monkeypatch.setattr(
        "kaine.lifecycle.__main__._qdrant_client",
        lambda cfg: FailingQdrant(),
    )
    monkeypatch.setattr(
        "kaine.lifecycle.decommission._qdrant_client",
        lambda cfg: WorkingQdrant(),
    )

    out = io.StringIO()
    err = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ]
    rc = main(
        _args(
            tmp_path,
            extra_config='[mnemos]\nbackend = "qdrant"\n[mnemos.qdrant]\nhost = "127.0.0.1"\nport = 1\n',
        ),
        input_fn=_scripted_input(answers),
        out=out,
        err=err,
    )
    assert rc == 8, out.getvalue() + err.getvalue()
    assert "Qdrant" in out.getvalue()
    assert (tmp_path / "state" / "eidolon").exists()


def test_bus_auth_failure_deletes_nothing(tmp_path, monkeypatch):
    """Bus authentication failure aborts deletion and leaves entity state intact."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")

    class FailingClient:
        def ping(self):
            raise redis.exceptions.AuthenticationError("bad")

        def type(self, name):
            return b"none"

        def unlink(self, *names):
            return 0

        def close(self):
            pass

    monkeypatch.setattr(
        "kaine.lifecycle.__main__._open_bus_client",
        lambda: FailingClient(),
    )

    out = io.StringIO()
    err = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ]
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(answers),
        out=out,
        err=err,
    )
    output = out.getvalue() + err.getvalue()
    assert rc == 8, output
    assert "FAILED" in output
    assert (tmp_path / "state" / "eidolon").exists()


def test_missing_bus_config_is_a_configuration_error(tmp_path, monkeypatch):
    """Missing or malformed bus configuration is a configuration error, not a reachability failure."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")

    def _raise_bus_config_error():
        raise BusConfigError("no password")

    monkeypatch.setattr(
        "kaine.lifecycle.__main__._open_bus_client",
        _raise_bus_config_error,
    )

    out = io.StringIO()
    err = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ]
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(answers),
        out=out,
        err=err,
    )
    assert rc == 6, out.getvalue() + err.getvalue()
    assert (tmp_path / "state" / "eidolon").exists()


def test_non_diverged_wrong_ack_aborts(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(["nope"]),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 5
    assert (tmp_path / "state" / "eidolon").exists()  # nothing deleted


def _make_diverged(tmp_path):
    state_root = tmp_path / "state"
    paths = IndividuationPaths(state_root / "individuation")
    save_ledger(
        paths,
        Ledger(
            reference_id="diverged-cli-latch",
            individuated=True,
            looks_completed=1,
        ),
    )
    return tmp_path / "data" / "evaluation"


def test_diverged_declines_continuity_exit_5(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    eval_root = _make_diverged(tmp_path)
    out = io.StringIO()
    rc = main(
        _args(tmp_path, eval_root=eval_root),
        input_fn=_scripted_input(["decline"]),  # decline the continuity note
        out=out,
        err=io.StringIO(),
    )
    assert rc == 5
    assert (tmp_path / "state" / "eidolon").exists()  # nothing deleted


def test_diverged_full_path_deletes(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    eval_root = _make_diverged(tmp_path)
    out = io.StringIO()
    answers = [
        "It wished to persist and keep its memories.",  # continuity note
        "n",  # do not send transfer email
        "I have preserved and will arrange safekeeping for this entity",  # guardian ack
        "Kaine Nova",  # confirmation token
    ]
    rc = main(
        _args(tmp_path, eval_root=eval_root),
        input_fn=_scripted_input(answers),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    assert not (tmp_path / "state" / "eidolon").exists()
    # S3: the continuity note is recorded in a SEPARATE sidecar, never the
    # plaintext manifest (encryption is disabled here so it is honest plaintext).
    manifest = next((tmp_path / "backups").glob("entity_*/manifest.json"))
    data = json.loads(manifest.read_text())
    assert "continuity_note" not in data
    cdata = json.loads((manifest.parent / "continuity.json").read_text())
    assert "persist" in (cdata.get("continuity_note") or "")


def test_dry_run_deletes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ]
    rc = main(
        _args(tmp_path, dry_run=True),
        input_fn=_scripted_input(answers),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 0, out.getvalue()
    assert (tmp_path / "state" / "eidolon").exists()  # nothing deleted
    assert "dry-run" in out.getvalue().lower()
    assert "redis stream: thymos.out" in out.getvalue()


def test_bus_live_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._bus_shows_live_entity",
        lambda config: (True, "workspace:broadcast last broadcast 1 s ago"),
    )
    err = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input([]),
        out=io.StringIO(),
        err=err,
    )
    assert rc == 3
    assert "workspace:broadcast" in err.getvalue()


def test_bus_unreachable_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._bus_shows_live_entity",
        lambda config: (None, "bus unreachable (ConnectionError)"),
    )
    err = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input([]),
        out=io.StringIO(),
        err=err,
    )
    assert rc == 3
    assert "cannot confirm" in err.getvalue().lower()
    assert "Start the bus" in err.getvalue()


def test_cycle_process_running_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._cycle_process_running",
        lambda: True,
    )
    err = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input([]),
        out=io.StringIO(),
        err=err,
    )
    assert rc == 3
    assert "kaine.cycle" in err.getvalue().lower()


def test_empty_state_root_refuses_no_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    state_root = tmp_path / "empty_state"
    state_root.mkdir(parents=True, exist_ok=True)
    out_root = tmp_path / "backups"
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "kaine.toml"
    cfg_path.write_text(
        "# minimal config\n[research_submission]\nenabled = false\n",
        encoding="utf-8",
    )
    args = [
        "--state-root",
        str(state_root),
        "--fork-root",
        str(tmp_path / "forks"),
        "--eval-root",
        str(tmp_path / "data" / "evaluation"),
        "--out-root",
        str(out_root),
        "--config",
        str(cfg_path),
    ]
    err = io.StringIO()
    rc = main(args, input_fn=_scripted_input([]), out=io.StringIO(), err=err)
    assert rc == 7
    assert "no entity state found" in err.getvalue().lower()
    # Nothing was backed up: the backup root was never created or is empty.
    assert not out_root.exists() or not any(out_root.iterdir())


def test_bad_config_refuses_before_gate2(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "kaine.toml"
    cfg_path.write_text("this is not toml = [", encoding="utf-8")
    state_root = tmp_path / "state"
    runtime = state_root / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(json.dumps({"pid": 12345}), encoding="utf-8")
    now = time.time()
    os.utime(runtime, (now, now))
    err = io.StringIO()
    rc = main(
        [
            "--state-root",
            str(state_root),
            "--fork-root",
            str(tmp_path / "forks"),
            "--eval-root",
            str(tmp_path / "data" / "evaluation"),
            "--out-root",
            str(tmp_path / "backups"),
            "--config",
            str(cfg_path),
        ],
        input_fn=_scripted_input([]),
        out=io.StringIO(),
        err=err,
    )
    assert rc == 6
    assert "configuration error" in err.getvalue().lower()


def test_bus_probe_fresh_broadcast_reports_live(monkeypatch):
    fresh_id = f"{int(time.time() * 1000)}-0"
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda url, **kwargs: _FakeClient([(fresh_id, {})]),
    )
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config",
        lambda **kw: SimpleNamespace(url="redis://fake"),
    )
    live, detail = _bus_shows_live_entity({})
    assert live is True
    assert "last broadcast" in detail


def test_bus_probe_stale_broadcast_reports_not_live(monkeypatch):
    old_id = f"{int((time.time() - 60) * 1000)}-0"
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda url, **kwargs: _FakeClient([(old_id, {})]),
    )
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config",
        lambda **kw: SimpleNamespace(url="redis://fake"),
    )
    live, detail = _bus_shows_live_entity({})
    assert live is False
    assert "broadcast" in detail


def test_bus_probe_unreachable_reports_unknown(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda url, **kwargs: _FakeClient(ping_exc=ConnectionError("boom")),
    )
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config",
        lambda **kw: SimpleNamespace(url="redis://fake"),
    )
    live, detail = _bus_shows_live_entity({})
    assert live is None
    assert "bus unreachable (ConnectionError)" in detail


def test_bus_probe_named_client_reports_live(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda url, **kwargs: _FakeClient(
            entries=[(f"{int(time.time() * 1000) - 120000}-0", {})],
            clients=[{"name": CYCLE_CLIENT_NAME}],
        ),
    )
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config",
        lambda **kw: SimpleNamespace(url="redis://fake"),
    )
    live, detail = _bus_shows_live_entity({})
    assert live is True
    assert "connected to the bus" in detail


def test_bus_probe_connection_refused_reports_not_running(monkeypatch):
    refused = ConnectionRefusedError()
    err = redis.exceptions.ConnectionError("refused")
    err.__cause__ = refused
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda url, **kwargs: _FakeClient(ping_exc=err),
    )
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config",
        lambda **kw: SimpleNamespace(url="redis://fake"),
    )
    live, detail = _bus_shows_live_entity({})
    assert live is False
    assert "not running (connection refused)" in detail


def test_bus_probe_timeout_reports_unknown(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda url, **kwargs: _FakeClient(
            ping_exc=redis.exceptions.TimeoutError("timeout")
        ),
    )
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config",
        lambda **kw: SimpleNamespace(url="redis://fake"),
    )
    live, detail = _bus_shows_live_entity({})
    assert live is None
    assert "bus unreachable (TimeoutError)" in detail


def test_bus_probe_missing_config_reports_unknown(monkeypatch):
    def _bad_load(**kw):
        raise BusConfigError("no Redis password found")

    monkeypatch.setattr("kaine.bus.config.load_bus_config", _bad_load)
    live, detail = _bus_shows_live_entity({})
    assert live is None
    assert "no Redis password found" in detail


def test_bus_probe_list_clients_error_reports_unknown(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda url, **kwargs: _FakeClient(
            list_exc=redis.exceptions.ResponseError("NOPERM")
        ),
    )
    monkeypatch.setattr(
        "kaine.bus.config.load_bus_config",
        lambda **kw: SimpleNamespace(url="redis://fake"),
    )
    live, detail = _bus_shows_live_entity({})
    assert live is None
    assert "cannot list bus clients (ResponseError)" in detail


@pytest.mark.parametrize(
    "args,expected",
    [
        ([b"python", b"-m", b"kaine.cycle"], True),
        ([b"python", b"-m", b"kaine.cycle.__main__"], True),
        ([b"python", b"-mkaine.cycle"], True),
        ([b"python", b"-mkaine.cycle.x"], True),
        ([b"python", b"/app/kaine/cycle/__main__.py"], True),
        ([b"python", b"-m", b"kaine.cyclefoo"], False),
        ([b"python", b"-m", b"kaine.lifecycle"], False),
    ],
)
def test_argv_is_cycle(args, expected):
    assert _argv_is_cycle(args) is expected


def test_empty_subtree_dirs_only_refuses_decommission(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    state_root = tmp_path / "state"
    for sub in ("eidolon", "forks", "cycle"):
        (state_root / sub).mkdir(parents=True, exist_ok=True)
    out_root = tmp_path / "backups"
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "kaine.toml"
    cfg_path.write_text(
        "# minimal config\n[research_submission]\nenabled = false\n",
        encoding="utf-8",
    )
    args = [
        "--state-root",
        str(state_root),
        "--fork-root",
        str(tmp_path / "forks"),
        "--eval-root",
        str(tmp_path / "data" / "evaluation"),
        "--out-root",
        str(out_root),
        "--config",
        str(cfg_path),
    ]
    err = io.StringIO()
    rc = main(args, input_fn=_scripted_input([]), out=io.StringIO(), err=err)
    assert rc == 7
    assert "no entity state found" in err.getvalue().lower()
    assert not out_root.exists() or not any(out_root.iterdir())
