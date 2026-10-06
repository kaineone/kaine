# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Intent-log rotation and corpus disk guard for the Hypnos voice-alignment pipeline."""

from __future__ import annotations

import datetime
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


def rotate_intent_log(
    log_path: Path,
    corpus_dir: Path,
    *,
    sleep_index: int,
    now: Callable[[], float] = time.time,
) -> Optional[Path]:
    """Move a non-empty intent log into the per-sleep corpus.

    The destination is named with UTC wall-clock time so the file name is
    meaningful even though ``sleep_index`` is not durable across restarts.
    The move never overwrites: a hard link is created and the source name is
    unlinked; if hard links are unsupported, ``os.rename`` is used only after
    confirming the destination does not exist.
    """
    if not log_path.exists() or log_path.stat().st_size == 0:
        return None

    corpus_dir.mkdir(parents=True, exist_ok=True)
    corpus_dir.chmod(0o700)

    ts = datetime.datetime.fromtimestamp(now(), tz=datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    base = f"sleep-{ts}-{sleep_index:04d}"

    src = str(log_path)
    dst: Optional[Path] = None
    suffix = 0
    while True:
        name = f"{base}.jsonl" if suffix == 0 else f"{base}-{suffix}.jsonl"
        dst = corpus_dir / name

        if dst.exists():
            suffix += 1
            continue

        try:
            os.link(src, str(dst))
        except FileExistsError:
            # A concurrent rotation claimed this name; try the next suffix.
            suffix += 1
            continue
        except OSError:
            # Hard links unsupported (e.g. cross-device). Fall back to rename,
            # but only when the destination is still free. Rotation runs only
            # inside Hypnos's sleep, which holds the sleep lock, so no second
            # rotation can claim the name between this check and the rename.
            if not dst.exists():
                os.rename(src, str(dst))
                break
            suffix += 1
            continue
        else:
            os.unlink(src)
            break

    return dst


def corpus_size_bytes(corpus_dir: Path) -> int:
    """Sum the sizes of all ``*.jsonl`` files in the corpus directory."""
    if not corpus_dir.exists():
        return 0

    total = 0
    for entry in corpus_dir.iterdir():
        if entry.is_file() and entry.suffix == ".jsonl":
            total += entry.stat().st_size
    return total


def check_corpus_ceiling(
    corpus_dir: Path,
    *,
    ceiling_gb: float,
    warn_fraction: float = 0.8,
) -> dict[str, int | bool]:
    """Warn when the corpus approaches its configured ceiling.

    This guard never deletes anything.  A non-positive ``ceiling_gb`` disables
    the check.
    """
    corpus_bytes = corpus_size_bytes(corpus_dir)
    if ceiling_gb <= 0:
        return {"corpus_bytes": corpus_bytes, "ceiling_bytes": 0, "warned": False}

    ceiling_bytes = int(ceiling_gb * 1024**3)
    warned = corpus_bytes >= int(warn_fraction * ceiling_bytes)

    if warned:
        log.warning(
            "Intent log corpus size is %d bytes (%.3f GB), at or above %.0f%% "
            "of the configured ceiling of %d bytes (%.3f GB); config key: "
            "[hypnos.voice_alignment].corpus_ceiling_gb=%.2f",
            corpus_bytes,
            corpus_bytes / (1024**3),
            warn_fraction * 100,
            ceiling_bytes,
            ceiling_gb,
            ceiling_gb,
        )

    return {
        "corpus_bytes": corpus_bytes,
        "ceiling_bytes": ceiling_bytes,
        "warned": warned,
    }
