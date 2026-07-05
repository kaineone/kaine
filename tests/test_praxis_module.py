# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.praxis import (
    FileWriteRequest,
    NotifyRequest,
    Praxis,
    ShellRequest,
)
from kaine.modules.praxis.whitelist import CommandWhitelist, WhitelistEntry
from kaine.security.intent_signing import compute_intent_signature
from kaine.workspace.volition import VOLITION_STREAM

# The per-boot provenance secret the tests share between the signer (here) and
# Praxis (via _make_praxis). At a real boot this is generate_intent_secret().
_TEST_SECRET = b"praxis-provenance-test-secret-32"
_TEST_RUN_ID = "test-run"


async def _publish_act_intent(
    bus: AsyncBus,
    effector: str,
    params: dict,
    *,
    sign: bool = True,
    run_id: str = _TEST_RUN_ID,
    seq: int = 0,
    sig_override: str | None = None,
) -> None:
    """Publish an act intent onto volition.out, signed by default.

    With ``sign=True`` (the default) the payload carries a valid provenance
    envelope so Praxis realizes it. ``sign=False`` models a forged/peripheral
    writer that has no secret; ``sig_override`` models a wrong/forged signature.
    """
    payload = {"kind": "act", "about": "do it", "effector": effector, "params": params}
    if sign:
        signature = sig_override or compute_intent_signature(
            _TEST_SECRET,
            kind="act",
            effector=effector,
            params=params,
            run_id=run_id,
            seq=seq,
        )
        payload.update({"run_id": run_id, "seq": seq, "sig": signature})
    event = Event(
        source="volition",
        type="intent.act",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)


async def _wait_for(bus: AsyncBus, stream: str, *, timeout_s: float = 2.0):
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        entries = await bus.read(stream, last_id="0")
        if entries:
            return entries
        await asyncio.sleep(0.02)
    return await bus.read(stream, last_id="0")


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_praxis(
    bus: AsyncBus, tmp_path: Path, whitelist=None, enabled_effectors=None
) -> Praxis:
    return Praxis(
        bus,
        sandbox_path=tmp_path / "sb",
        audit_log_path=tmp_path / "audit.log",
        notification_command="this-binary-does-not-exist-xyz",
        notification_fallback_log=tmp_path / "notify.log",
        # The provenance secret matching the test signer, so intents published
        # via _publish_act_intent verify. Direct .act() tests are unaffected by
        # this (the boundary is only checked on the bus-intent path).
        intent_secret=_TEST_SECRET,
        whitelist=whitelist or CommandWhitelist(),
        # Default: the three built-in effectors are operator-enabled, so these
        # behaviour tests exercise the WITHIN-effector bounds (sandbox, command
        # whitelist). The empty-by-default gate itself is covered separately.
        enabled_effectors=(
            enabled_effectors
            if enabled_effectors is not None
            else ["file_write", "notify", "shell"]
        ),
    )


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus, tmp_path: Path):
    with pytest.raises(ValueError):
        Praxis(bus, sandbox_path=tmp_path, baseline_salience=2.0)
    with pytest.raises(ValueError):
        Praxis(bus, sandbox_path=tmp_path, alert_salience=-0.1)


@pytest.mark.asyncio
async def test_file_write_via_module(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    result = await p.act("file_write", FileWriteRequest(name="x.txt", content="hi"))
    assert result.success is True
    assert (tmp_path / "sb" / "x.txt").read_text() == "hi"


@pytest.mark.asyncio
async def test_unknown_effector_fails(bus: AsyncBus, tmp_path: Path):
    # Whitelist "nope" so it passes the enablement gate and reaches the layer-2
    # effector resolution, which fails because no such effector is registered.
    p = _make_praxis(bus, tmp_path, enabled_effectors=["nope"])
    result = await p.act("nope", FileWriteRequest(name="x", content="x"))
    assert result.success is False
    assert "unknown" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_action_publishes_diagnostics_only_event(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.act("file_write", FileWriteRequest(name="x.txt", content="secret content"))
    entries = await bus.read("praxis.out", last_id="0")
    assert len(entries) == 1
    _, event = entries[0]
    assert event.type == "praxis.action"
    keys = set(event.payload.keys())
    assert keys == {"effector", "success", "elapsed_ms", "error", "blocked"}
    # Payload contains no traces of the file content.
    for v in event.payload.values():
        if isinstance(v, str):
            assert "secret content" not in v


@pytest.mark.asyncio
async def test_audit_log_excludes_content(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.act("file_write", FileWriteRequest(name="x.txt", content="SUPER_SECRET"))
    audit_text = (tmp_path / "audit.log").read_text()
    assert "SUPER_SECRET" not in audit_text


@pytest.mark.asyncio
async def test_shell_via_module_with_whitelist(bus: AsyncBus, tmp_path: Path):
    wl = CommandWhitelist(
        [WhitelistEntry(command="echo", arg_patterns=("[A-Za-z]+",), timeout_s=2.0)]
    )
    p = _make_praxis(bus, tmp_path, whitelist=wl)
    result = await p.act("shell", ShellRequest(command="echo", args=["hi"]))
    assert result.success is True


@pytest.mark.asyncio
async def test_shell_rejects_unwhitelisted(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)  # empty whitelist
    result = await p.act("shell", ShellRequest(command="ls", args=[]))
    assert result.success is False
    entries = await bus.read("praxis.out", last_id="0")
    _, event = entries[0]
    assert event.payload["success"] is False


@pytest.mark.asyncio
async def test_alert_salience_on_failure(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.act("nope", FileWriteRequest(name="x", content="x"))
    entries = await bus.read("praxis.out", last_id="0")
    _, event = entries[0]
    assert event.salience == pytest.approx(p._alert_salience)


@pytest.mark.asyncio
async def test_baseline_salience_on_success(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.act("file_write", FileWriteRequest(name="x.txt", content="ok"))
    entries = await bus.read("praxis.out", last_id="0")
    _, event = entries[0]
    assert event.salience == pytest.approx(p._baseline_salience)


@pytest.mark.asyncio
async def test_praxis_realizes_act_intent(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        await _publish_act_intent(bus, "file_write", {"name": "y.txt", "content": "via intent"})
        # The effector ran (file written) and the action was audited.
        entries = await _wait_for(bus, "praxis.out")
        assert (tmp_path / "sb" / "y.txt").read_text() == "via intent"
        assert len(entries) == 1
        _, event = entries[0]
        assert event.type == "praxis.action"
        assert event.payload["effector"] == "file_write"
        assert event.payload["success"] is True
        audit_text = (tmp_path / "audit.log").read_text()
        assert "file_write" in audit_text
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_praxis_no_action_without_intent(bus: AsyncBus, tmp_path: Path):
    """A workspace broadcast occurs but no act intent is issued → no effector."""
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        from kaine.cycle.types import WorkspaceSnapshot

        snap = WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
        await p.on_workspace(snap)
        await asyncio.sleep(0.1)
        entries = await bus.read("praxis.out", last_id="0")
        assert entries == []
        assert not (tmp_path / "sb").exists() or not any((tmp_path / "sb").iterdir())
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_praxis_ignores_non_act_intent(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        # A speak intent on the same stream must not trigger any effector.
        event = Event(
            source="volition",
            type="intent.speak",
            payload={"kind": "speak", "about": "hi"},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await bus.publish(event)
        await asyncio.sleep(0.1)
        entries = await bus.read("praxis.out", last_id="0")
        assert entries == []
    finally:
        await p.shutdown()


def test_praxis_does_not_override_on_workspace():
    from kaine.modules.base import BaseModule

    assert Praxis.on_workspace is BaseModule.on_workspace


@pytest.mark.asyncio
async def test_register_effector(bus: AsyncBus, tmp_path: Path):
    # The custom effector must also be operator-enabled to run (the gate is
    # uniform — registering an effector does not auto-enable it).
    p = _make_praxis(
        bus, tmp_path, enabled_effectors=["file_write", "notify", "shell", "custom"]
    )

    class Custom:
        name = "custom"

        async def act(self, request):
            from kaine.modules.praxis.effectors import ActionResult
            return ActionResult(success=True, elapsed_ms=0.0)

    p.register_effector(Custom())
    result = await p.act("custom", FileWriteRequest(name="x", content="x"))
    assert result.success is True


# ---------------------------------------------------------------------------
# Effector-enablement whitelist (paper §3.4.4 / §3.5): EMPTY by default; every
# effector — notify included — is blocked + audit-logged unless whitelisted.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notify_denied_when_not_whitelisted(bus: AsyncBus, tmp_path: Path):
    # notify is NOT in the operator whitelist → blocked at the gate, audit-logged,
    # and the effector never runs (no fallback notification line is written).
    p = _make_praxis(bus, tmp_path, enabled_effectors=["file_write"])
    result = await p.act("notify", NotifyRequest(title="t", body="b"))
    assert result.success is False
    assert "whitelist" in (result.error or "").lower()
    # Published as a blocked action.
    entries = await bus.read("praxis.out", last_id="0")
    _, event = entries[0]
    assert event.payload["effector"] == "notify"
    assert event.payload["success"] is False
    assert event.payload["blocked"] is True
    # Audit-logged as blocked, and the effector did NOT execute (no notify log).
    records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text().splitlines()
        if line.strip()
    ]
    assert records and records[-1]["effector"] == "notify"
    assert records[-1]["blocked"] is True
    assert not (tmp_path / "notify.log").exists()


@pytest.mark.asyncio
async def test_notify_runs_when_whitelisted(bus: AsyncBus, tmp_path: Path):
    # With notify whitelisted, the effector runs (falls back to the notify log,
    # since the notifier binary does not exist) and is audit-logged as not-blocked.
    p = _make_praxis(bus, tmp_path, enabled_effectors=["notify"])
    result = await p.act("notify", NotifyRequest(title="t", body="b"))
    assert result.success is True
    assert (tmp_path / "notify.log").exists()
    records = [
        json.loads(line)
        for line in (tmp_path / "audit.log").read_text().splitlines()
        if line.strip()
    ]
    assert records[-1]["effector"] == "notify"
    assert records[-1]["blocked"] is False
    assert records[-1]["success"] is True


# ---------------------------------------------------------------------------
# Act-intent provenance boundary (authenticate-intent-provenance, Mechanism B).
# A missing/invalid/replayed HMAC signature drops the intent BEFORE any effector
# runs, and is audit-logged under the distinct provenance_rejected category.
# ---------------------------------------------------------------------------
def _read_audit(tmp_path: Path) -> list[dict]:
    p = tmp_path / "audit.log"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_signed_intent_is_realized(bus: AsyncBus, tmp_path: Path):
    # Happy path unchanged: a validly-signed act intent from Volition executes.
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        await _publish_act_intent(bus, "file_write", {"name": "ok.txt", "content": "hi"})
        await _wait_for(bus, "praxis.out")
        assert (tmp_path / "sb" / "ok.txt").read_text() == "hi"
        records = _read_audit(tmp_path)
        assert records and records[-1]["effector"] == "file_write"
        assert records[-1]["success"] is True
        assert records[-1]["provenance_rejected"] is False
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_missing_signature_rejected(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        await _publish_act_intent(
            bus, "file_write", {"name": "nope.txt", "content": "x"}, sign=False
        )
        entries = await _wait_for(bus, "praxis.out")
        # No effector ran: no file written.
        assert not (tmp_path / "sb" / "nope.txt").exists()
        # Audited under the distinct provenance_rejected category (NOT blocked).
        records = _read_audit(tmp_path)
        assert records and records[-1]["provenance_rejected"] is True
        assert records[-1]["blocked"] is False
        assert records[-1]["success"] is False
        # Surfaced on the bus as metadata only — no params/content.
        _, event = entries[-1]
        assert event.payload["provenance_rejected"] is True
        assert "content" not in json.dumps(event.payload)
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_forged_signature_rejected(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        await _publish_act_intent(
            bus,
            "file_write",
            {"name": "forged.txt", "content": "x"},
            sig_override="deadbeef" * 8,
        )
        await _wait_for(bus, "praxis.out")
        assert not (tmp_path / "sb" / "forged.txt").exists()
        records = _read_audit(tmp_path)
        assert records and records[-1]["provenance_rejected"] is True
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_replayed_intent_rejected(bus: AsyncBus, tmp_path: Path):
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        # Same (run_id, seq) published twice. The first is realized; the second
        # is a replay and must be rejected — no second write, no double-execute.
        await _publish_act_intent(
            bus, "file_write", {"name": "once.txt", "content": "first"}, seq=7
        )
        await _wait_for(bus, "praxis.out")
        await _publish_act_intent(
            bus, "file_write", {"name": "once.txt", "content": "first"}, seq=7
        )
        await asyncio.sleep(0.15)
        records = _read_audit(tmp_path)
        successes = [r for r in records if r.get("success") and not r.get("provenance_rejected")]
        replays = [r for r in records if r.get("provenance_rejected")]
        assert len(successes) == 1, "replay must not execute a second time"
        assert len(replays) == 1
        assert "replay" in (replays[0].get("error") or "").lower()
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_fail_closed_without_secret(bus: AsyncBus, tmp_path: Path):
    # Enforcement on (default) but NO secret injected → every act intent is
    # refused (a misconfigured boundary must not silently pass).
    p = Praxis(
        bus,
        sandbox_path=tmp_path / "sb",
        audit_log_path=tmp_path / "audit.log",
        enabled_effectors=["file_write"],
    )
    await p.initialize()
    try:
        await _publish_act_intent(bus, "file_write", {"name": "x.txt", "content": "x"})
        await _wait_for(bus, "praxis.out")
        assert not (tmp_path / "sb" / "x.txt").exists()
        records = _read_audit(tmp_path)
        assert records and records[-1]["provenance_rejected"] is True
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_replay_guard_survives_light_restart(bus: AsyncBus, tmp_path: Path):
    # The replay guard is in-process state. A LIGHT module restart (Spot's path
    # for a module with no external resources) re-initializes the SAME instance,
    # so the guard MUST persist: a captured signed intent re-delivered after a
    # restart is still rejected as a replay. This pins the invariant so a future
    # change that makes Praxis heavy (and thus rebuilt) is forced to reconsider.
    p = _make_praxis(bus, tmp_path)
    # The invariant depends on Praxis staying a light (non-externally-rebuilt)
    # module — see the replay-guard note in module.py.
    assert p.holds_external_resources() is False
    await p.initialize()
    try:
        await _publish_act_intent(bus, "file_write", {"name": "r.txt", "content": "a"}, seq=3)
        await _wait_for(bus, "praxis.out")
        before = _read_audit(tmp_path)
        assert len([r for r in before if r.get("success") and not r.get("provenance_rejected")]) == 1

        await p.restart()  # light restart on the same instance

        # Re-deliver the IDENTICAL signed (run_id=test-run, seq=3) intent.
        await _publish_act_intent(bus, "file_write", {"name": "r.txt", "content": "a"}, seq=3)
        await asyncio.sleep(0.2)
        records = _read_audit(tmp_path)
        successes = [r for r in records if r.get("success") and not r.get("provenance_rejected")]
        replays = [r for r in records if r.get("provenance_rejected")]
        # No second realization; the replay is rejected even after the restart.
        assert len(successes) == 1, "replay guard did not survive a light restart"
        assert replays and "replay" in (replays[-1].get("error") or "").lower()
    finally:
        await p.shutdown()


def test_praxis_stays_light_so_replay_guard_persists():
    # The replay guard's durability across a Spot restart depends on Praxis being
    # a LIGHT module: BaseModule.restart() re-initializes the same instance
    # (preserving _replay_high_water) ONLY because holds_external_resources() is
    # False, so Spot does not rebuild a fresh Praxis. If a future PR adds an
    # external resource and flips this to True, the replay window silently
    # reopens on restart — this assertion forces that PR to revisit replay
    # durability (persist/rotate the guard) rather than regress silently.
    from kaine.modules.base import BaseModule

    assert Praxis.holds_external_resources is BaseModule.holds_external_resources


@pytest.mark.asyncio
async def test_replay_guard_memory_is_bounded(bus: AsyncBus, tmp_path: Path):
    # The guard is an O(1) high-water mark per run_id, not an unbounded set of
    # realized pairs: realizing many intents leaves exactly one entry (one
    # per-boot run_id), and a stale capture below the mark is still rejected.
    p = _make_praxis(bus, tmp_path)
    await p.initialize()
    try:
        for seq in range(6):
            await _publish_act_intent(
                bus, "file_write", {"name": f"n{seq}.txt", "content": "x"}, seq=seq
            )
        await asyncio.sleep(0.2)
        # One run_id → one dict entry regardless of how many intents were realized.
        assert list(p._replay_high_water.keys()) == ["test-run"]
        assert p._replay_high_water["test-run"] == 5
        # A stale capture at/below the high-water mark is still rejected.
        await _publish_act_intent(
            bus, "file_write", {"name": "stale.txt", "content": "x"}, seq=2
        )
        await asyncio.sleep(0.2)
        assert not (tmp_path / "sb" / "stale.txt").exists()
        replays = [r for r in _read_audit(tmp_path) if r.get("provenance_rejected")]
        assert replays and "replay" in (replays[-1].get("error") or "").lower()
        # Still exactly one entry after the rejected replay.
        assert list(p._replay_high_water.keys()) == ["test-run"]
    finally:
        await p.shutdown()


@pytest.mark.asyncio
async def test_empty_whitelist_blocks_every_effector(bus: AsyncBus, tmp_path: Path):
    # The shipped empty-by-default posture: file_write, shell, notify all blocked
    # at the gate, none executes.
    p = _make_praxis(bus, tmp_path, enabled_effectors=[])
    fw = await p.act("file_write", FileWriteRequest(name="x.txt", content="hi"))
    sh = await p.act("shell", ShellRequest(command="echo", args=["hi"]))
    nt = await p.act("notify", NotifyRequest(title="t", body="b"))
    for r in (fw, sh, nt):
        assert r.success is False
        assert "whitelist" in (r.error or "").lower()
    # No file was written and no notification logged — nothing ran.
    assert not (tmp_path / "sb").exists() or not any((tmp_path / "sb").iterdir())
    assert not (tmp_path / "notify.log").exists()
