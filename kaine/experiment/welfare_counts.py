# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare gray-zone counters and sensor advisory state from the JSONL rollup (boundary-neutral).

Lives in ``kaine.experiment`` so BOTH the evaluation tab
(``kaine.evaluation.dashboard_tab``) and the dashboard diagnostics health board
(``kaine.dashboard.health``) can read it without ``kaine.dashboard`` importing
``kaine.evaluation`` (which the sidecar boundary forbids). Numeric only, no
entity-interior content (records are scrubbed through the shared PrivacyFilter
as belt-and-suspenders; welfare gray-zone records are content-free by
construction). Sensor advisories expose only the processor label.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from kaine.lifecycle.welfare_signal import ADVISORY_RESET, BLIND_SENSOR_PROCESSORS

log = logging.getLogger(__name__)

_COUNT_FIELDS = {
    "unmaintained_fatigue": "unmaintained_fatigue_count",
    "sustained_extreme_vad": "sustained_extreme_vad_count",
    "replay_overload": "replay_overload_count",
    "sustained_interoceptive_distress": "sustained_interoceptive_distress_count",
}


def _get_encryptor() -> Any:
    """Load the state encryptor if available; otherwise return None."""
    try:
        from kaine.security.crypto import get_state_encryptor

        try:
            return get_state_encryptor()
        except Exception:
            return None
    except Exception:
        return None


def _decode_line(line: str, encryptor: Any) -> dict[str, Any] | None:
    """Decrypt (when possible) and parse a single JSONL line.

    Returns the decoded object only if it is a JSON object; otherwise None.
    """
    plain = line
    if encryptor is not None:
        try:
            plain = encryptor.decrypt_text(line)
        except Exception:
            plain = line
    try:
        entry = json.loads(plain)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict):
        return None
    return entry


def _read_welfare_lines(welfare_dir: Path, *, limit: int = 500) -> list[dict[str, Any]]:
    """Read the newest welfare rollup lines, bounded to the last three files."""
    if not welfare_dir.exists():
        return []
    from kaine.privacy_filter import CONTENT_FIELDS

    encryptor = _get_encryptor()
    out: list[dict[str, Any]] = []
    for jsonl in sorted(welfare_dir.glob("welfare-*.jsonl"))[-3:]:
        try:
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = _decode_line(line, encryptor)
                if entry is None:
                    continue
                # Belt-and-suspenders: welfare records are numeric by
                # construction; drop any content field defensively.
                out.append({k: v for k, v in entry.items() if k not in CONTENT_FIELDS})
        except Exception:
            log.debug("skipped welfare rollup %s", jsonl, exc_info=True)
    return out[-limit:]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def advisory_state_from_jsonl(logs_root: Path) -> dict[str, Any]:
    """Reconstruct current sensor advisory state from the JSONL rollup.

    Walks every welfare rollup file under ``logs_root / "welfare"`` from newest
    to oldest and each file's lines from last to first, stopping at the latest
    reset advisory. The most recent blind or silent advisory per known processor
    decides whether it is still blind or silent. Advisory counts are the
    maximum numeric count seen since the latest reset.
    """
    welfare_dir = Path(logs_root) / "welfare"
    if not welfare_dir.exists():
        return {
            "blind_sensors": [],
            "silent_sensors": [],
            "blind_sensor_advisories": None,
            "sensor_silent_advisories": None,
        }

    encryptor = _get_encryptor()
    valid_processors = set(BLIND_SENSOR_PROCESSORS.values())

    blind_decided: dict[str, bool] = {}
    silent_decided: dict[str, bool] = {}
    max_blind_count: int | float = 0
    max_silent_count: int | float = 0
    reset_seen = False

    try:
        files = sorted(welfare_dir.glob("welfare-*.jsonl"), reverse=True)
    except Exception:
        log.debug("failed to list welfare rollup files", exc_info=True)
        return {
            "blind_sensors": [],
            "silent_sensors": [],
            "blind_sensor_advisories": None,
            "sensor_silent_advisories": None,
        }

    for jsonl in files:
        try:
            text = jsonl.read_text(encoding="utf-8")
        except Exception:
            log.debug("skipped welfare rollup %s", jsonl, exc_info=True)
            continue
        for raw_line in reversed(text.splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            entry = _decode_line(line, encryptor)
            if not isinstance(entry, dict):
                continue

            advisory = entry.get("advisory")
            if advisory == ADVISORY_RESET:
                reset_seen = True
                break

            processor = entry.get("processor")
            if isinstance(processor, str) and processor in valid_processors:
                if advisory == "blind_sensor":
                    blind_decided.setdefault(processor, True)
                elif advisory == "blind_sensor_cleared":
                    blind_decided.setdefault(processor, False)
                elif advisory == "sensor_silent":
                    silent_decided.setdefault(processor, True)
                elif advisory == "sensor_silent_cleared":
                    silent_decided.setdefault(processor, False)

            if advisory in {"blind_sensor", "blind_sensor_cleared"}:
                count = entry.get("blind_sensor_count")
                if _is_number(count) and count > max_blind_count:
                    max_blind_count = count
            if advisory in {"sensor_silent", "sensor_silent_cleared"}:
                count = entry.get("sensor_silent_count")
                if _is_number(count) and count > max_silent_count:
                    max_silent_count = count

        if reset_seen:
            break

    if not files:
        return {
            "blind_sensors": [],
            "silent_sensors": [],
            "blind_sensor_advisories": None,
            "sensor_silent_advisories": None,
        }

    return {
        "blind_sensors": sorted(p for p, is_blind in blind_decided.items() if is_blind),
        "silent_sensors": sorted(p for p, is_silent in silent_decided.items() if is_silent),
        "blind_sensor_advisories": int(max_blind_count),
        "sensor_silent_advisories": int(max_silent_count),
    }


def welfare_counts_from_jsonl(logs_root: Path) -> dict[str, Any]:
    """Welfare gray-zone counters and sensor advisory state from the JSONL rollup.

    Returns the four numeric gray-zone counters, the highest blind-sensor and
    sensor-silent advisory counts seen since the latest reset, the processor
    labels still blind or silent, and ``source`` ('jsonl' | 'none').
    """
    entries = _read_welfare_lines(Path(logs_root) / "welfare")
    advisory_state = advisory_state_from_jsonl(logs_root)

    if not entries:
        return (
            {key: None for key in _COUNT_FIELDS}
            | {"source": "none"}
            | advisory_state
        )

    counts = {
        key: max((e.get(field, 0) for e in entries), default=0)
        for key, field in _COUNT_FIELDS.items()
    }
    counts["source"] = "jsonl"
    return counts | advisory_state
