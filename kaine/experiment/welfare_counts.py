# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare gray-zone counters from the JSONL rollup — boundary-neutral.

Lives in ``kaine.experiment`` so BOTH the evaluation tab
(``kaine.evaluation.nexus_tab``) and the Nexus diagnostics health board
(``kaine.nexus.health``) can read it without ``kaine.nexus`` importing
``kaine.evaluation`` (which the sidecar boundary forbids). Numeric only — no
entity-interior content (records are scrubbed through the shared PrivacyFilter
as belt-and-suspenders; welfare gray-zone records are content-free by
construction).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_COUNT_FIELDS = {
    "unmaintained_fatigue": "unmaintained_fatigue_count",
    "sustained_extreme_vad": "sustained_extreme_vad_count",
    "replay_overload": "replay_overload_count",
    "sustained_interoceptive_distress": "sustained_interoceptive_distress_count",
}


def _read_welfare_lines(welfare_dir: Path, *, limit: int = 500) -> list[dict[str, Any]]:
    if not welfare_dir.exists():
        return []
    from kaine.privacy_filter import CONTENT_FIELDS

    out: list[dict[str, Any]] = []
    for jsonl in sorted(welfare_dir.glob("welfare-*.jsonl"))[-3:]:
        try:
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                # Belt-and-suspenders: welfare gray-zone records are numeric by
                # construction; drop any content field defensively.
                out.append({k: v for k, v in entry.items() if k not in CONTENT_FIELDS})
        except Exception:
            log.debug("skipped welfare rollup %s", jsonl, exc_info=True)
    return out[-limit:]


def welfare_counts_from_jsonl(logs_root: Path) -> dict[str, Any]:
    """Welfare gray-zone counters from the JSONL rollup only (no live registry).

    Returns the four numeric counters plus ``source`` ('jsonl' | 'none').
    """
    entries = _read_welfare_lines(Path(logs_root) / "welfare")
    if not entries:
        return {key: None for key in _COUNT_FIELDS} | {"source": "none"}
    counts = {
        key: max((e.get(field, 0) for e in entries), default=0)
        for key, field in _COUNT_FIELDS.items()
    }
    counts["source"] = "jsonl"
    return counts
