# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


class IntentExpressionLog:
    """JSONL append log of every Lingua output.

    Each record is the input to Phase 6 Hypnos's DPO pair construction.
    The "chosen" side is the `faithful_rendering` field; the "rejected"
    side (when applicable) is the `generated_text`. Mode and metadata
    let Hypnos partition the training data.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        *,
        mode: str,
        prompt: str,
        generated_text: str,
        model: str,
        faithful_rendering: Optional[str] = None,
        snapshot_summary: Optional[dict[str, Any]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        record: dict[str, Any] = {
            "timestamp": time.time(),
            "mode": mode,
            "prompt": prompt,
            "generated_text": generated_text,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
        }
        if faithful_rendering is not None:
            record["faithful_rendering"] = faithful_rendering
        if snapshot_summary is not None:
            record["snapshot_summary"] = snapshot_summary
        if extra:
            record["extra"] = dict(extra)
        self._write(record)

    def record_preemption(
        self, *, mode: str, tick: Optional[int] = None
    ) -> None:
        """Content-free note that an in-flight utterance was preempted.

        Deliberately records NO prompt, generated text, or partial content —
        only that a preemption occurred, on which channel, and (when known) at
        which tick. This matches the zero-content policy of the other audit
        trails (``interruptible-utterance`` D4): a redirect means the entity
        changed its mind, and the unspoken remainder is discarded, not retained.
        The ``event: "preempted"`` tag lets DPO-pair construction skip these
        records (they carry no ``generated_text``/``faithful_rendering``).
        """
        record: dict[str, Any] = {
            "timestamp": time.time(),
            "event": "preempted",
            "mode": mode,
        }
        if tick is not None:
            record["tick"] = int(tick)
        self._write(record)

    def _write(self, record: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            log.exception("intent-expression log write failed")
