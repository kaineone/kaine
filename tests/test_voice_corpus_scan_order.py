# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.research.submission import DENY_PATTERNS
from tests.test_voice_corpus_protection import (
    DPOPairBuilder,
    _make_hypnos,
    _plaintext_encryptor,  # noqa: F401
    _voice_alignment_opt_in,  # noqa: F401
    intent_record_paths,
    read_consolidation_divergence,
)


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _record(index: int, *, divergent: bool) -> dict:
    chosen = f"truth {index}"
    rejected = f"generated {index}" if divergent else chosen
    return {
        "prompt": "p",
        "faithful_rendering": chosen,
        "generated_text": rejected,
        "timestamp": index,
    }


def test_newest_first_across_files_counts_recent_divergence(tmp_path: Path) -> None:
    """When the cap is smaller than the corpus, newest-first still evaluates recent speech."""
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir()
    live_log = tmp_path / "intent.jsonl"

    older = corpus_dir / "sleep-a.jsonl"
    newer = corpus_dir / "sleep-b.jsonl"
    older.write_text(
        "".join(json.dumps(_record(i, divergent=False)) + "\n" for i in range(20)),
        encoding="utf-8",
    )
    newer.write_text(
        "".join(json.dumps(_record(i, divergent=True)) + "\n" for i in range(20, 25)),
        encoding="utf-8",
    )
    live_log.write_text(
        "".join(json.dumps(_record(i, divergent=True)) + "\n" for i in range(25, 28)),
        encoding="utf-8",
    )

    base_ns = int(time.time() * 1_000_000_000)
    os.utime(older, ns=(base_ns, base_ns))
    os.utime(newer, ns=(base_ns + 1_000_000_000, base_ns + 1_000_000_000))

    builder = DPOPairBuilder(max_records_scanned=10)
    pairs, scanned, usable = builder.build_with_counts(
        intent_record_paths(live_log, corpus_dir), max_pairs=100
    )

    assert scanned == 10
    assert usable == 8
    assert len(pairs) == 8


def test_newest_first_switches_when_recent_records_lose_divergence(tmp_path: Path) -> None:
    """A change in the newest records is visible; oldest-first would hide it."""
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir()
    live_log = tmp_path / "intent.jsonl"

    older = corpus_dir / "sleep-a.jsonl"
    newer = corpus_dir / "sleep-b.jsonl"
    older.write_text(
        "".join(json.dumps(_record(i, divergent=False)) + "\n" for i in range(20)),
        encoding="utf-8",
    )
    newer.write_text(
        "".join(json.dumps(_record(i, divergent=True)) + "\n" for i in range(20, 25)),
        encoding="utf-8",
    )
    live_log.write_text(
        "".join(json.dumps(_record(i, divergent=False)) + "\n" for i in range(25, 28)),
        encoding="utf-8",
    )

    base_ns = int(time.time() * 1_000_000_000)
    os.utime(older, ns=(base_ns, base_ns))
    os.utime(newer, ns=(base_ns + 1_000_000_000, base_ns + 1_000_000_000))

    builder = DPOPairBuilder(max_records_scanned=10)
    pairs, scanned, usable = builder.build_with_counts(
        intent_record_paths(live_log, corpus_dir), max_pairs=100
    )

    assert scanned == 10
    assert usable == 5
    assert len(pairs) == 5


def test_within_single_file_last_lines_are_scanned_first(tmp_path: Path) -> None:
    """Reversing lines within a file lets the cap hit the newest records at the end."""
    single = tmp_path / "single.jsonl"
    lines = [json.dumps(_record(i, divergent=False)) for i in range(15)]
    lines.extend(json.dumps(_record(i, divergent=True)) for i in range(15, 19))
    single.write_text("\n".join(lines) + "\n", encoding="utf-8")

    builder = DPOPairBuilder(max_records_scanned=4)
    pairs, scanned, usable = builder.build_with_counts(single, max_pairs=100)

    assert scanned == 4
    assert usable == 4
    assert len(pairs) == 4


@pytest.mark.asyncio
async def test_hypnos_emission_uses_intent_record_paths(bus, tmp_path: Path) -> None:
    """The divergence emission reaches corpus files when the live log is absent."""
    h = _make_hypnos(bus, tmp_path, intent_records=None)
    corpus_dir = h._voice_config.intent_log_path.parent / "intent_log"
    corpus_dir.mkdir()
    corpus_file = corpus_dir / "sleep-1.jsonl"
    corpus_file.write_text(
        "".join(json.dumps(_record(i, divergent=True)) + "\n" for i in range(5)),
        encoding="utf-8",
    )
    assert not h._voice_config.intent_log_path.exists()

    divergence_path = tmp_path / "consolidation_divergence.json"
    h._consolidation_divergence_path = divergence_path

    await h._emit_consolidation_divergence()
    rec = read_consolidation_divergence(divergence_path)
    assert rec is not None
    assert rec["records_scanned"] > 0


def test_intent_log_is_a_research_submission_deny_pattern() -> None:
    assert "intent_log" in DENY_PATTERNS
