# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Service & dependency health probing for the Nexus diagnostics surface.

This was a single 1,144-line ``health.py`` module; it is now a small package
so the three concerns stay separable:

  * :mod:`.probes`  — individual dependency probe coroutines (Redis, Qdrant,
    the chat LLM, Speaches, Chatterbox, Nous/pymdp, state encryption) + the
    status vocabulary (``UP``/``DOWN``/``DEGRADED``/``NOT_CONFIGURED``).
  * :mod:`.blocks`   — the per-block snapshot builders (spot, preservation,
    cycle pacing, entity care, research, perception feed, model server, GPU
    pre-flight, welfare, admissibility, module states).
  * :mod:`.prober`   — ``DependencySpec`` + ``HealthProber``, the caching,
    timeout-bounded orchestrator that ties the above to instance config and
    exposes the single ``snapshot()`` entrypoint the diagnostics route calls.
  * :mod:`.config`   — ``build_dependency_specs`` / ``load_health_prober``,
    construction from ``config/kaine.toml`` (+ ``config/secrets.toml``).

Everything below is re-exported here so ``from kaine.nexus.health import X``
keeps working exactly as it did when this was one module — this package
split is purely internal; it changes no public behavior or import path.

The ``HEALTH_BLOCK_KEYS`` orphan-guard contract (every per-block key
``HealthProber.snapshot()`` surfaces must be extracted into the diagnostics
template context) lives in ``kaine/nexus/diagnostics.py`` — NOT here — and
stays there; this decomposition does not move or duplicate it.
"""
from __future__ import annotations

# Re-exported (not just used internally) so `kaine.nexus.health.httpx` still
# resolves — tests/test_chat_llm_health_probe.py monkeypatches
# `health.httpx.AsyncClient` the way it did when this was one flat module.
# It is the same module object `.probes` imports, so patching either
# reference mutates the one shared `httpx` module.
import httpx  # noqa: F401

from .blocks import PRESERVATION_ALLOWED_FIELDS
from .config import build_dependency_specs, load_health_prober
from .prober import DependencySpec, HealthProber
from .probes import (
    DEFAULT_CACHE_TTL_S,
    DEFAULT_PROBE_TIMEOUT_S,
    DEGRADED,
    DOWN,
    NOT_CONFIGURED,
    UP,
    nous_health_probe,
    probe_chat_llm,
    probe_chatterbox,
    probe_qdrant,
    probe_redis,
    probe_speaches,
    probe_state_encryption,
)

__all__ = [
    "UP",
    "DOWN",
    "DEGRADED",
    "NOT_CONFIGURED",
    "DEFAULT_PROBE_TIMEOUT_S",
    "DEFAULT_CACHE_TTL_S",
    "PRESERVATION_ALLOWED_FIELDS",
    "DependencySpec",
    "HealthProber",
    "build_dependency_specs",
    "load_health_prober",
    "nous_health_probe",
    "probe_redis",
    "probe_qdrant",
    "probe_chat_llm",
    "probe_speaches",
    "probe_chatterbox",
    "probe_state_encryption",
]
