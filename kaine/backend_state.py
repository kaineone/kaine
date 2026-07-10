# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral registry for runtime-backend load outcomes.

Each heavy organ (Lingua LLM, Mnemos vector store, Audio-In STT, ...) selects a
model *runtime backend* via a ``[<module>].backend`` config key (see
:mod:`kaine.modules.backends`). When a configured backend cannot load on the
current host — a missing third-party dependency, or a load error — the failure
must be **reported, not silent**: a capability quietly dropped reads as "it
works" when it does not (openspec ``runtime-backends``).

This module is the shared, dependency-free home for those reports: an in-process
list of structured :class:`BackendFailure` records plus pure readers. It depends
only on the stdlib, so BOTH the modules that record a failure and the Nexus
health surface that displays it can use it without either importing the other —
the same boundary-neutral pattern as :mod:`kaine.organ_window_state`.

Content-free: only the module name, the attempted backend, an optional fallback
that was used instead, and a short human reason ever leave here. Never model
weights, prompts, or utterance text.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackendFailure:
    """One backend that failed to load, and what happened instead.

    ``fallback`` is the lighter backend that was loaded in its place, or ``None``
    when the module disabled itself entirely. ``fatal`` is True only when there
    was neither a fallback nor a clean disable path (kept for completeness; the
    contract is that a load failure never raises into boot).
    """

    module: str
    backend: str
    reason: str
    fallback: str | None = None
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "backend": self.backend,
            "reason": self.reason,
            "fallback": self.fallback,
            "ts": self.ts,
        }


# Process-global registry. Boot is single-threaded, but a lock keeps the reader
# (the async Nexus health prober, possibly on another thread) consistent.
_LOCK = threading.Lock()
_FAILURES: list[BackendFailure] = []


def record_backend_failure(
    module: str,
    backend: str,
    reason: str,
    *,
    fallback: str | None = None,
) -> BackendFailure:
    """Register (and log) a backend that could not load on this host.

    Returns the stored record. Logs a structured WARNING naming the module and
    the failed backend so the reason is visible in the boot log as well as on
    the health surface.
    """
    failure = BackendFailure(
        module=str(module),
        backend=str(backend),
        reason=str(reason),
        fallback=(str(fallback) if fallback is not None else None),
    )
    with _LOCK:
        _FAILURES.append(failure)
    if failure.fallback is not None:
        log.warning(
            "backend load failed: module=%s backend=%s -> falling back to %s (%s)",
            failure.module,
            failure.backend,
            failure.fallback,
            failure.reason,
        )
    else:
        log.warning(
            "backend load failed: module=%s backend=%s -> module disabled (%s)",
            failure.module,
            failure.backend,
            failure.reason,
        )
    return failure


def backend_failures() -> list[BackendFailure]:
    """Return a snapshot copy of every recorded backend failure."""
    with _LOCK:
        return list(_FAILURES)


def backend_failures_snapshot() -> list[dict[str, Any]]:
    """Content-free dicts for the Nexus health surface / diagnostics JSON."""
    return [f.as_dict() for f in backend_failures()]


def clear_backend_failures() -> None:
    """Reset the registry. For test isolation and a fresh boot only."""
    with _LOCK:
        _FAILURES.clear()
