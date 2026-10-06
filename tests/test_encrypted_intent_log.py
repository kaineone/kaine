# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import base64
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.divergence import assess_divergence
from kaine.modules.hypnos import FakeTrainer, Hypnos, VoiceAlignmentConfig
from kaine.modules.hypnos.voice_alignment import DPOPairBuilder
from kaine.modules.hypnos.voice_measures import compute_sleep_measures
from kaine.modules.lingua.intent_log import IntentExpressionLog
from kaine.persistence.encrypted_jsonl import (
    _is_envelope,
    encode_record,
    iter_records,
    rewrite_encrypted,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _voice_alignment_opt_in(monkeypatch):
    from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV

    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")


def _enable(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    _set_key(monkeypatch, key)


def _set_key(monkeypatch, key):
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))


class FakeMnemos:
    def __init__(self) -> None:
        self.consolidated = 0
        self.downscale_calls = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidated += 1
        return 5

    def downscale_activations(self, factor: float) -> int:
        self.downscale_calls.append(factor)
        return 0

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeThymos:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


class FakeSteppable:
    @property
    def running(self) -> bool:
        return True

    async def step(self, n: int) -> list[str]:
        return ["belief_factor_0"]


class FakeResetter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls += 1


def _make_hypnos(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_records: list[dict] | None = None,
    trainer=None,
    mnemos=None,
):
    log_path = tmp_path / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if intent_records is not None:
        with log_path.open("w", encoding="utf-8") as fh:
            for r in intent_records:
                fh.write(json.dumps(r) + "\n")
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    return Hypnos(
        bus,
        mnemos=mnemos or FakeMnemos(),
        nous_process=FakeSteppable(),
        thymos=FakeThymos(),
        chronos_resetters=[FakeResetter(), FakeResetter()],
        trainer=trainer or FakeTrainer(),
        voice_alignment_config=config,
    )


def test_round_trip(monkeypatch):
    _enable(monkeypatch)
    record = {"a": 1, "b": "text"}
    line = encode_record(record)
    assert _is_envelope(line)
    path = Path(tempfile.mkdtemp()) / "test.jsonl"
    path.write_text(line + "\n", encoding="utf-8")
    lines = list(iter_records(path))
    assert len(lines) == 1
    assert lines[0].record == record
    assert not lines[0].unreadable


def test_mixed_file(monkeypatch):
    _enable(monkeypatch)
    record1 = {"a": 1}
    record2 = {"b": 2}
    plaintext = json.dumps(record1)
    envelope = encode_record(record2)
    path = Path(tempfile.mkdtemp()) / "test.jsonl"
    path.write_text(plaintext + "\n" + envelope + "\n", encoding="utf-8")
    lines = list(iter_records(path))
    assert len(lines) == 2
    assert lines[0].record == record1
    assert not lines[0].unreadable
    assert lines[1].record == record2
    assert not lines[1].unreadable


def test_wrong_key(monkeypatch):
    _enable(monkeypatch)
    record = {"secret": "x"}
    envelope = encode_record(record)
    key2 = base64.b64encode(os.urandom(32)).decode("ascii")
    _set_key(monkeypatch, key2)
    path = Path(tempfile.mkdtemp()) / "test.jsonl"
    path.write_text(envelope + "\n", encoding="utf-8")
    lines = list(iter_records(path))
    assert len(lines) == 1
    assert lines[0].unreadable
    assert lines[0].record is None


def test_disabled_encryptor(monkeypatch):
    _enable(monkeypatch)
    record = {"secret": "x"}
    envelope = encode_record(record)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    path = Path(tempfile.mkdtemp()) / "test.jsonl"
    path.write_text(envelope + "\n", encoding="utf-8")
    lines = list(iter_records(path))
    assert len(lines) == 1
    assert lines[0].unreadable
    assert lines[0].record is None
    assert b"SENTINEL-DISABLED" not in path.read_bytes()


def test_tampering(monkeypatch, tmp_path):
    """Flipping one ciphertext character fails authentication."""
    _enable(monkeypatch)
    envelope = encode_record({"secret": "x"})
    # Flip a character in the ciphertext tail (before any '=' padding), so the
    # envelope stays valid base64 but no longer authenticates.
    body = envelope.rstrip("=")
    i = len(body) - 2
    flipped = "B" if body[i] != "B" else "C"
    tampered = envelope[:i] + flipped + envelope[i + 1 :]
    assert tampered != envelope
    base64.b64decode(tampered, validate=True)
    path = tmp_path / "test.jsonl"
    path.write_text(tampered + "\n", encoding="utf-8")
    lines = list(iter_records(path))
    assert len(lines) == 1
    assert lines[0].unreadable


def test_rewrite(monkeypatch, tmp_path):
    _enable(monkeypatch)
    record1 = {"a": 1}
    record2 = {"b": 2}
    envelope = encode_record(record2)
    path = tmp_path / "test.jsonl"
    path.write_text(json.dumps(record1) + "\n" + envelope + "\n", encoding="utf-8")
    assert rewrite_encrypted(path) is True
    raw_lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(raw_lines) == 2
    assert raw_lines[1] == envelope
    decoded = list(iter_records(path))
    assert decoded[0].record == record1
    assert decoded[1].record == record2
    assert rewrite_encrypted(path) is False
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    assert rewrite_encrypted(path) is False


def test_atomicity(monkeypatch, tmp_path):
    _enable(monkeypatch)
    record = {"a": 1}
    path = tmp_path / "test.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    original = path.read_bytes()

    def bad_replace(src, dst):
        raise OSError("boom")

    monkeypatch.setattr(os, "replace", bad_replace)
    with pytest.raises(OSError):
        rewrite_encrypted(path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_lingua_writes_envelopes(monkeypatch, tmp_path):
    _enable(monkeypatch)
    log = IntentExpressionLog(tmp_path / "intent_expression.jsonl")
    log.append(
        mode="test",
        prompt="prompt",
        generated_text="SENTINEL-MONOLOGUE-7731",
        model="model",
    )
    raw = (tmp_path / "intent_expression.jsonl").read_bytes()
    assert b"SENTINEL-MONOLOGUE-7731" not in raw
    lines = list(iter_records(tmp_path / "intent_expression.jsonl"))
    assert len(lines) == 1
    assert lines[0].record["generated_text"] == "SENTINEL-MONOLOGUE-7731"


def test_lingua_migrates_once(monkeypatch, tmp_path):
    _enable(monkeypatch)
    path = tmp_path / "intent_expression.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"a": 1}) + "\n" + json.dumps({"b": 2}) + "\n",
        encoding="utf-8",
    )
    import kaine.modules.lingua.intent_log as intent_log_module

    calls = []
    original_rewrite = intent_log_module.rewrite_encrypted

    def counting_rewrite(p):
        calls.append(p)
        return original_rewrite(p)

    monkeypatch.setattr(intent_log_module, "rewrite_encrypted", counting_rewrite)
    log1 = IntentExpressionLog(path)
    log1.append(mode="m", prompt="p", generated_text="g", model="m")
    assert len(calls) == 1
    decoded = list(iter_records(path))
    assert len(decoded) == 3
    assert all(not line.unreadable for line in decoded)

    log2 = IntentExpressionLog(path)
    log2.append(mode="m", prompt="p", generated_text="g2", model="m")
    assert len(calls) == 1


def test_welfare_case(monkeypatch, tmp_path):
    _enable(monkeypatch)
    root = tmp_path / "state"
    lingua = root / "lingua"
    lingua.mkdir(parents=True, exist_ok=True)
    record = {"generated_text": "hello world"}
    envelope = encode_record(record)
    (lingua / "intent_expression.jsonl").write_text(envelope + "\n", encoding="utf-8")
    key2 = base64.b64encode(os.urandom(32)).decode("ascii")
    _set_key(monkeypatch, key2)
    result = assess_divergence(state_root=root, distinctiveness_threshold=0.5)
    assert result.diverged is True
    assert result.signals["voice_vote"] == "diverged"


def test_measures_unreadable(monkeypatch, tmp_path):
    key_a = base64.b64encode(os.urandom(32)).decode("ascii")
    _set_key(monkeypatch, key_a)
    path = tmp_path / "corpus.jsonl"
    good = {"generated_text": "a", "faithful_rendering": "b"}
    good_envelope = encode_record(good)
    key_b = base64.b64encode(os.urandom(32)).decode("ascii")
    _set_key(monkeypatch, key_b)
    bad_envelope = encode_record({"generated_text": "x"})
    path.write_text(good_envelope + "\n" + bad_envelope + "\n", encoding="utf-8")
    _set_key(monkeypatch, key_a)
    base_profile = {"gguf_sha256": "abc", "style_profile": {}}
    cumulative = {"some": "profile"}
    measures, new_cumulative = compute_sleep_measures(
        path, base_profile=base_profile, cumulative=cumulative
    )
    assert measures["unreadable_lines"] == 1
    assert measures["distinctiveness"] is None
    assert measures["self_consistency"] is None
    assert new_cumulative is cumulative


def test_pair_builder_unreadable(monkeypatch, tmp_path):
    key_a = base64.b64encode(os.urandom(32)).decode("ascii")
    _set_key(monkeypatch, key_a)
    usable = {"prompt": "p", "faithful_rendering": "a", "generated_text": "b"}
    usable_envelope = encode_record(usable)
    key_b = base64.b64encode(os.urandom(32)).decode("ascii")
    _set_key(monkeypatch, key_b)
    foreign_envelope = encode_record(
        {"prompt": "x", "faithful_rendering": "c", "generated_text": "d"}
    )
    path = tmp_path / "intent.jsonl"
    path.write_text(usable_envelope + "\n" + foreign_envelope + "\n", encoding="utf-8")
    _set_key(monkeypatch, key_a)
    builder = DPOPairBuilder(max_records_scanned=10000)
    pairs, scanned, usable_count = builder.build_with_counts(path, max_pairs=10)
    assert len(pairs) == 1
    assert scanned == 1
    assert usable_count == 1
    assert pairs[0].chosen == "a"
    assert pairs[0].rejected == "b"


@pytest.mark.asyncio
async def test_hypnos_corpus_rewrite_scope(monkeypatch, tmp_path, bus):
    _enable(monkeypatch)
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "sleep-1.jsonl").write_text(
        json.dumps({"generated_text": "old", "faithful_rendering": "old"}) + "\n",
        encoding="utf-8",
    )
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backups_dir / "x.jsonl"
    backup_content = json.dumps({"secret": "keep"}) + "\n"
    backup_file.write_text(backup_content, encoding="utf-8")

    intent_records = [
        {
            "prompt": "p",
            "generated_text": "gen",
            "faithful_rendering": "faith",
            "mode": "m",
            "model": "m",
            "timestamp": time.time(),
        },
    ]
    hypnos = _make_hypnos(bus, tmp_path, intent_records=intent_records)
    summary = await hypnos.enter_sleep()
    # The pre-existing plaintext sleep-1 file and the newly rotated log.
    assert summary["corpus"]["encrypted_rewrites"] == 2

    for f in corpus_dir.glob("sleep-*.jsonl"):
        for line in f.read_text(encoding="utf-8").strip().split("\n"):
            assert _is_envelope(line)

    assert backup_file.read_text(encoding="utf-8") == backup_content


def _append(log, text):
    log.append(mode="external", prompt="p", generated_text=text, model="m")


def test_migration_runs_when_encryption_is_enabled_after_a_plaintext_write(monkeypatch, tmp_path):
    path = tmp_path / "intent_expression.jsonl"
    log = IntentExpressionLog(path)
    _append(log, "before encryption")  # encryptor disabled: plaintext line
    _enable(monkeypatch)
    _append(log, "after encryption")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    assert all(_is_envelope(ln) for ln in lines)


def test_failed_migration_is_retried_on_the_next_write(monkeypatch, tmp_path):
    import kaine.modules.lingua.intent_log as intent_log_mod

    path = tmp_path / "intent_expression.jsonl"
    path.write_text(json.dumps({"generated_text": "legacy"}) + "\n", encoding="utf-8")
    _enable(monkeypatch)
    real = intent_log_mod.rewrite_encrypted
    calls = []

    def flaky(p):
        calls.append(p)
        if len(calls) == 1:
            raise OSError("disk hiccup")
        return real(p)

    monkeypatch.setattr(intent_log_mod, "rewrite_encrypted", flaky)
    log = IntentExpressionLog(path)
    _append(log, "one")
    _append(log, "two")
    assert len(calls) == 2
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert all(_is_envelope(ln) for ln in lines)
