# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import copy
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# A snapshot id is a server-generated 16-hex UUID prefix (a fork/root id) or a
# `<hex>+<hex>` pair (a merge parent id). This is the ONE source of truth shared
# by the Nexus request boundary and the path-builder below — any id that fails it
# is definitionally not one this system minted, so it is treated as an attack.
_SNAPSHOT_ID_RE = re.compile(r"^[0-9a-f]{16}(\+[0-9a-f]{16})?$")


class InvalidSnapshotId(ValueError):
    """A snapshot id failed validation or resolved outside the snapshot root."""


def is_valid_snapshot_id(snapshot_id: str) -> bool:
    """True iff ``snapshot_id`` matches the strict fork/merge id grammar."""
    return isinstance(snapshot_id, str) and _SNAPSHOT_ID_RE.fullmatch(snapshot_id) is not None


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort chmod; a no-op failure on non-POSIX is acceptable."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        # e.g. no chmod support on this platform, or a permission error on an
        # already-owner-only file; the caller's hardening is best-effort.
        pass


@dataclass(frozen=True)
class ForkSnapshot:
    """A point-in-time capture of every registered module's state.

    Snapshots are content-addressable by `id`. `parent_id` is None for
    root snapshots, a single id for forks, and `<a>+<b>` for merges.
    """

    id: str = field(default_factory=_new_id)
    parent_id: str | None = None
    label: str = ""
    timestamp: float = field(default_factory=time.time)
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    adapters: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ForkSnapshot":
        return cls(
            id=str(raw.get("id") or _new_id()),
            parent_id=raw.get("parent_id"),
            label=str(raw.get("label") or ""),
            timestamp=float(raw.get("timestamp") or time.time()),
            modules=dict(raw.get("modules") or {}),
            adapters=list(raw.get("adapters") or []),
            metadata=dict(raw.get("metadata") or {}),
        )

    def with_modules(self, modules: dict[str, dict[str, Any]]) -> "ForkSnapshot":
        return ForkSnapshot(
            id=self.id,
            parent_id=self.parent_id,
            label=self.label,
            timestamp=self.timestamp,
            modules=copy.deepcopy(modules),
            adapters=list(self.adapters),
            metadata=dict(self.metadata),
        )


def snapshot_dir(root: Path, snapshot_id: str) -> Path:
    """Resolve ``<root>/<snapshot_id>``, refusing any id whose resolved path
    escapes ``root``.

    Defense in depth behind the Nexus id validator: even if a caller reaches
    this builder with an unvalidated id, an absolute or ``..``-bearing id cannot
    produce a path outside the snapshot root. Mirrors the Praxis sandbox
    containment check (``effectors._resolve_sandbox_path``) — note
    ``Path(root) / "/abs"`` discards ``root`` and ``..`` climbs out, so the
    resolved candidate MUST be re-confirmed to live under the resolved root.
    """
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / snapshot_id).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise InvalidSnapshotId(
            f"snapshot id escapes root: {snapshot_id!r}"
        ) from exc
    return candidate


def snapshot_path(root: Path, snapshot_id: str) -> Path:
    return snapshot_dir(root, snapshot_id) / "snapshot.json"


def save_snapshot(root: Path, snap: ForkSnapshot) -> Path:
    """Write a fork/merge snapshot bundle under ``<root>/<id>/snapshot.json``.

    When state encryption is enabled the bundle is AES-256-GCM encrypted before
    it is written; the key MUST be transferred out-of-band for cross-host
    fork/merge (see SECURITY.md).
    """
    from kaine.security.crypto import get_state_encryptor

    target_dir = snapshot_dir(root, snap.id)
    # Snapshot bundles hold the full cognitive state; create the snapshot root
    # and its parent owner-only (0700) so they are not group/world-readable.
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_quietly(root, 0o700)
    _chmod_quietly(target_dir, 0o700)
    target = snapshot_path(root, snap.id)
    tmp = target.with_suffix(".json.tmp")
    payload = json.dumps(snap.to_dict(), indent=2, sort_keys=True)
    tmp.write_text(get_state_encryptor().encrypt_text(payload))
    _chmod_quietly(tmp, 0o600)  # chmod before replace; the target inherits 0600
    os.replace(tmp, target)
    return target


def load_snapshot(root: Path, snapshot_id: str) -> ForkSnapshot:
    from kaine.security.crypto import get_state_encryptor

    target = snapshot_path(root, snapshot_id)
    text = get_state_encryptor().maybe_decrypt(target.read_bytes()).decode("utf-8")
    raw = json.loads(text)
    return ForkSnapshot.from_dict(raw)


def list_snapshots(root: Path) -> list[str]:
    if not root.exists():
        return []
    out: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "snapshot.json").exists():
            out.append(entry.name)
    return out
