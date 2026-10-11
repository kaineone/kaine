# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from kaine.persistence.encrypted_jsonl import (
    encode_record,
    has_envelope_line,
    has_plaintext_line,
    rewrite_encrypted,
)

log = logging.getLogger(__name__)


class IntentExpressionLog:
    """JSONL append log of every Lingua output.

    Each record is the input to Phase 6 Hypnos's DPO pair construction.
    The "chosen" side is the `faithful_rendering` field; the "rejected"
    side (when applicable) is the `generated_text`. Mode and metadata
    let Hypnos partition the training data.

    The log is the corpus of the being's own utterances, and it never holds
    heard speech.

    When state encryption is enabled, each line is written as its own
    AES-256-GCM envelope and the live log is migrated atomically on the first
    write of the process.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._migration_checked = False
        self._encryption_off_checked = False
        self._warned_encryption_off = False

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
        record_id: Optional[str] = None,
        intent_entry_id: Optional[str] = None,
        intent_origin: Optional[str] = None,
        sleep_index: Optional[int] = None,
        system_digest: Optional[str] = None,
        seed: Optional[int] = None,
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
            "record_id": record_id,
            "intent_entry_id": intent_entry_id,
            "intent_origin": intent_origin,
            "sleep_index": sleep_index,
            "system_digest": system_digest,
            "seed": seed,
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
        from kaine.security.crypto import get_state_encryptor

        encryptor = get_state_encryptor()

        if not encryptor.enabled:
            if not self._encryption_off_checked:
                self._encryption_off_checked = True
                if (
                    not self._warned_encryption_off
                    and self._path.is_file()
                    and has_envelope_line(self._path)
                ):
                    log.warning(
                        "intent log: encryption is off but the log already holds encrypted lines; new lines are written in plaintext"
                    )
                    self._warned_encryption_off = True
        elif not self._migration_checked:
            # Checked once per instance, and only under encryption: if the
            # encryptor is enabled later, the next write still migrates, and a
            # failed migration is retried on the next write.
            try:
                if has_plaintext_line(self._path):
                    rewrite_encrypted(self._path)
                    log.info(
                        "intent log: migrated plaintext lines to encrypted envelopes"
                    )
                self._migration_checked = True
            except Exception:
                log.exception(
                    "intent log: plaintext migration failed; retrying on the next write"
                )

        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # A torn final line (a crash mid-append) must not swallow the next
            # record: start on a fresh line.
            if self._path.is_file() and self._path.stat().st_size > 0:
                with open(self._path, "rb") as tail:
                    tail.seek(-1, os.SEEK_END)
                    torn = tail.read(1) != b"\n"
                if torn:
                    with open(self._path, "a", encoding="utf-8") as fhn:
                        fhn.write("\n")
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(encode_record(record) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            log.exception("intent-expression log write failed")
