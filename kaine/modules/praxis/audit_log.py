# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# The genesis link the first record chains from. A fixed, well-known constant so
# a verifier with only the on-disk log (and this module) can recompute the whole
# chain from scratch.
GENESIS_HASH = "0" * 64

# Hash fields are excluded from the canonical body that is hashed — the body is
# the record's substance, the two hash fields are the chain envelope around it.
_HASH_FIELDS = ("prev_hash", "this_hash")


def _canonical(core: dict[str, Any]) -> str:
    """Deterministic serialization of a record's substance (no hash fields).

    Key order and separators are pinned so the same record always hashes the
    same way regardless of insertion order or the writer's json defaults.
    """
    return json.dumps(core, sort_keys=True, separators=(",", ":"))


def _link_hash(prev_hash: str, core: dict[str, Any]) -> str:
    """``sha256(prev_hash || canonical(core))`` — one link of the chain."""
    digest = hashlib.sha256()
    digest.update(prev_hash.encode("utf-8"))
    digest.update(_canonical(core).encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class AuditChainResult:
    """Outcome of :meth:`ActionAuditLog.verify`.

    ``ok`` is True when every record's hash chains correctly from genesis.
    On the first break, ``broken_index`` is the 0-based record index and
    ``detail`` explains the failure (edit vs. reorder/truncation).
    """

    ok: bool
    broken_index: int | None = None
    detail: str = ""


class ActionAuditLog:
    """Tamper-evident, atomic-append JSONL audit log for Praxis actions.

    Each record is one JSON object on a single line. Content (file body, shell
    stdout, notification body) is intentionally NOT written here — only metadata
    and result status.

    Records are hash-chained: each carries ``prev_hash`` (the previous record's
    ``this_hash``, or :data:`GENESIS_HASH` for the first) and
    ``this_hash = sha256(prev_hash || canonical(record))`` over the record's
    substance. :meth:`verify` walks the on-disk chain and reports the first break.

    Threat model — read this before trusting :meth:`verify`.
    This is an UNKEYED hash chain with no secret (HMAC), no external anchor, and
    no append-only storage. Be honest about what it does and does not buy:

    - DETECTED: accidental or naive tampering — an in-place edit to a record, a
      reordering of lines, or deletion of a record from the middle of the log
      (the following record's ``prev_hash`` stops chaining). This is the common
      corruption/foot-gun case the chain is for.
    - NOT DETECTED: a write-capable adversary who forges deliberately. Because the
      hash uses no secret, anyone who can write the file can edit a record and
      recompute ``this_hash``/``prev_hash`` forward for every later record, after
      which :meth:`verify` returns ``ok``. Tail truncation of the newest records
      is likewise undetectable from the chain alone (it needs an external length
      anchor). Closing these requires an HMAC key held off the writable path or a
      periodic external anchor — deliberately out of scope here; the 0600/0700
      permissions below are the current line of defense against untrusted writers.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _last_hash(self) -> str:
        """The most recent record's ``this_hash``, or genesis if the log is
        empty/absent. A corrupt tail falls back to genesis so the next record
        chains from a known point and :meth:`verify` surfaces the break."""
        if not self._path.exists():
            return GENESIS_HASH
        last = ""
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        last = line
        except OSError:
            return GENESIS_HASH
        if not last:
            return GENESIS_HASH
        try:
            return str(json.loads(last)["this_hash"])
        except Exception:
            return GENESIS_HASH

    def append(
        self,
        *,
        effector: str,
        request_summary: dict[str, Any],
        success: bool,
        elapsed_ms: float,
        error: str | None,
        blocked: bool = False,
        provenance_rejected: bool = False,
    ) -> None:
        # The audit log holds action provenance; create its directory owner-only
        # (0700) regardless of the ambient umask, mirroring snapshot.py /
        # effectors.py / preservation.py rather than inheriting a loose umask.
        parent = self._path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _chmod_quietly(parent, 0o700)
        core = {
            "timestamp": time.time(),
            "effector": effector,
            "request": _sanitize(request_summary),
            "success": bool(success),
            "elapsed_ms": float(elapsed_ms),
            "error": error,
            # True when the action was refused by the operator effector-whitelist
            # gate (never reached its effector). Distinguishes a gate refusal from
            # an effector-internal failure for auditing.
            "blocked": bool(blocked),
            # True when the intent was refused at the provenance boundary — its
            # HMAC signature was missing/invalid, or it was a replay — so no
            # effector ran and the intent never reached the whitelist gate. A
            # DISTINCT category from `blocked` (whitelist refusal): a forged/
            # replayed intent is a security event, a blocked one is a policy one.
            "provenance_rejected": bool(provenance_rejected),
        }
        prev_hash = self._last_hash()
        record = {
            **core,
            "prev_hash": prev_hash,
            "this_hash": _link_hash(prev_hash, core),
        }
        line = json.dumps(record, sort_keys=True) + "\n"
        # Create+append atomically at mode 0600 via os.open, so a first-append
        # file is never briefly world-readable (no write-then-chmod race window).
        # `O_APPEND` keeps each single-line write atomic (< PIPE_BUF) on POSIX.
        try:
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            log.exception("praxis audit log write failed")
            return

    def verify(self) -> AuditChainResult:
        """Walk the on-disk hash chain and report the first break.

        Returns ``ok=True`` for an intact (or empty/absent) log; otherwise the
        0-based index of the first record whose ``prev_hash`` does not match the
        running chain (reorder/middle-truncation) or whose ``this_hash`` does not
        match its recomputed link (edit)."""
        if not self._path.exists():
            return AuditChainResult(ok=True)
        prev = GENESIS_HASH
        idx = -1
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    idx += 1
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        return AuditChainResult(
                            ok=False, broken_index=idx, detail="record is not valid JSON"
                        )
                    core = {k: v for k, v in record.items() if k not in _HASH_FIELDS}
                    if record.get("prev_hash") != prev:
                        return AuditChainResult(
                            ok=False,
                            broken_index=idx,
                            detail="prev_hash breaks the chain (reordered or truncated history)",
                        )
                    expected = _link_hash(prev, core)
                    if record.get("this_hash") != expected:
                        return AuditChainResult(
                            ok=False,
                            broken_index=idx,
                            detail="this_hash does not match record contents (edited)",
                        )
                    prev = expected
        except OSError as exc:
            return AuditChainResult(ok=False, detail=f"cannot read audit log: {exc}")
        return AuditChainResult(ok=True)


def _chmod_quietly(path: Path, mode: int) -> None:
    """Best-effort chmod; a no-op failure on non-POSIX is acceptable."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        # Hardening the perms is best-effort: filesystems that don't support
        # POSIX modes (e.g. some network/Windows mounts) can't honour the
        # request. The audit log stays usable; we only lose the perm tightening,
        # so swallow the failure rather than break logging. Debug-logged for
        # diagnosis when someone turns verbosity up.
        log.debug("best-effort chmod of %s to %o failed", path, mode, exc_info=True)


_FORBIDDEN_KEYS = frozenset({"content", "body", "stdout"})


def _sanitize(summary: dict[str, Any]) -> dict[str, Any]:
    """Strip content fields from a request summary before logging."""
    out: dict[str, Any] = {}
    for k, v in summary.items():
        if k in _FORBIDDEN_KEYS:
            continue
        out[k] = v
    return out
