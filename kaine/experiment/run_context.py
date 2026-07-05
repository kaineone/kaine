# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-process run identity.

A ``RunContext`` is minted once at cycle startup and held process-globally,
exactly like ``kaine.security.crypto.get_state_encryptor``: modules and sinks
read it via ``get_run_context()`` rather than threading it through every call.
``get_run_context()`` returns ``None`` when no run has been started (the
library / unit-test default), which is what keeps record-stamping inert outside
a real run.

The context carries no entity interior and no operator-identifying data: a random
run_id, the integer seed, an ISO timestamp, a best-effort short git sha, the
configured model ids (documented model keys only), a config digest (a hash, not
the config), and the kaine version.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


def _utc_iso() -> str:
    """Current UTC time as an ISO-8601 string.

    The single shared wall-clock-to-ISO helper for run-scoped record stamping
    (preservation manifests, the Spot incident log). Boundary-neutral: this
    module already lives in ``kaine.experiment`` and is imported widely.
    """
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunContext:
    """Identity of one cycle run. Immutable once minted."""

    run_id: str
    seed: int
    started_at: str  # ISO-8601 UTC (passed in; the clock is never called at import)
    git_sha: Optional[str]
    model_ids: dict[str, str] = field(default_factory=dict)
    config_digest: str = ""
    kaine_version: str = ""
    # Reproducible perceptual-feed descriptor (reproducible-perception-feed):
    # {"mode": "off"|"seeded"|"playlist"|"camera", ...}. For seeded the seed +
    # schedule params (enough to regenerate the stream); for playlist the
    # manifest sha256 + per-item digests (enough to verify it). Non-content: no
    # rendered frames, no operator paths — just the descriptor. Empty dict means
    # the feed contributed nothing (e.g. off, or the descriptor was unavailable).
    perception_feed: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict view suitable for JSON serialization (manifest, stamping)."""
        return asdict(self)


def compute_git_sha(*, timeout_s: float = 2.0) -> Optional[str]:
    """Best-effort short git sha of the working tree.

    Returns ``None`` on any failure (no git, not a repo, detached, timeout).
    Never raises.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def compute_config_digest(mapping: Mapping[str, Any]) -> str:
    """Stable 16-hex-char digest of a resolved config mapping.

    ``sha256(json.dumps(mapping, sort_keys=True, default=str))[:16]`` — lets two
    runs be compared for "same config" without storing the (operator-specific)
    config itself. Stable across identical mappings; changes on any change.
    """
    encoded = json.dumps(mapping, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def mint_run_context(
    *,
    seed: int,
    started_at: str,
    config: Mapping[str, Any],
    model_ids: Mapping[str, str],
    version: str,
    perception_feed: Mapping[str, Any] | None = None,
) -> RunContext:
    """Assemble a fresh ``RunContext``.

    ``run_id`` is a fresh uuid4 hex; ``git_sha`` is resolved best-effort; the
    config digest is computed from ``config``. The caller passes ``started_at``
    (an ISO timestamp) so the wall clock is never read at import time.

    ``perception_feed`` is the reproducible perception-feed descriptor, passed in
    BY THE CALLER as data (gathered at the cycle/boot layer via
    ``kaine.boot.gather_perception_feed_descriptor``) — this keeps
    ``kaine.experiment`` boundary-neutral and off the ``kaine.modules`` package,
    exactly like ``model_ids``.
    """
    return RunContext(
        run_id=uuid.uuid4().hex,
        seed=int(seed),
        started_at=str(started_at),
        git_sha=compute_git_sha(),
        model_ids=dict(model_ids),
        config_digest=compute_config_digest(config),
        kaine_version=str(version),
        perception_feed=dict(perception_feed or {"mode": "off"}),
    )


# ---------------------------------------------------------------------------
# Process-global active run context.
#
# Mirrors kaine/security/crypto.py::get_state_encryptor(): boot installs the
# minted context via set_run_context(); the default is None so imports and the
# unit-test suite see no run identity (record-stamping stays inert).
# ---------------------------------------------------------------------------

_active: Optional[RunContext] = None


def get_run_context() -> Optional[RunContext]:
    """Return the process-global RunContext, or ``None`` if no run started."""
    return _active


def set_run_context(ctx: Optional[RunContext]) -> None:
    """Install (or clear, with ``None``) the process-global RunContext."""
    global _active
    _active = ctx


__all__ = [
    "RunContext",
    "_utc_iso",
    "compute_git_sha",
    "compute_config_digest",
    "mint_run_context",
    "get_run_context",
    "set_run_context",
]
