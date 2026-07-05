# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral atomic JSON state writer.

A single fail-safe ``write_json_atomic`` shared by every component that
persists small JSON state files (perception/control/escalation state, the
preflight gate, the runtime snapshot, the experiment manifest, organ revision
provenance, ...). Each of these had its own byte-identical ``_atomic_write``
copy; consolidating them keeps the on-disk format identical everywhere and
removes the drift risk.

The write is crash-safe: the payload is serialized to a sibling ``*.tmp`` file
and ``os.replace``d into place, which is atomic on POSIX. Serialization is
``json.dumps(payload, indent=2, sort_keys=True)`` so output bytes are stable
and diff-friendly.

This module is deliberately stdlib-only and imports nothing from the rest of
``kaine``, so it is import-legal from the core runtime, the modules, the
evaluation sidecar, and the boundary-neutral homes alike.

NOTE: The ENCRYPTING state writers (``kaine.lifecycle.snapshot``,
``kaine.lifecycle.decommission``, ``kaine.modules.phantasia.checkpoint``,
``kaine.modules.eidolon.document``) are a justified specialization — they
encrypt the payload (and chmod 0600) before it touches disk — and stay
SEPARATE from this plaintext helper on purpose.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = ["write_json_atomic"]


def write_json_atomic(path: Path, payload: Any) -> None:
    """Atomically write ``payload`` as pretty, sorted JSON to ``path``.

    Creates the parent directory if needed, writes to a sibling ``*.tmp`` file,
    then ``os.replace``s it into place (atomic on POSIX). The serialization is
    ``json.dumps(payload, indent=2, sort_keys=True)``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
