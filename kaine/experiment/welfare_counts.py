# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare gray-zone counters and blind-sensor state from the JSONL rollup (boundary-neutral).

Lives in ``kaine.experiment`` so BOTH the evaluation tab
(``kaine.evaluation.nexus_tab``) and the Nexus diagnostics health board
(``kaine.nexus.health``) can read it without ``kaine.nexus`` importing
``kaine.evaluation`` (which the sidecar boundary forbids). Numeric only, no
entity-interior content (records are scrubbed through the shared PrivacyFilter
as belt-and-suspenders; welfare gray-zone records are content-free by
construction). Blind-sensor advisories expose only the processor label.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from kaine.lifecycle.welfare_signal import BLIND_SENSOR_PROCESSORS

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
                # Belt-and-suspenders: welfare records are numeric by
                # construction; drop any content field defensively.
                out.append({k: v for k, v in entry.items() if k not in CONTENT_FIELDS})
        except Exception:
            log.debug("skipped welfare rollup %s", jsonl, exc_info=True)
    return out[-limit:]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def welfare_counts_from_jsonl(logs_root: Path) -> dict[str, Any]:
    """Welfare gray-zone counters and blind-sensor state from the JSONL rollup only.

    Returns the four numeric counters, the highest blind-sensor advisory count
    seen, the processor labels still blind, and ``source`` ('jsonl' | 'none').
    """
    entries = _read_welfare_lines(Path(logs_root) / "welfare")
    if not entries:
        return (
            {key: None for key in _COUNT_FIELDS}
            | {"blind_sensor_advisories": None, "blind_sensors": [], "source": "none"}
        )
    counts = {
        key: max((e.get(field, 0) for e in entries), default=0)
        for key, field in _COUNT_FIELDS.items()
    }
    advisory_max = max(
        (
            e.get("blind_sensor_count", 0)
            for e in entries
            if _is_number(e.get("blind_sensor_count"))
        ),
        default=0,
    )
    valid_processors = set(BLIND_SENSOR_PROCESSORS.values())
    blind_now: set[str] = set()
    for e in entries:
        advisory = e.get("advisory")
        processor = e.get("processor")
        if not isinstance(processor, str) or processor not in valid_processors:
            continue
        if advisory == "blind_sensor":
            blind_now.add(processor)
        elif advisory == "blind_sensor_cleared":
            blind_now.discard(processor)
    counts["blind_sensor_advisories"] = advisory_max
    counts["blind_sensors"] = sorted(blind_now)
    counts["source"] = "jsonl"
    return counts
