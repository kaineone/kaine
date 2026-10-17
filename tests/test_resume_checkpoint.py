# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
import os
import stat
import time
import types

import pytest

import kaine.lifecycle.resume_checkpoint as rc_module
from kaine.lifecycle.identity import mint_identity
from kaine.lifecycle.resume_checkpoint import (
    ResumeCheckpointer,
    capture_checkpoint,
    checkpoint_file,
    discard_checkpoint,
    read_checkpoint,
    restore_checkpoint,
    save_checkpoint,
    write_checkpoint,
)
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    is_encrypted,
    set_state_encryptor,
)


class FakeModule:
    def __init__(self, name, state=None, *, fail_serialize=False, fail_deserialize=False):
        self.name = name
        self.state = dict(state or {})
        self.fail_serialize = fail_serialize
        self.fail_deserialize = fail_deserialize
        self.deserialized = []

    def serialize(self):
        if self.fail_serialize:
            raise RuntimeError("boom")
        return dict(self.state)

    def deserialize(self, state):
        if self.fail_deserialize:
            raise ValueError("bad")
        self.deserialized.append(state)
        self.state = dict(state)


class FakeRegistry:
    def __init__(self, *modules):
        self._modules = list(modules)

    def all_modules(self):
        return list(self._modules)


def _interoception():
    pytest.importorskip("snntorch")
    from kaine.boot import make_interoception

    return make_interoception(types.SimpleNamespace(), {"self_rhythm_enabled": True})


def _affect():
    from kaine.modules.affect.module import Affect

    return Affect(types.SimpleNamespace(), publish_interval_s=999.0)


def _resume_warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.name == "kaine.lifecycle.resume_checkpoint" and r.levelno == logging.WARNING
    ]


@pytest.mark.asyncio
async def test_real_module_restart_round_trip(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"

    i1 = _interoception()
    a1 = _affect()

    fresh = _interoception()
    # Stay inside [ln tau_min, ln tau_max]; deserialize clamps to it.
    i1._self_rhythm._ln_tau = fresh._self_rhythm._ln_tau - 0.2
    assert i1._self_rhythm._ln_tau != fresh._self_rhythm._ln_tau
    i1._fatigue.load_state_dict({"value": 37.5})

    a1._drives.curiosity.value = 0.81
    a1._drives.restlessness.value = 0.66
    a1._drives.curiosity.own_ends = 3
    a1._drives.curiosity.other_ends = 2
    a1._goals.add("explore", drive="curiosity")

    assert await save_checkpoint(FakeRegistry(i1, a1), ident, reason="periodic", directory=d)

    i2 = _interoception()
    a2 = _affect()
    result = restore_checkpoint(FakeRegistry(i2, a2), ident, directory=d)

    assert set(result.restored) == {"interoception", "affect"}
    assert i2._self_rhythm._ln_tau == i1._self_rhythm._ln_tau
    assert i2._self_rhythm.identity == i1._self_rhythm.identity
    assert i2._fatigue.state_dict()["value"] == 37.5
    assert i2._self_rhythm._rng.bit_generator.state == i1._self_rhythm._rng.bit_generator.state
    assert a2._drives.curiosity.value == 0.81
    assert a2._drives.restlessness.value == 0.66
    assert a2._drives.curiosity.own_ends == 3
    assert a2._drives.curiosity.other_ends == 2
    assert a2._goals.to_dict() == a1._goals.to_dict()
    assert a2.serialize() == a1.serialize()


@pytest.mark.asyncio
async def test_transient_cursor_keys_not_stored(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"

    inter = _interoception()
    assert "cycle_cursor" in inter.serialize()
    assert await save_checkpoint(FakeRegistry(inter), ident, reason="periodic", directory=d)

    stored = read_checkpoint(d).modules["interoception"]
    assert "cycle_cursor" not in stored

    d2 = tmp_path / "ckpt2"
    embodiment = FakeModule("embodiment", {"intent_cursor": 1, "speech_cursor": 2, "other": 3})
    sequence = FakeModule("sequence", {"user_input_cursors": [4], "pred": 5})
    snap = capture_checkpoint(FakeRegistry(embodiment, sequence), ident, reason="test")
    write_checkpoint(snap, d2)

    stored_emb = read_checkpoint(d2).modules["embodiment"]
    stored_seq = read_checkpoint(d2).modules["sequence"]
    assert stored_emb == {"other": 3}
    assert stored_seq == {"pred": 5}


@pytest.mark.asyncio
async def test_self_persisting_modules_not_written_nor_restored(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"

    self_model = FakeModule("self_model", {"x": 1})
    episodic = FakeModule("episodic_memory", {"e": 2})
    social = FakeModule("social_cognition", {"s": 3})
    world = FakeModule("world_model", {"w": 4})
    vocal = FakeModule("vocal", {"v": 5})

    snap = capture_checkpoint(FakeRegistry(self_model, episodic, social, world, vocal), ident, reason="test")
    write_checkpoint(snap, d)

    assert set(read_checkpoint(d).modules.keys()) == {"vocal"}

    modified = dataclasses.replace(
        snap, modules={**snap.modules, "self_model": {"hand": True}}
    )
    write_checkpoint(modified, d)

    self_model2 = FakeModule("self_model", {})
    vocal2 = FakeModule("vocal", {})
    result = restore_checkpoint(FakeRegistry(self_model2, vocal2), ident, directory=d)

    assert result.restored == ("vocal",)
    assert self_model2.deserialized == []


@pytest.mark.asyncio
async def test_exactly_one_checkpoint_file_after_many_writes(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    module = FakeModule("m", {"v": 0})

    for i in range(25):
        module.state["v"] = i
        assert await save_checkpoint(FakeRegistry(module), ident, reason="periodic", directory=d)

    assert sorted(p.name for p in d.iterdir()) == ["checkpoint.json"]
    assert read_checkpoint(d).modules["m"]["v"] == 24


@pytest.mark.asyncio
async def test_checkpoint_encrypted_at_rest(tmp_path, monkeypatch):
    ident = mint_identity()
    d = tmp_path / "ckpt"

    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))

    marker = "marker-plaintext-7731"
    module = FakeModule("m", {"marker": marker})
    await save_checkpoint(FakeRegistry(module), ident, reason="periodic", directory=d)

    target = checkpoint_file(d)
    raw = target.read_bytes()
    assert marker.encode() not in raw
    assert b'"modules"' not in raw
    assert is_encrypted(base64.b64decode(raw))

    stored = read_checkpoint(d).modules["m"]["marker"]
    assert stored == marker

    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(target.parent).st_mode) == 0o700


@pytest.mark.asyncio
async def test_undecryptable_checkpoint_is_ignored(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="kaine.lifecycle.resume_checkpoint")
    ident = mint_identity()
    d = tmp_path / "ckpt"

    key_a = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key_a)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
    module = FakeModule("m", {"v": 1})
    await save_checkpoint(FakeRegistry(module), ident, reason="periodic", directory=d)

    key_b = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key_b)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))

    caplog.clear()
    assert restore_checkpoint(FakeRegistry(FakeModule("m")), ident, directory=d) is None
    assert len(_resume_warnings(caplog)) == 1
    assert module.deserialized == []

    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    caplog.clear()
    assert restore_checkpoint(FakeRegistry(FakeModule("m")), ident, directory=d) is None
    assert len(_resume_warnings(caplog)) == 1
    assert module.deserialized == []


def test_corrupt_checkpoint_is_ignored(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kaine.lifecycle.resume_checkpoint")
    ident = mint_identity()
    d = tmp_path / "ckpt"

    d.mkdir(parents=True)
    checkpoint_file(d).write_bytes(b"{not json")
    caplog.clear()
    assert restore_checkpoint(FakeRegistry(FakeModule("m")), ident, directory=d) is None
    assert len(_resume_warnings(caplog)) == 1

    checkpoint_file(d).write_text(json.dumps({"modules": {}, "metadata": {"kind": "other"}}))
    caplog.clear()
    assert restore_checkpoint(FakeRegistry(FakeModule("m")), ident, directory=d) is None
    assert len(_resume_warnings(caplog)) == 1


@pytest.mark.asyncio
async def test_other_entity_checkpoint_ignored(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kaine.lifecycle.resume_checkpoint")
    ident_a = mint_identity()
    ident_b = mint_identity()
    d = tmp_path / "ckpt"

    module = FakeModule("m", {"v": 1})
    await save_checkpoint(FakeRegistry(module), ident_a, reason="periodic", directory=d)

    caplog.clear()
    assert restore_checkpoint(FakeRegistry(FakeModule("m")), ident_b, directory=d) is None
    assert len(_resume_warnings(caplog)) == 1
    assert module.deserialized == []

    caplog.clear()
    assert restore_checkpoint(FakeRegistry(FakeModule("m")), None, directory=d) is None
    assert len(_resume_warnings(caplog)) == 1


def test_missing_checkpoint_returns_none(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kaine.lifecycle.resume_checkpoint")
    d = tmp_path / "empty"

    caplog.clear()
    assert restore_checkpoint(FakeRegistry(FakeModule("m")), mint_identity(), directory=d) is None
    assert len(_resume_warnings(caplog)) == 0


def test_absent_and_disabled_modules(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"

    a = FakeModule("a", {"v": 1})
    b = FakeModule("b", {"v": 2})
    snap = capture_checkpoint(FakeRegistry(a, b), ident, reason="test")
    write_checkpoint(snap, d)

    b2 = FakeModule("b", {})
    c = FakeModule("c", {})
    result = restore_checkpoint(FakeRegistry(b2, c), ident, directory=d)

    assert result.restored == ("b",)
    assert result.skipped == ("a",)
    assert result.fresh == ("c",)
    assert c.deserialized == []


@pytest.mark.asyncio
async def test_failing_deserialize_is_reported(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="kaine.lifecycle.resume_checkpoint")
    ident = mint_identity()
    d = tmp_path / "ckpt"

    good = FakeModule("good", {"v": 1})
    bad = FakeModule("bad", {"v": 2}, fail_deserialize=True)
    await save_checkpoint(FakeRegistry(good, bad), ident, reason="periodic", directory=d)

    caplog.clear()
    result = restore_checkpoint(FakeRegistry(good, bad), ident, directory=d)

    assert result.failed == ("bad",)
    assert result.restored == ("good",)
    assert len(_resume_warnings(caplog)) == 1


@pytest.mark.asyncio
async def test_failing_serialize_keeps_previous_checkpoint(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"

    module = FakeModule("m", {"v": 1})
    assert await save_checkpoint(FakeRegistry(module), ident, reason="periodic", directory=d)
    assert read_checkpoint(d).modules["m"]["v"] == 1

    bad_module = FakeModule("m", {"v": 2}, fail_serialize=True)
    ok = await save_checkpoint(FakeRegistry(bad_module), ident, reason="periodic", directory=d)
    assert ok is False
    assert read_checkpoint(d).modules["m"]["v"] == 1


@pytest.mark.asyncio
async def test_save_without_identity_returns_false(tmp_path):
    d = tmp_path / "ckpt"
    ok = await save_checkpoint(FakeRegistry(FakeModule("m")), None, reason="periodic", directory=d)
    assert ok is False
    assert not checkpoint_file(d).exists()


@pytest.mark.asyncio
async def test_discard_checkpoint(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    await save_checkpoint(FakeRegistry(FakeModule("m")), ident, reason="periodic", directory=d)

    assert discard_checkpoint(d) is True
    assert not checkpoint_file(d).exists()
    assert discard_checkpoint(d) is True


@pytest.mark.asyncio
async def test_periodic_checkpointer_writes_per_awake_interval(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    clock = {"awake": 0.0, "ok": True}
    module = FakeModule("m", {"v": 0})

    cp = ResumeCheckpointer(
        FakeRegistry(module),
        ident,
        awake_seconds=lambda: clock["awake"],
        can_write=lambda: clock["ok"],
        directory=d,
        interval_seconds=60.0,
        poll_seconds=0.01,
    )

    task = cp.start()
    await asyncio.sleep(0)  # let run() take its awake-time baseline

    async def wait_writes(n, timeout=2.0):
        deadline = time.monotonic() + timeout
        while cp.writes < n and time.monotonic() < deadline:
            await asyncio.sleep(0.01)

    clock["awake"] = 30.0
    await asyncio.sleep(0.05)
    assert cp.writes == 0

    clock["awake"] = 61.0
    await wait_writes(1)
    assert cp.writes == 1

    clock["awake"] = 200.0
    clock["ok"] = False
    await asyncio.sleep(0.1)
    assert cp.writes == 1

    clock["ok"] = True
    await wait_writes(2)
    assert cp.writes == 2

    await cp.stop()
    assert task.done()


@pytest.mark.asyncio
async def test_write_final_shutdown_and_asleep(tmp_path):
    ident = mint_identity()
    d = tmp_path / "ckpt"

    cp = ResumeCheckpointer(
        FakeRegistry(FakeModule("m", {"v": 1})),
        ident,
        awake_seconds=lambda: 0.0,
        can_write=lambda: True,
        directory=d,
        interval_seconds=60.0,
        poll_seconds=0.01,
    )
    cp.start()
    assert await cp.write_final(asleep=False) is True
    snap = read_checkpoint(d)
    assert snap.metadata["reason"] == "shutdown"
    assert cp._task.done()

    d2 = tmp_path / "ckpt2"
    cp2 = ResumeCheckpointer(
        FakeRegistry(FakeModule("m", {"v": 1})),
        ident,
        awake_seconds=lambda: 0.0,
        can_write=lambda: True,
        directory=d2,
        interval_seconds=60.0,
        poll_seconds=0.01,
    )
    cp2.start()
    assert await cp2.write_final(asleep=True) is False
    assert not checkpoint_file(d2).exists()
    assert cp2._task.done()


@pytest.mark.asyncio
async def test_stop_waits_for_in_flight_write(tmp_path, monkeypatch):
    import kaine.lifecycle.resume_checkpoint as rc

    real_write = rc.write_checkpoint

    def slow_write(snap, directory=None):
        time.sleep(0.2)
        return real_write(snap, directory)

    monkeypatch.setattr(rc, "write_checkpoint", slow_write)

    ident = mint_identity()
    d = tmp_path / "ckpt"
    clock = {"awake": 0.0}
    module = FakeModule("m", {"v": 1})

    cp = ResumeCheckpointer(
        FakeRegistry(module),
        ident,
        awake_seconds=lambda: clock["awake"],
        can_write=lambda: True,
        directory=d,
        interval_seconds=60.0,
        poll_seconds=0.01,
    )
    cp.start()
    await asyncio.sleep(0)  # let run() take its awake-time baseline

    clock["awake"] = 61.0
    await asyncio.sleep(0.05)
    await cp.stop()

    assert checkpoint_file(d).exists()
    assert cp.writes == 1


def test_checkpointer_rejects_non_positive_interval(tmp_path):
    ident = mint_identity()
    with pytest.raises(ValueError):
        ResumeCheckpointer(
            FakeRegistry(FakeModule("m")),
            ident,
            awake_seconds=lambda: 0.0,
            can_write=lambda: True,
            interval_seconds=0.0,
            poll_seconds=0.01,
        )


def test_write_checkpoint_fsyncs_the_directory(tmp_path, monkeypatch):
    real_fsync = rc_module.os.fsync
    recorded = []

    def wrapper(fd):
        recorded.append(os.fstat(fd).st_mode)
        return real_fsync(fd)

    monkeypatch.setattr(rc_module.os, "fsync", wrapper)

    write_checkpoint(
        capture_checkpoint(
            FakeRegistry(FakeModule("m", {"v": 1})),
            mint_identity(),
            reason="test",
        ),
        tmp_path / "ckpt",
    )

    assert any(stat.S_ISDIR(m) for m in recorded)
    assert any(stat.S_ISREG(m) for m in recorded)
