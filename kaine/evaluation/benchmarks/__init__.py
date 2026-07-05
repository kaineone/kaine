# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline research benchmarks for KAINE cognitive components.

These are headless instruments: they construct synthetic problems and run
KAINE's engines against baselines, *without* booting an entity or attaching to
the live cognitive loop / event bus. They are operator-run and collect no live
sense-data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["write_jsonl"]


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """Write records as JSONL (one JSON object per line).

    Creates parent directories as needed. ``default=str`` keeps non-JSON-native
    values (e.g. enum members) serializable rather than raising. Shared by every
    benchmark / instrument runner so results persist identically.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=str) + "\n")
