# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import base64
import io
import json
import os
import tarfile
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.decommission import capture_backup
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.modules.sleep import FakeTrainer, Sleep, Trainer, VoiceAlignmentConfig
from kaine.modules.sleep.corpus import intent_record_paths, rotate_intent_log
from kaine.modules.sleep.voice_alignment import OPERATOR_APPROVED_ENV, DPOPairBuilder
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)


@pytest.fixture(autouse=True)
def _voice_alignment_opt_in(monkeypatch):
    """Existing sleep tests assume voice-alignment training fires.
    Two-layer safety gate (config.enabled + env var) is set by default
    so the trainer is actually called; tests that want to exercise the
    skip-on-disabled paths override this fixture explicitly."""
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")


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


class FakeEpisodicMemory:
    def __init__(self) -> None:
        self.consolidated = 0
        self.downscale_calls: list[float] = []
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        self.consolidated += 1
        return 5

    async def downscale(self, protect=()):
        protect = list(protect)
        self.downscale_calls.append(protect)
        return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeAffect:
    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


class FakeResetter:
    def __init__(self) -> None:
        self.calls = 0

    def reset(self) -> None:
        self.calls += 1


def _make_sleep(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    intent_records: list[dict] | None = None,
    trainer: Trainer | None = None,
    episodic_memory=None,
) -> Sleep:
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
    return Sleep(
        bus,
        episodic_memory=episodic_memory or FakeEpisodicMemory(),
        affect=FakeAffect(),
        sequence_resetters=[FakeResetter(), FakeResetter()],
        trainer=trainer or FakeTrainer(),
        voice_alignment_config=config,
    )


def _assessment() -> DivergenceAssessment:
    return DivergenceAssessment(
        diverged=True, signals={"individuation_significant": True}, summary="x"
    )


def _enable(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))


def _seed_backup_state(state_root: Path) -> None:
    (state_root / "self_model").mkdir(parents=True, exist_ok=True)
    (state_root / "self_model" / "self_model.json").write_text(
        json.dumps({"name": "Kaine Nova"}), encoding="utf-8"
    )
    (state_root / "language").mkdir(parents=True, exist_ok=True)
    (state_root / "language" / "intent_expression.jsonl").write_text(
        '{"live": true}\n', encoding="utf-8"
    )
    corpus = state_root / "language" / "intent_log"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "sleep-a.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    (corpus / "sleep-b.jsonl").write_text('{"b": 1}\n', encoding="utf-8")


def _seed_fork(fork_root: Path) -> None:
    from kaine.lifecycle.snapshot import ForkSnapshot, save_snapshot

    snap = ForkSnapshot(label="root", modules={"interoception": {"wellness": 0.9}})
    save_snapshot(fork_root, snap)


@pytest.mark.asyncio
async def test_two_sleeps_scan_rotated_corpus_files(bus, tmp_path):
    """Two sleeps with a rotation in between keep the corpus scan counts stable."""
    intent_records = [
        {
            "prompt": "p",
            "faithful_rendering": f"truth {i}",
            "generated_text": f"generated {i}",
        }
        for i in range(20)
    ]
    h = _make_sleep(bus, tmp_path, intent_records=intent_records)
    log_path = h._voice_config.intent_log_path
    corpus_dir = log_path.parent / "intent_log"

    pairs, scanned, usable = h._builder.build_with_counts(
        intent_record_paths(log_path, corpus_dir), max_pairs=100
    )
    assert scanned == 20
    assert usable == 20
    assert len(pairs) == 20

    rotate_intent_log(log_path, corpus_dir, sleep_index=1)
    assert not log_path.exists()

    pairs2, scanned2, usable2 = h._builder.build_with_counts(
        intent_record_paths(log_path, corpus_dir), max_pairs=100
    )
    assert scanned2 == 20
    assert usable2 == 20
    assert len(pairs2) == 20


def test_scan_cap_across_files(tmp_path):
    """DPOPairBuilder enforces max_records_scanned across a sequence."""
    builder = DPOPairBuilder(max_records_scanned=5)
    file1 = tmp_path / "a.jsonl"
    file2 = tmp_path / "b.jsonl"
    records = [
        {
            "prompt": "p",
            "faithful_rendering": f"truth {i}",
            "generated_text": f"generated {i}",
        }
        for i in range(8)
    ]
    file1.write_text(
        "".join(json.dumps(r) + "\n" for r in records[:4]), encoding="utf-8"
    )
    file2.write_text(
        "".join(json.dumps(r) + "\n" for r in records[4:]), encoding="utf-8"
    )

    pairs, scanned, usable = builder.build_with_counts([file1, file2], max_pairs=100)
    assert scanned == 5
    assert usable == 5
    assert len(pairs) == 5


def test_intent_record_paths_orders_by_mtime_then_live(tmp_path):
    """Corpus files are oldest-first; the live log is always last."""
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir()
    live = tmp_path / "intent.jsonl"
    live.write_text('{"live": true}\n', encoding="utf-8")
    older = corpus_dir / "sleep-20260101T000000Z-0001.jsonl"
    newer = corpus_dir / "sleep-20260101T000001Z-0001.jsonl"
    older.write_text('{"older": 1}\n', encoding="utf-8")
    newer.write_text('{"newer": 1}\n', encoding="utf-8")

    base_ns = int(time.time() * 1_000_000_000)
    os.utime(older, ns=(base_ns, base_ns))
    os.utime(newer, ns=(base_ns + 1_000_000_000, base_ns + 1_000_000_000))

    assert intent_record_paths(live, corpus_dir) == [older, newer, live]

    # Swap mtimes: ordering flips.
    os.utime(older, ns=(base_ns + 2_000_000_000, base_ns + 2_000_000_000))
    assert intent_record_paths(live, corpus_dir) == [newer, older, live]


def test_capture_backup_plaintext_includes_corpus(tmp_path):
    """capture_backup copies the rotated intent log corpus in plaintext."""
    state_root = tmp_path / "state"
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    _seed_backup_state(state_root)
    _seed_fork(fork_root)

    result = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg={"episodic_memory": {"backend": "inmemory"}, "social_cognition": {"backend": "inmemory"}},  # no Qdrant: the runtime default would need a live store
        out_root=out_root,
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    bdir = result.backup_path
    assert (bdir / "intent_log" / "sleep-a.jsonl").read_bytes() == b'{"a": 1}\n'
    assert (bdir / "intent_log" / "sleep-b.jsonl").read_bytes() == b'{"b": 1}\n'
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert "intent_log/" in manifest["inventory"]


def test_capture_backup_encrypted_includes_corpus(monkeypatch, tmp_path):
    """The encrypted tar contains the rotated corpus members."""
    _enable(monkeypatch)
    state_root = tmp_path / "state"
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    _seed_backup_state(state_root)
    _seed_fork(fork_root)

    result = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg={"episodic_memory": {"backend": "inmemory"}, "social_cognition": {"backend": "inmemory"}},  # no Qdrant: the runtime default would need a live store
        out_root=out_root,
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    bdir = result.backup_path
    enc_path = bdir / "bundle.tar.enc"
    assert enc_path.is_file()

    raw = get_state_encryptor().decrypt(enc_path.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        names = set(tar.getnames())
    assert "intent_log/sleep-a.jsonl" in names
    assert "intent_log/sleep-b.jsonl" in names


def test_rotate_intent_log_unlink_failure_cleans_up(monkeypatch, tmp_path):
    """If unlinking the live log fails after hard-linking, the link is removed."""
    log_path = tmp_path / "intent.jsonl"
    corpus_dir = tmp_path / "intent_log"
    log_path.write_text('{"record": 1}\n', encoding="utf-8")
    real_unlink = os.unlink

    def fake_unlink(path):
        if Path(path) == log_path:
            raise OSError("permission denied")
        return real_unlink(path)

    monkeypatch.setattr(os, "unlink", fake_unlink)
    with pytest.raises(OSError, match="permission denied"):
        rotate_intent_log(log_path, corpus_dir, sleep_index=1)

    assert not corpus_dir.exists() or not any(corpus_dir.iterdir())
    assert log_path.read_text() == '{"record": 1}\n'
