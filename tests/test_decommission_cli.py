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

from kaine import legacy_aliases
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
    (state_root / "self_model").mkdir(parents=True, exist_ok=True)
    (state_root / "self_model" / "self_model.json").write_text(
        json.dumps({"name": name, "drift_count": 0, "identity_history": []}),
        encoding="utf-8",
    )
    (state_root / "language").mkdir(parents=True, exist_ok=True)
    (state_root / "language" / "intent_expression.jsonl").write_text(
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
    client.xadd("affect.out", {"data": "1"})
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._open_bus_client",
        lambda: client,
    )


def _args(tmp_path, *, dry_run=False, eval_root=None, extra_config=""):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "kaine.toml"
    cfg_path.write_text(
        "# minimal config\n[research_submission]\nenabled = false\n"
        # The runtime default memory backend is Qdrant; these tests keep none.
        + (
            ""
            if "[episodic_memory]" in extra_config
            else '[episodic_memory]\nbackend = "inmemory"\n[social_cognition]\nbackend = "inmemory"\n'
        )
        + extra_config,
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
    assert not (tmp_path / "state" / "self_model").exists()
    assert "Entity state deleted" in out.getvalue()
    # Backup was written.
    assert list((tmp_path / "backups").glob("entity_*"))
    assert "cleared stream: affect.out" in out.getvalue()
    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    assert audit_path.exists()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["outcome"] == "deleted"
    assert "affect.out" in record["cleared_streams"]
    text = audit_path.read_text(encoding="utf-8")
    assert '{"x":1}' not in text
    assert "Kaine Nova" not in text


def test_guardian_notice_shown_on_every_path(tmp_path, monkeypatch):
    """The CAL Article 4.2(a) reminder is printed before the first prompt and in a dry run, and the audit notes it."""
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

    adapter_store = tmp_path / "state" / "sleep" / "adapters"
    adapter_store.mkdir(parents=True)
    own_job = jobs_dir / "j1"
    own_job.mkdir(parents=True)
    (own_job / "job.json").write_text(
        json.dumps(
            {
                "adapter_output_dir": str(adapter_store.resolve()),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "kaine.lifecycle.__main__.cancel_voice_alignment_jobs",
        lambda path, **kw: (["j1"], ["j1"]),
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
            extra_config=f'[sleep.voice_alignment]\ntrainer_jobs_dir = "{jobs_dir}"\n',
        ),
        input_fn=_scripted_input(answers),
        out=out,
        err=err,
    )
    assert rc == 3, out.getvalue() + err.getvalue()
    assert (tmp_path / "state" / "self_model").exists()
    assert "voice-alignment job is still training" in err.getvalue()


def test_qdrant_unreachable_fails_before_deletion(tmp_path, monkeypatch):
    """Qdrant that cannot be reached at deletion time fails the run with nothing deleted."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")

    class FailingQdrant:
        def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        def get_collections(self):
            raise RuntimeError("connection refused")

        def close(self):
            pass

    class WorkingQdrant:
        def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

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
    cli_args = _args(
        tmp_path,
        extra_config='[episodic_memory]\nbackend = "qdrant"\n[episodic_memory.qdrant]\nhost = "127.0.0.1"\nport = 1\n',
    )
    # Module toggles come from the operator overlay (the default profile
    # leaves the episodic memory module off).
    (tmp_path / "config" / "kaine.operator.toml").write_text(
        "[modules]\nepisodic_memory = true\n", encoding="utf-8"
    )
    rc = main(
        cli_args,
        input_fn=_scripted_input(answers),
        out=out,
        err=err,
    )
    assert rc == 8, out.getvalue() + err.getvalue()
    assert "Qdrant" in out.getvalue()
    assert (tmp_path / "state" / "self_model").exists()


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
    assert (tmp_path / "state" / "self_model").exists()


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
    assert (tmp_path / "state" / "self_model").exists()


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
    assert (tmp_path / "state" / "self_model").exists()  # nothing deleted


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
    assert (tmp_path / "state" / "self_model").exists()  # nothing deleted


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
    assert not (tmp_path / "state" / "self_model").exists()
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
    assert (tmp_path / "state" / "self_model").exists()  # nothing deleted
    assert "dry-run" in out.getvalue().lower()
    assert "redis stream: affect.out" in out.getvalue()


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
    for sub in ("self_model", "forks", "cycle"):
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


def test_location_split_printed_before_confirmation(tmp_path, monkeypatch):
    """The location split is printed before any confirmation prompt."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    answers = iter([
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ])

    def _input(prompt=""):
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
    split_idx = text.find("What decommission does with this entity's data:")
    prompt_idx = text.find("<<PROMPT>>")
    assert split_idx != -1
    assert prompt_idx != -1
    assert split_idx < prompt_idx
    assert "backed up, then deleted:" in text
    assert "- self_model:" in text
    assert "- language:" in text
    assert "kept by design:" in text


def test_incomplete_deletion_exits_8_and_is_audited(tmp_path, monkeypatch):
    """A permission error during deletion exits 8 and writes an incomplete outcome to the audit log."""
    import shutil

    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    out = io.StringIO()
    answers = [
        "I acknowledge the CAL welfare terms",  # ack
        "Kaine Nova",  # confirmation token (entity name)
    ]
    real_rmtree = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        if Path(path).name in legacy_aliases.name_forms("self_model"):
            raise PermissionError(path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("kaine.lifecycle.decommission.shutil.rmtree", guarded_rmtree)
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(answers),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 8, out.getvalue()
    assert "INCOMPLETE" in out.getvalue()
    assert (tmp_path / "state" / "self_model").exists()
    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    assert audit_path.exists()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["outcome"] == "incomplete"


def _snapshot_tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_module_off_unreachable_qdrant_refuses_before_anything(tmp_path, monkeypatch):
    """CLI refuses to run when Qdrant is unreachable; nothing is touched."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    before = _snapshot_tree(tmp_path / "state")
    monkeypatch.setattr("kaine.lifecycle.decommission._qdrant_client", lambda cfg: None)
    monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", lambda cfg: None)
    out = io.StringIO()
    err = io.StringIO()
    answers = iter([
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ])
    rc = main(
        _args(tmp_path, extra_config='[episodic_memory.qdrant]\nhost = "127.0.0.1"\nport = 1\n'),
        input_fn=lambda prompt="": next(answers),
        out=out,
        err=err,
    )
    assert rc == 8, out.getvalue()
    text = out.getvalue()
    assert "nothing was backed up or deleted" in text
    assert "127.0.0.1:1" in text
    assert "--qdrant-absent" in text
    assert _snapshot_tree(tmp_path / "state") == before
    assert not (tmp_path / "state" / "audit" / "decommission.jsonl").exists()
    backup_root = tmp_path / "backups"
    assert not backup_root.exists() or not any(backup_root.iterdir())


def test_qdrant_absent_flag_skips_qdrant_and_deletes(tmp_path, monkeypatch):
    """--qdrant-absent makes one CLI probe call and deletes state."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    calls_cli = []
    calls_lib = []

    def recording_cli_factory(cfg):
        calls_cli.append(cfg)
        return None

    def recording_lib_factory(cfg):
        calls_lib.append(cfg)
        return None

    monkeypatch.setattr("kaine.lifecycle.decommission._qdrant_client", recording_lib_factory)
    monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", recording_cli_factory)
    out = io.StringIO()
    err = io.StringIO()
    answers = iter([
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ])
    rc = main(
        _args(tmp_path, extra_config='[episodic_memory.qdrant]\nhost = "127.0.0.1"\nport = 1\n') + ["--qdrant-absent"],
        input_fn=lambda prompt="": next(answers),
        out=out,
        err=err,
    )
    assert rc == 0, out.getvalue() + err.getvalue()
    assert len(calls_cli) == 1
    assert calls_lib == []
    assert not (tmp_path / "state" / "self_model").exists()
    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    assert audit_path.exists()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["qdrant_absent_asserted"] is True
    assert record["outcome"] == "deleted"
    assert "Qdrant: skipped" in out.getvalue()


def test_qdrant_absent_does_not_override_a_module_that_is_on(tmp_path, monkeypatch):
    """--qdrant-absent is not allowed when a memory module is actually enabled."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    before = _snapshot_tree(tmp_path / "state")
    monkeypatch.setattr("kaine.lifecycle.decommission._qdrant_client", lambda cfg: None)
    monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", lambda cfg: None)
    out = io.StringIO()
    err = io.StringIO()
    base_args = _args(
        tmp_path,
        extra_config='[episodic_memory]\nbackend = "qdrant"\n[episodic_memory.qdrant]\nhost = "127.0.0.1"\nport = 1\n',
    )
    (tmp_path / "config" / "kaine.operator.toml").write_text(
        "[modules]\nepisodic_memory = true\n", encoding="utf-8"
    )
    answers = iter([
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ])
    rc = main(
        base_args + ["--qdrant-absent"],
        input_fn=lambda prompt="": next(answers),
        out=out,
        err=err,
    )
    assert rc == 8, out.getvalue()
    assert _snapshot_tree(tmp_path / "state") == before
    assert not (tmp_path / "state" / "audit" / "decommission.jsonl").exists()


def test_stuck_job_names_directory_and_trainer_stopped_proceeds(tmp_path, monkeypatch):
    """A stuck claimed job is reported; --trainer-stopped lets deletion proceed."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    jobs_dir = tmp_path / "state" / "jobs"
    job = jobs_dir / "job7"
    job.mkdir(parents=True)
    (job / "CLAIMED").write_text("")
    (job / "pairs.jsonl").write_text("SECRET pairs\n")

    adapter_store = tmp_path / "state" / "sleep" / "adapters"
    adapter_store.mkdir(parents=True)
    (job / "job.json").write_text(
        json.dumps(
            {
                "adapter_output_dir": str(adapter_store.resolve()),
            }
        ),
        encoding="utf-8",
    )

    from kaine.lifecycle.decommission_locations import cancel_voice_alignment_jobs as _real_cancel

    def _fast_cancel(path, **kw):
        kw["wait_s"] = 0.0
        kw["poll_s"] = 0.0
        return _real_cancel(path, **kw)

    monkeypatch.setattr("kaine.lifecycle.__main__.cancel_voice_alignment_jobs", _fast_cancel)

    extra_config = (
        f'[sleep.voice_alignment]\n'
        f'trainer_jobs_dir = "{jobs_dir.as_posix()}"\n'
        f'trainer_workdir = "{(tmp_path / "state" / "work").as_posix()}"\n'
    )
    args = _args(tmp_path, extra_config=extra_config)
    answers = [
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ]

    out = io.StringIO()
    err = io.StringIO()
    rc = main(args, input_fn=_scripted_input(answers), out=out, err=err)
    assert rc == 3, f"{out.getvalue()}\n{err.getvalue()}"
    err_text = err.getvalue()
    assert str(job) in err_text
    assert "--trainer-stopped" in err_text
    assert (tmp_path / "state" / "self_model").exists()

    out2 = io.StringIO()
    err2 = io.StringIO()
    rc2 = main(
        [a if a != str(tmp_path / "backups") else str(tmp_path / "backups2") for a in args]
        + ["--trainer-stopped"],
        input_fn=_scripted_input(answers),
        out=out2,
        err=err2,
    )
    assert rc2 == 0, f"{out2.getvalue()}\n{err2.getvalue()}"
    assert "claimed job not waited for" in out2.getvalue()

    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    assert audit_path.exists()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record.get("trainer_stopped_asserted") is True

    # The second run's own backup holds the stuck job's directory.
    backup_root = tmp_path / "backups2"
    assert backup_root.exists()
    found = False
    for entity_dir in backup_root.iterdir():
        if not entity_dir.is_dir():
            continue
        for path in entity_dir.rglob("*"):
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if "SECRET pairs" in text:
                    found = True
                    break
        if found:
            break
    assert found


def test_qdrant_failing_before_deletion_keeps_local_state(tmp_path, monkeypatch):
    """If Qdrant fails the final probe, local state is kept and the CLI exits 8."""
    import io


    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    model_path = tmp_path / "state" / "self_model" / "self_model.json"
    original_bytes = model_path.read_bytes()

    config_path = tmp_path / "config" / "kaine.operator.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[modules]\nepisodic_memory = true\n", encoding="utf-8")

    class Reachable:
        def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        def get_collections(self):
            class Collections:
                collections = []
            return Collections()

        def close(self):
            pass

    monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", lambda cfg: Reachable())
    monkeypatch.setattr("kaine.lifecycle.decommission._qdrant_client", lambda cfg: Reachable())

    out = io.StringIO()
    err = io.StringIO()
    answers = iter([
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ])
    call_count = 0

    def input_fn(prompt=""):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", lambda cfg: None)
        return next(answers)

    rc = main(
        _args(
            tmp_path,
            extra_config='[episodic_memory]\nbackend = "qdrant"\n[episodic_memory.qdrant]\nhost = "127.0.0.1"\nport = 1\n',
        ),
        input_fn=input_fn,
        out=out,
        err=err,
    )
    text = out.getvalue() + err.getvalue()
    assert rc == 8, text
    assert "just before deletion" in text
    assert model_path.exists()
    assert model_path.read_bytes() == original_bytes
    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    assert not audit_path.exists()


def test_qdrant_absent_refused_when_qdrant_answers(tmp_path, monkeypatch):
    """--qdrant-absent fails when Qdrant is actually reachable."""
    import io
    from pathlib import Path


    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")

    def snapshot_files(root):
        snapshot = {}
        for p in Path(root).rglob("*"):
            if p.is_file():
                snapshot[str(p.relative_to(root))] = p.read_bytes()
        return snapshot

    before = snapshot_files(tmp_path / "state")

    class Reachable:
        def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        def get_collections(self):
            class Collections:
                collections = []
            return Collections()

        def close(self):
            pass

    monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", lambda cfg: Reachable())
    monkeypatch.setattr("kaine.lifecycle.decommission._qdrant_client", lambda cfg: Reachable())

    out = io.StringIO()
    err = io.StringIO()
    answers = iter([
        "I acknowledge the CAL welfare terms",
        "Kaine Nova",
    ])
    rc = main(
        _args(
            tmp_path,
            extra_config='[episodic_memory.qdrant]\nhost = "127.0.0.1"\nport = 1\n',
        ) + ["--qdrant-absent"],
        input_fn=lambda prompt="": next(answers),
        out=out,
        err=err,
    )
    text = out.getvalue() + err.getvalue()
    assert rc == 8, text
    assert "Qdrant answered at 127.0.0.1:1" in text
    assert "run again without --qdrant-absent" in text
    after = snapshot_files(tmp_path / "state")
    assert before == after
    backups = tmp_path / "backups"
    entries = list(backups.iterdir()) if backups.exists() else []
    assert entries == []


def test_unattributable_pending_job_refuses_before_anything(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    job = tmp_path / "state" / "sleep" / "voice_align_jobs" / "q1"
    job.mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"adapter_output_dir": "out"}))
    (job / "READY").write_text("")
    (job / "pairs.jsonl").write_text("SECRET pairs\n")
    before = {p: p.read_bytes() for p in (tmp_path / "state").rglob("*") if p.is_file()}
    out = io.StringIO()
    err = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(["I acknowledge the CAL welfare terms", "Kaine Nova"]),
        out=out,
        err=err,
    )
    after = {p: p.read_bytes() for p in (tmp_path / "state").rglob("*") if p.is_file()}
    assert rc == 3
    assert str(job) in err.getvalue()
    assert "--keep-unattributed-jobs" in err.getvalue()
    assert after == before
    assert not (job / "CANCELLED").exists()
    assert not (tmp_path / "state" / "audit" / "decommission.jsonl").exists()
    backups = tmp_path / "backups"
    assert not backups.exists() or not any(backups.rglob("*"))


def test_keep_unattributed_jobs_flag_proceeds_and_records(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    job = tmp_path / "state" / "sleep" / "voice_align_jobs" / "q1"
    job.mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"adapter_output_dir": "out"}))
    (job / "READY").write_text("")
    (job / "pairs.jsonl").write_text("SECRET pairs\n")
    out = io.StringIO()
    err = io.StringIO()
    rc = main(
        _args(tmp_path) + ["--keep-unattributed-jobs"],
        input_fn=_scripted_input(["I acknowledge the CAL welfare terms", "Kaine Nova"]),
        out=out,
        err=err,
    )
    assert rc == 0, f"out={out.getvalue()!r} err={err.getvalue()!r}"
    assert job.exists()
    assert (job / "pairs.jsonl").read_text() == "SECRET pairs\n"
    audit_path = tmp_path / "state" / "audit" / "decommission.jsonl"
    assert audit_path.exists()
    lines = audit_path.read_text().strip().splitlines()
    record = json.loads(lines[-1])
    assert record["keep_unattributed_jobs_asserted"] is True
    assert "sleep/voice_align_jobs/q1" in record["unattributed_jobs_kept"]


def test_attributable_pending_job_is_still_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    adapters = tmp_path / "state" / "sleep" / "adapters"
    adapters.mkdir(parents=True)
    job = tmp_path / "state" / "sleep" / "voice_align_jobs" / "q1"
    job.mkdir(parents=True)
    (job / "job.json").write_text(
        json.dumps({"adapter_output_dir": str(adapters.resolve())})
    )
    (job / "READY").write_text("")
    (job / "pairs.jsonl").write_text("SECRET pairs\n")
    out = io.StringIO()
    err = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(["I acknowledge the CAL welfare terms", "Kaine Nova"]),
        out=out,
        err=err,
    )
    assert rc == 0, f"out={out.getvalue()!r} err={err.getvalue()!r}"
    assert not job.exists()
    backups = tmp_path / "backups"
    assert backups.exists()
    found = any(
        p.is_file() and b"SECRET pairs" in p.read_bytes()
        for p in backups.rglob("*")
    )
    assert found


def test_reprobe_stops_module_off_run_before_deletion(tmp_path, monkeypatch):
    """With the module off and an endpoint configured, the CLI re-probe just before deletion stops the run."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")

    class _Reachable:
        def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        def get_collections(self):
            return SimpleNamespace(collections=[])

        def close(self):
            pass

    # The deletion itself would still reach Qdrant through the library
    # factory, so only the CLI re-probe can stop this run.
    monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", lambda cfg: _Reachable())
    monkeypatch.setattr("kaine.lifecycle.decommission._qdrant_client", lambda cfg: _Reachable())
    _seed_state(tmp_path / "state")
    before = (tmp_path / "state" / "self_model" / "self_model.json").read_bytes()
    out = io.StringIO()
    err = io.StringIO()
    answers = iter(["I acknowledge the CAL welfare terms", "Kaine Nova"])
    first = [True]

    def _input_fn(prompt=""):
        if first[0]:
            first[0] = False
            # The first prompt comes after the backup: Qdrant now stops
            # answering the CLI's probe.
            monkeypatch.setattr("kaine.lifecycle.__main__._qdrant_client", lambda cfg: None)
        return next(answers, "")

    rc = main(
        _args(tmp_path, extra_config='[episodic_memory.qdrant]\nhost = "127.0.0.1"\nport = 1\n'),
        input_fn=_input_fn,
        out=out,
        err=err,
    )
    assert rc == 8, out.getvalue() + err.getvalue()
    assert "just before deletion" in out.getvalue()
    assert (tmp_path / "state" / "self_model" / "self_model.json").read_bytes() == before
    assert not (tmp_path / "state" / "audit" / "decommission.jsonl").exists()


def test_unattributable_claimed_job_refuses_before_anything(tmp_path, monkeypatch):
    """A claimed but unfinished job blocks decommission without changing state."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_state(tmp_path / "state")
    job = tmp_path / "state" / "sleep" / "voice_align_jobs" / "q1"
    job.mkdir(parents=True)
    (job / "job.json").write_text(json.dumps({"adapter_output_dir": "out"}))
    (job / "CLAIMED").write_text("")
    (job / "pairs.jsonl").write_text("SECRET pairs\n")
    before = {p: p.read_bytes() for p in (tmp_path / "state").rglob("*") if p.is_file()}
    out = io.StringIO()
    err = io.StringIO()
    rc = main(
        _args(tmp_path),
        input_fn=_scripted_input(["I acknowledge the CAL welfare terms", "Kaine Nova"]),
        out=out,
        err=err,
    )
    after = {p: p.read_bytes() for p in (tmp_path / "state").rglob("*") if p.is_file()}
    assert rc == 3
    assert str(job) in err.getvalue()
    assert "--keep-unattributed-jobs" in err.getvalue()
    assert after == before
    assert not (job / "CANCELLED").exists()
    assert not (tmp_path / "state" / "audit" / "decommission.jsonl").exists()
    backups = tmp_path / "backups"
    assert not backups.exists() or not any(backups.rglob("*"))


def test_rerun_names_the_earlier_qdrant_export(tmp_path, monkeypatch):
    """An earlier incomplete run is named as the source Qdrant export backup."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    earlier_backup = "/backups/entity_Kaine_Nova_20261013T120000Z"

    run1 = tmp_path / "run1"
    _seed_state(run1 / "state")
    audit1 = run1 / "state" / "audit"
    audit1.mkdir(parents=True)
    (audit1 / "decommission.jsonl").write_text(
        json.dumps(
            {
                "outcome": "incomplete",
                "dropped_collections": ["episodic_memory_episodic"],
                "backup_path": earlier_backup,
            }
        )
        + "\n"
    )
    out1 = io.StringIO()
    err1 = io.StringIO()
    rc1 = main(
        _args(run1),
        input_fn=_scripted_input(["I acknowledge the CAL welfare terms", "Kaine Nova"]),
        out=out1,
        err=err1,
    )
    assert rc1 == 0, f"rc={rc1}\nout={out1.getvalue()}\nerr={err1.getvalue()}"
    assert "An earlier run already dropped this entity's Qdrant collections" in out1.getvalue()
    assert earlier_backup in out1.getvalue()
    lines1 = (audit1 / "decommission.jsonl").read_text().strip().split("\n")
    assert len(lines1) == 2
    assert json.loads(lines1[1])["earlier_qdrant_export_backup"] == earlier_backup

    run2 = tmp_path / "run2"
    _seed_state(run2 / "state")
    audit2 = run2 / "state" / "audit"
    audit2.mkdir(parents=True)
    (audit2 / "decommission.jsonl").write_text(
        json.dumps(
            {
                "outcome": "deleted",
                "dropped_collections": ["episodic_memory_episodic"],
                "backup_path": earlier_backup,
            }
        )
        + "\n"
    )
    out2 = io.StringIO()
    err2 = io.StringIO()
    rc2 = main(
        _args(run2),
        input_fn=_scripted_input(["I acknowledge the CAL welfare terms", "Kaine Nova"]),
        out=out2,
        err=err2,
    )
    assert rc2 == 0, f"rc={rc2}\nout={out2.getvalue()}\nerr={err2.getvalue()}"
    assert "An earlier run already dropped this entity's Qdrant collections" not in out2.getvalue()
    lines2 = (audit2 / "decommission.jsonl").read_text().strip().split("\n")
    assert len(lines2) == 2
    assert json.loads(lines2[1])["earlier_qdrant_export_backup"] is None


def _old_key(new_key: str) -> str:
    """The module's directory name before the rename, from the table."""
    from kaine import legacy_names

    return next(k for k, e in legacy_names.MODULES.items() if e["new_key"] == new_key)


def _seed_old_state(state_root: Path) -> None:
    """A state tree last written before the stored-name rename."""
    old_self_model = state_root / _old_key("self_model")
    old_self_model.mkdir(parents=True, exist_ok=True)
    (old_self_model / "self_model.json").write_text(
        json.dumps({"name": "Kaine Nova", "drift_count": 0, "identity_history": []}),
        encoding="utf-8",
    )
    old_language = state_root / _old_key("language")
    old_language.mkdir(parents=True, exist_ok=True)
    (old_language / "intent_expression.jsonl").write_text('{"x":1}\n', encoding="utf-8")


def test_an_old_tree_is_moved_before_decommission_reads_it(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_old_state(tmp_path / "state")
    eval_root = _make_diverged(tmp_path)
    out = io.StringIO()
    rc = main(
        _args(tmp_path, eval_root=eval_root),
        input_fn=_scripted_input(["decline"]),
        out=out,
        err=io.StringIO(),
    )
    assert rc == 5
    assert "state tree moved to the current names" in out.getvalue()
    assert (tmp_path / "state" / "self_model" / "self_model.json").is_file()
    assert not (tmp_path / "state" / _old_key("self_model")).exists()


def test_a_dry_run_refuses_an_old_tree_and_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    _seed_old_state(tmp_path / "state")
    before = _snapshot_tree(tmp_path / "state")
    err = io.StringIO()
    rc = main(
        _args(tmp_path, dry_run=True),
        input_fn=_scripted_input([]),
        out=io.StringIO(),
        err=err,
    )
    assert rc == 6
    assert "before the module rename" in err.getvalue()
    assert _snapshot_tree(tmp_path / "state") == before
