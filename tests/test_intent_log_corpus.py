# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import datetime
import json
from pathlib import Path

from kaine.modules.hypnos.corpus import (
    check_corpus_ceiling,
    corpus_size_bytes,
    rotate_intent_log,
)

FIXED_NOW = 1_700_000_000.0
FIXED_TS = datetime.datetime.fromtimestamp(
    FIXED_NOW, tz=datetime.timezone.utc
).strftime("%Y%m%dT%H%M%SZ")


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def test_rotate_intent_log_moves_and_preserves_content(tmp_path: Path) -> None:
    log_path = tmp_path / "intent.jsonl"
    content = b'{"a": 1}\n{"b": 2}\n'
    log_path.write_bytes(content)
    corpus_dir = tmp_path / "intent_log"

    result = rotate_intent_log(log_path, corpus_dir, sleep_index=3, now=lambda: FIXED_NOW)

    assert result is not None
    assert not log_path.exists()
    files = sorted(corpus_dir.iterdir())
    assert len(files) == 1
    assert files[0] == result
    assert result.name.startswith("sleep-")
    assert result.name.endswith("-0003.jsonl")
    assert files[0].read_bytes() == content


def test_rotate_intent_log_same_second_suffix(tmp_path: Path) -> None:
    log_path = tmp_path / "intent.jsonl"
    corpus_dir = tmp_path / "intent_log"

    for i in range(3):
        log_path.write_text(f"line {i}\n")
        rotate_intent_log(log_path, corpus_dir, sleep_index=1, now=lambda: FIXED_NOW)
        log_path.unlink(missing_ok=True)

    names = {p.name for p in corpus_dir.iterdir()}
    assert names == {
        f"sleep-{FIXED_TS}-0001.jsonl",
        f"sleep-{FIXED_TS}-0001-1.jsonl",
        f"sleep-{FIXED_TS}-0001-2.jsonl",
    }


def test_rotate_intent_log_never_overwrites(tmp_path: Path) -> None:
    log_path = tmp_path / "intent.jsonl"
    original = b"original content\n"
    log_path.write_bytes(original)
    corpus_dir = tmp_path / "intent_log"
    first_name = f"sleep-{FIXED_TS}-0007.jsonl"
    preexisting = corpus_dir / first_name
    preexisting.parent.mkdir(parents=True, exist_ok=True)
    preexisting.write_bytes(b"preexisting content\n")

    result = rotate_intent_log(log_path, corpus_dir, sleep_index=7, now=lambda: FIXED_NOW)

    assert result is not None
    assert result.name == first_name.replace(".jsonl", "-1.jsonl")
    assert preexisting.read_bytes() == b"preexisting content\n"
    assert (corpus_dir / result.name).read_bytes() == original
    assert not log_path.exists()


def test_rotate_missing_or_empty_rotates_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    corpus_dir = tmp_path / "intent_log"

    assert rotate_intent_log(missing, corpus_dir, sleep_index=0) is None
    assert not corpus_dir.exists()

    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert rotate_intent_log(empty, corpus_dir, sleep_index=0) is None
    assert not corpus_dir.exists()


def test_three_rotations_current_log_only_post_rotation(tmp_path: Path) -> None:
    log_path = tmp_path / "intent.jsonl"
    corpus_dir = tmp_path / "intent_log"

    _append(log_path, "one\ntwo\n")
    rotate_intent_log(log_path, corpus_dir, sleep_index=0, now=lambda: FIXED_NOW)
    assert not log_path.exists()

    _append(log_path, "three\n")
    rotate_intent_log(log_path, corpus_dir, sleep_index=1, now=lambda: FIXED_NOW)

    _append(log_path, "four\n")
    rotate_intent_log(log_path, corpus_dir, sleep_index=2, now=lambda: FIXED_NOW)

    files = sorted(corpus_dir.iterdir())
    assert len(files) == 3
    assert files[0].read_text() == "one\ntwo\n"
    assert files[1].read_text() == "three\n"
    assert files[2].read_text() == "four\n"
    assert not log_path.exists()


def test_corpus_size_bytes_counts_jsonl_only(tmp_path: Path) -> None:
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir()
    (corpus_dir / "a.jsonl").write_bytes(b"12345")
    (corpus_dir / "b.jsonl").write_bytes(b"ab")
    (corpus_dir / "notes.txt").write_bytes(b"ignored")

    assert corpus_size_bytes(corpus_dir) == 7
    assert corpus_size_bytes(tmp_path / "does_not_exist") == 0


def test_check_corpus_ceiling_warns_at_threshold(tmp_path: Path, caplog) -> None:
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir()
    ceiling_gb = 1e-6
    ceiling_bytes = int(ceiling_gb * 1024**3)
    threshold = int(0.8 * ceiling_bytes)

    target = corpus_dir / "small.jsonl"
    target.write_bytes(b"x" * (threshold - 1))
    info = check_corpus_ceiling(corpus_dir, ceiling_gb=ceiling_gb)
    assert info["warned"] is False
    assert info["corpus_bytes"] == threshold - 1

    target.write_bytes(b"x" * threshold)
    with caplog.at_level("WARNING"):
        info = check_corpus_ceiling(corpus_dir, ceiling_gb=ceiling_gb)
    assert info["warned"] is True
    assert info["corpus_bytes"] == threshold
    assert info["ceiling_bytes"] == ceiling_bytes
    assert "[hypnos.voice_alignment].corpus_ceiling_gb" in caplog.text

    # The guard never deletes.
    assert target.exists()
    assert len(list(corpus_dir.iterdir())) == 1


def test_check_corpus_ceiling_zero_disables(tmp_path: Path, caplog) -> None:
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir()
    (corpus_dir / "big.jsonl").write_bytes(b"x" * 10_000)

    info = check_corpus_ceiling(corpus_dir, ceiling_gb=0.0)
    assert info["warned"] is False
    assert info["ceiling_bytes"] == 0


def test_corpus_dir_mode_0700(tmp_path: Path) -> None:
    log_path = tmp_path / "intent.jsonl"
    log_path.write_text(json.dumps({"record": 1}) + "\n")
    corpus_dir = tmp_path / "intent_log"

    rotate_intent_log(log_path, corpus_dir, sleep_index=0, now=lambda: FIXED_NOW)

    assert corpus_dir.exists()
    assert (corpus_dir.stat().st_mode & 0o777) == 0o700


def test_rotate_without_hard_links_falls_back_to_rename_and_never_overwrites(
    tmp_path: Path, monkeypatch
) -> None:
    """On a filesystem without hard links the move falls back to rename, and
    still never replaces an existing corpus file."""
    import kaine.modules.hypnos.corpus as corpus_mod

    def no_links(_src, _dst):
        raise OSError("hard links not supported")

    monkeypatch.setattr(corpus_mod.os, "link", no_links)
    log_path = tmp_path / "intent.jsonl"
    corpus_dir = tmp_path / "intent_log"
    corpus_dir.mkdir()
    taken = corpus_dir / f"sleep-{FIXED_TS}-0003.jsonl"
    taken.write_text("earlier sleep\n")
    log_path.write_text("this sleep\n")

    dst = rotate_intent_log(log_path, corpus_dir, sleep_index=3, now=lambda: FIXED_NOW)

    assert dst == corpus_dir / f"sleep-{FIXED_TS}-0003-1.jsonl"
    assert dst.read_text() == "this sleep\n"
    assert taken.read_text() == "earlier sleep\n"
    assert not log_path.exists()
