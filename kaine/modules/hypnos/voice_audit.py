# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Atomic-append JSONL audit trail for voice-alignment veto decisions.

Each record is one JSON object on a single line written to
``<adapter_output_dir>/../voice_alignment_audit.jsonl`` — a SIBLING of the
adapters directory so it never appears as a spurious entry when the adapter
store is listed/pruned. The trail records the abliteration-veto verdict (and
any other promotion-gate decisions) so the welfare-load-bearing rejection of
a deflecting adapter is durably auditable — no model output content is ever
written, only the verdict, the matched refusal pattern (a short marker
string), and counts.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


AUDIT_FILENAME = "voice_alignment_audit.jsonl"


def voice_audit_path(adapter_output_dir: Path | str) -> Path:
    # Sibling of the adapters dir so the audit file never shows up as a
    # spurious entry in adapter_store.list_accepted() / prune() scans.
    return Path(adapter_output_dir).parent / AUDIT_FILENAME


def append_voice_audit(
    adapter_output_dir: Path | str,
    *,
    event: str,
    accepted: bool,
    reason: str,
    matched_pattern: Optional[str] = None,
    probes_scored: int = 0,
) -> None:
    """Append one verdict record to the voice-alignment audit trail."""
    path = voice_audit_path(adapter_output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": time.time(),
        "event": event,
        "accepted": bool(accepted),
        "reason": reason,
        "matched_pattern": matched_pattern,
        "probes_scored": int(probes_scored),
    }
    # `os.O_APPEND` is atomic for writes smaller than PIPE_BUF on POSIX —
    # ample for a single JSONL line.
    line = json.dumps(record, sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
