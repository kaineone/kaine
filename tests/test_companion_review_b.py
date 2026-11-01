# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Second review B of the companion-stream mechanism: bound companion
entries, host-run decommission and preboot, the boot and shutdown flush, the
wider spoken-text split, the volatile service's shape and its boot check."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.schema import validate_event
from tests._companion import attach_spoken_test_volatile, attach_test_volatile
from tests.test_latent_content_privacy import _ConfigClient

HEARD = "come and see this right now"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    b = AsyncBus(BusConfig(password="x", audit_required=False), client=fakeredis.FakeRedis(decode_responses=True))
    yield b
    await b.close()


def _now_ev(source, type_, payload):
    return validate_event(source=source, type=type_, payload=payload, salience=0.5,
                          timestamp=datetime.now(timezone.utc))


# --- F3: a companion entry is bound to the main entry that names it ----------


@pytest.mark.asyncio
async def test_forged_reference_does_not_cross_join(bus):
    """The reviewer's probe: a raw language.external entry naming an
    audition.out companion entry must not join the heard words."""
    attach_spoken_test_volatile(bus)
    await bus.publish(_now_ev("audition", "audition.transcription", {"text": HEARD, "source_label": "live_mic"}))
    (_eid, heard), = await bus.read("audition.out")
    forged = {
        "source": "language", "type": "external_speech", "salience": "0.5",
        "timestamp": datetime.now(timezone.utc).isoformat(), "causal_parent": "",
        "payload": json.dumps({"mode": "external"}), "companion": heard.companion,
    }
    await bus.client.xadd("language.external", forged)
    (_eid, event), = await bus.read("language.external")
    assert event.companion == heard.companion
    for stream in (None, "language.external"):
        joined, ok = await bus.join_companion(event, stream=stream)
        assert ok is False and "text" not in joined.payload
    # The genuine entry still joins, and only for its own stream.
    joined, ok = await bus.join_companion(heard, stream="audition.out")
    assert ok and joined.payload["text"] == HEARD
    _joined, ok = await bus.join_companion(heard, stream="language.external")
    assert ok is False


@pytest.mark.asyncio
async def test_same_source_and_type_on_another_stream_does_not_join(bus):
    attach_spoken_test_volatile(bus)
    original = _now_ev("audition", "audition.transcription", {"text": HEARD})
    await bus.publish(original)
    (_eid, heard), = await bus.read("audition.out")
    copy = heard.model_copy(update={"timestamp": heard.timestamp.replace(microsecond=(heard.timestamp.microsecond + 1) % 10**6)})
    assert (await bus.join_companion(copy))[1] is False  # a different timestamp
    assert (await bus.join_companion(heard, stream="embodiment.out"))[1] is False


def test_companion_reference_needs_the_suffix_and_a_full_id():
    """B19."""
    from kaine.bus.companion import parse_companion_ref

    assert parse_companion_ref("audition.out.companion:1-0") == ("audition.out.companion", "1-0")
    for bad in ("audition.out:1-0", "audition.out.companion:1793557488988", ".companion:1-0",
                "audition.out.companion:1-x", "audition.out.companion:", None, 5):
        assert parse_companion_ref(bad) is None


@pytest.mark.asyncio
async def test_failed_write_log_holds_no_exception_text(bus, caplog):
    """B27: an exception that quotes the words never reaches the log."""
    volatile = attach_spoken_test_volatile(bus)

    async def refuse(stream, values, **kw):
        raise ConnectionError(f"could not write {values!r}")

    volatile.add = refuse
    with caplog.at_level("DEBUG"):
        await bus.publish(_now_ev("audition", "audition.transcription", {"text": HEARD}))
    text = " ".join(r.getMessage() for r in caplog.records) + " ".join(
        str(r.exc_text or "") for r in caplog.records)
    assert HEARD not in text and "could not write" not in text
    assert any("ConnectionError" in r.getMessage() for r in caplog.records)


# --- F4: companion content never outlives the run -----------------------------


@pytest.mark.asyncio
async def test_companion_streams_flushed_on_close_and_by_the_boot_flush(bus):
    volatile = attach_spoken_test_volatile(bus)
    await bus.publish(_now_ev("audition", "audition.transcription", {"text": HEARD}))
    assert await volatile.client.xlen("audition.out.companion") == 1
    # A boot after a crash: the stale stream is flushed before anything runs.
    assert await bus.flush_companion_streams() == 1
    assert await volatile.client.xlen("audition.out.companion") == 0
    await bus.publish(_now_ev("audition", "audition.transcription", {"text": HEARD}))
    client = volatile.client
    await bus.close()
    assert await client.exists("audition.out.companion") == 0


@pytest.mark.asyncio
async def test_no_flush_without_declarations(bus):
    assert await bus.flush_companion_streams() == 0  # no instance
    volatile = attach_test_volatile(bus)  # an instance, nothing declared
    await volatile.client.xadd("other.companion", {"values": "{}"})
    assert await bus.flush_companion_streams() == 0
    assert await volatile.client.xlen("other.companion") == 1


def test_cycle_flushes_before_modules_start():
    import inspect

    import kaine.cycle.__main__ as cyc

    source = inspect.getsource(cyc._phase_registry)
    assert source.index("declare_and_check(") < source.index("flush_companion_streams") < source.index(
        "await module.initialize()")


# --- B31: the cycle attaches the volatile instance ----------------------------


def test_cycle_attaches_the_volatile_instance(monkeypatch):
    import kaine.cycle.__main__ as cyc

    class Bus:
        volatile = None

        def attach_volatile(self, v):
            self.volatile = v

    monkeypatch.delenv("KAINE_REDIS_VOLATILE_URL", raising=False)
    monkeypatch.setattr("kaine.bus.volatile.resolve_volatile_url", lambda *a, **k: None)
    b = Bus()
    assert cyc._attach_volatile(b, {}) is False and b.volatile is None
    monkeypatch.setattr("kaine.bus.volatile.resolve_volatile_url", lambda *a, **k: "redis://:pw@kaine-redis-volatile:6379/0")
    monkeypatch.setattr("kaine.boot.companions.resolve_volatile_url", lambda *a, **k: "redis://:pw@kaine-redis-volatile:6379/0")
    assert cyc._attach_volatile(b, {"privacy": {"companion_stream_maxlen": 500}}) is True
    assert b.volatile is not None and b.volatile.companion_stream_maxlen == 500


# --- F2: host-run decommission and preboot ------------------------------------


class _Host:
    ABSENT, STOPPED, RUNNING, UNKNOWN = "absent", "stopped", "running", "unknown"

    def __init__(self, state, flush_ok=True):
        self.state, self.flush_ok, self.calls = state, flush_ok, []

    def container_state(self):
        return self.state

    def redis_cli(self, *args):
        self.calls.append(args)
        return (self.flush_ok, "OK" if self.flush_ok else "")


def test_decommission_flushes_the_compose_instance_from_the_host():
    from kaine.lifecycle.decommission import flush_volatile_bus

    assert flush_volatile_bus(None, dry_run=False, host=_Host("absent")) == ("not configured", None)
    assert flush_volatile_bus(None, dry_run=False, host=_Host("stopped"))[1] is None
    h = _Host("running")
    assert flush_volatile_bus(None, dry_run=True, host=h) == ("would flush (docker exec)", None) and h.calls == []
    assert flush_volatile_bus(None, dry_run=False, host=h) == ("flushed (docker exec)", None)
    assert h.calls == [("FLUSHALL",)]
    state, error = flush_volatile_bus(None, dry_run=False, host=_Host("running", flush_ok=False))
    assert state == "failed" and "could not be flushed" in error
    state, error = flush_volatile_bus(None, dry_run=False, host=_Host("unknown"))
    assert error and "not flushed" in error


def test_container_state_reads_docker():
    import subprocess

    from kaine.bus import volatile_host

    def run(out="", err="", rc=0):
        return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout=out, stderr=err)

    assert volatile_host.container_state(run=run(out="true\n"), docker="docker") == "running"
    assert volatile_host.container_state(run=run(out="false\n"), docker="docker") == "stopped"
    assert volatile_host.container_state(run=run(err="Error: No such object: x", rc=1), docker="docker") == "absent"
    assert volatile_host.container_state(run=run(err="permission denied", rc=1), docker="docker") == "unknown"
    assert volatile_host.container_state(docker="") == "absent"
    seen = []

    def capture(cmd, **k):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")

    assert volatile_host.redis_cli("FLUSHALL", run=capture, docker="docker") == (True, "OK")
    assert seen[0][:3] == ["docker", "exec", "kaine-redis-volatile"]
    assert "KAINE_REDIS_VOLATILE_PASSWORD" in seen[0][-1] and "pw" not in seen[0]


@pytest.mark.asyncio
async def test_preboot_on_the_host_reports_honestly():
    from kaine import preboot

    (row,) = await preboot.check_volatile_bus({}, host_state=lambda: "running")
    assert row.status == preboot.SKIP and "checks it at boot" in row.detail
    (row,) = await preboot.check_volatile_bus({}, host_state=lambda: "absent")
    assert row.status == preboot.FAIL and "absent" in row.detail


# --- F5: words under `about` and in the keys of a heard-input event ----------


def test_heard_about_is_diverted():
    from kaine.faithful.external_input import split_spoken_payload

    main, diverted = split_spoken_payload("intent.speak", {"about": HEARD, "about_kind": "heard", "kind": "speak"})
    assert main == {"about_kind": "heard", "kind": "speak"}
    assert [p for p, _v, _i in diverted] == [("about",)]
    own = {"about": "my rest", "about_kind": "felt"}
    assert split_spoken_payload("intent.speak", own)[0] is own


def test_mapping_keys_of_a_heard_input_event_are_diverted():
    from kaine.faithful.external_input import split_spoken_payload

    payload = {"text": HEARD, "word_confidence": {"secretword": 0.7}, "spans": [[0, 4]],
               "items": [{"w": 1}], "latency_ms": 3.0, "ok": True, "source_label": "live_mic"}
    main, diverted = split_spoken_payload("audition.transcription", payload)
    assert "secretword" not in json.dumps(main)
    assert set(main) == {"latency_ms", "ok", "source_label", "text_chars", "text_words"}
    assert {p for p, _v, _i in diverted} == {("text",), ("word_confidence",), ("spans",), ("items",)}
    assert main["latency_ms"] == 3.0 and main["ok"] is True and main["source_label"] == "live_mic"


@pytest.mark.asyncio
async def test_heard_about_never_reaches_the_intent_stream(bus):
    await bus.publish(_now_ev("action_selection", "intent.speak", {"about": HEARD, "about_kind": "heard"}))
    raw = json.dumps(await bus.client.xrange("action_selection.out"))
    assert HEARD not in raw


# --- F6: the volatile service's shape and its boot check ----------------------


def _service():
    import yaml

    doc = yaml.safe_load((REPO / "compose" / "kaine.yml").read_text())
    return doc["services"]["kaine-redis-volatile"]


def test_volatile_service_shape():
    svc = _service()
    assert "ports" not in svc
    assert "volumes" not in svc
    assert svc.get("tmpfs") == ["/data"]
    cmd = svc["command"]
    assert cmd[cmd.index("--appendonly") + 1] == "no"
    assert cmd[cmd.index("--save") + 1] == ""
    assert "--requirepass" not in cmd
    user = cmd[cmd.index("--user") + 1:]
    assert user[:2] == ["default", "on"] and any(a.startswith(">${KAINE_REDIS_VOLATILE_PASSWORD") for a in user)
    for denied in ("-save", "-bgsave", "-bgrewriteaof", "-shutdown", "-config|set", "-config|rewrite",
                   "-acl|setuser", "-module", "-replicaof", "-slaveof", "-debug"):
        assert denied in user, denied
    assert "+@all" in user and user.index("+@all") < user.index("-save")


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [("SAVE",), ("BGSAVE",), ("BGREWRITEAOF",), ("CONFIG",), ("ACL",), ("SHUTDOWN",)])
async def test_boot_refuses_a_volatile_bus_that_allows_persisting_commands(allowed):
    from kaine.bus.companion import CompanionDeclaration, CompanionRegistry
    from kaine.bus.volatile import PrivacySettings, VolatileBus, companion_refusals

    registry = CompanionRegistry(declarations=[CompanionDeclaration("p", "vision.out", "latent")])
    reasons = await companion_refusals(registry, VolatileBus(client=_ConfigClient(allowed=allowed)), PrivacySettings())
    assert reasons and all("allows" in r and allowed[0] in r for r in reasons)
    from kaine.bus.volatile import PERSISTING_COMMANDS

    reasons = await companion_refusals(registry, VolatileBus(client=_ConfigClient(dryrun=False)), PrivacySettings())
    assert len(reasons) == len(PERSISTING_COMMANDS) and all("cannot show" in r for r in reasons)


@pytest.mark.asyncio
async def test_boot_accepts_an_acl_password_without_requirepass():
    from kaine.bus.companion import CompanionDeclaration, CompanionRegistry
    from kaine.bus.volatile import PrivacySettings, VolatileBus, companion_refusals

    registry = CompanionRegistry(declarations=[CompanionDeclaration("p", "vision.out", "latent")])
    ok = VolatileBus(client=_ConfigClient(requirepass="", acl_password=True))
    assert await companion_refusals(registry, ok, PrivacySettings()) == []
    nopass = VolatileBus(client=_ConfigClient(requirepass="", acl_password=False))
    (reason,) = await companion_refusals(registry, nopass, PrivacySettings())
    assert "requires no password" in reason


@pytest.mark.asyncio
async def test_companion_entry_must_live_on_its_bound_streams_companion(bus):
    """A companion entry whose binding names another stream than the companion
    stream it sits on is never joined, even when source, type and timestamp match."""
    from kaine.bus.companion import BINDING_KEY, binding_for
    from kaine.bus.schema import Event

    volatile = attach_spoken_test_volatile(bus)
    ts = datetime.now(timezone.utc)
    values = {"spoken_text": [[["text"], HEARD, 0]],
              BINDING_KEY: binding_for("audition.out", "audition", "audition.transcription", ts.isoformat())}
    eid = await volatile.add("language.external.companion", values)
    event = Event(source="audition", type="audition.transcription", salience=0.5, timestamp=ts,
                  payload={}, companion=f"language.external.companion:{eid}")
    joined, ok = await bus.join_companion(event)
    assert ok is False and "text" not in joined.payload
    good = await volatile.add("audition.out.companion", values)
    joined, ok = await bus.join_companion(event.model_copy(update={"companion": f"audition.out.companion:{good}"}))
    assert ok and joined.payload["text"] == HEARD


@pytest.mark.asyncio
async def test_vocal_joins_only_its_own_streams_companion(bus, tmp_path):
    """language.external and language.out carry the same utterance with the
    same source, type and timestamp; a language.external entry naming the
    language.out companion is still refused by the vocal module."""
    from kaine.modules.vocal import FakePlayer, FakeTTSClient, Vocal

    attach_spoken_test_volatile(bus)
    utterance = _now_ev("language", "external_speech", {"text": HEARD, "mode": "external"})
    await bus.publish_on("language.out", utterance)
    (_eid, mirrored), = await bus.read("language.out")
    forged = {
        "source": "language", "type": "external_speech", "salience": "0.5",
        "timestamp": mirrored.timestamp.isoformat(), "causal_parent": "",
        "payload": json.dumps({"mode": "external"}), "companion": mirrored.companion,
    }
    await bus.client.xadd("language.external", forged)
    (_eid, event), = await bus.read("language.external")
    tts = FakeTTSClient(canned_audio=b"WAV")
    vocal = Vocal(bus, tts_client=tts, sink_path=tmp_path / "v", predefined_voice_id="v.wav", player=FakePlayer())
    await vocal._handle(vocal._language_stream, event)
    assert tts.requests == []
