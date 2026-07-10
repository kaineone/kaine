# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Runtime-backend resolution shared by every heavy organ.

KAINE's per-cycle cost is dominated by a few heavy models; the portability
cliff is the *runtime* those models need, not the accelerator. A workstation
runs the torch/transformers/funasr stack; a ~512 MB-class single-board computer
needs the GGML/ONNX family (llama.cpp, whisper.cpp, sqlite-vec, ONNX Runtime).
Each heavy module therefore selects its model runtime through a
``[<module>].backend`` config key resolved *behind* the module's existing
internal client interface — the module body, its bus subscriptions, and its
published event shapes are unchanged; only which implementation realizes the
organ differs (openspec ``runtime-backends``).

This module is the small, reusable seam that does the selecting. Two contracts
it enforces so a tier install stays lean and a boot never crashes:

* **Lazy import.** A backend's third-party dependency is imported only inside
  its factory, so selecting the Ollama backend never imports ``llama_cpp`` and
  vice versa. Backends are registered as *factory callables*, never as eagerly
  imported classes.

* **Degrade, do not crash.** :func:`resolve_backend` attempts the configured
  backend; on ``ImportError`` / load error it either falls back to a declared
  lighter backend or returns ``None`` (module disables itself). In both cases it
  records a structured, surfaced reason via
  :func:`kaine.backend_state.record_backend_failure` — a removed capability is
  reported, never silent — and does not raise into the boot path.

This file depends only on :mod:`kaine.backend_state` (boundary-neutral) and the
stdlib, so any module factory can reuse it.
"""
from __future__ import annotations

import logging
from typing import Callable, Generic, Optional, TypeVar

from kaine.backend_state import record_backend_failure

log = logging.getLogger(__name__)

T = TypeVar("T")

#: A backend factory: constructs and returns the concrete client. It may raise
#: ``ImportError`` (missing third-party dependency) or any load error; both are
#: caught by :func:`resolve_backend` and turned into a structured failure.
BackendFactory = Callable[[], T]


class UnknownBackendError(ValueError):
    """Raised when a ``[<module>].backend`` value names no registered backend.

    This is an operator *configuration* error (a typo'd backend name), distinct
    from a backend that is known but cannot load on this host — the latter
    degrades via :func:`resolve_backend` rather than raising.
    """


class BackendRegistry(Generic[T]):
    """A module's set of interchangeable runtime backends, keyed by name.

    Register each backend with a *factory* (a zero-arg callable that performs the
    lazy import and constructs the client). The default backend reproduces the
    current workstation ("Tier 2") behaviour, so a config with no ``backend`` key
    resolves exactly as today.
    """

    def __init__(self, module: str, *, default: str) -> None:
        self._module = str(module)
        self._default = str(default)
        self._factories: dict[str, BackendFactory[T]] = {}
        self._fallbacks: dict[str, str] = {}

    @property
    def module(self) -> str:
        return self._module

    @property
    def default(self) -> str:
        return self._default

    def register(
        self,
        name: str,
        factory: BackendFactory[T],
        *,
        fallback: Optional[str] = None,
    ) -> "BackendRegistry[T]":
        """Register a backend ``name`` built by ``factory``.

        ``fallback`` names a lighter backend to try if this one fails to load;
        omit it (or pass ``None``) to disable the module instead of degrading.
        Returns self for chaining.
        """
        self._factories[str(name)] = factory
        if fallback is not None:
            self._fallbacks[str(name)] = str(fallback)
        return self

    def names(self) -> list[str]:
        return sorted(self._factories)

    def resolve(self, selected: Optional[str]) -> Optional[T]:
        """Build the selected backend, degrading rather than crashing.

        ``selected`` is the ``[<module>].backend`` value, or ``None`` to use the
        registered default. Returns the constructed client, or ``None`` when the
        selected backend (and any declared fallback chain) cannot load — in which
        case the caller disables the module. Every failure is recorded and
        surfaced.
        """
        return resolve_backend(self, selected)


def resolve_backend(registry: BackendRegistry[T], selected: Optional[str]) -> Optional[T]:
    """Resolve ``selected`` against ``registry``, following the fallback chain.

    Attempts the selected backend's factory; on load failure records a structured
    reason and recurses into the declared fallback. Returns ``None`` when the
    chain is exhausted (module disables itself). Never raises on a load failure;
    only an *unknown* backend name raises :class:`UnknownBackendError`.
    """
    name = (selected or registry.default).strip() or registry.default
    return _resolve_chain(registry, name, seen=set())


def _resolve_chain(
    registry: BackendRegistry[T], name: str, *, seen: set[str]
) -> Optional[T]:
    if name in seen:
        # A cyclic fallback declaration — stop rather than loop forever.
        record_backend_failure(
            registry.module,
            name,
            "cyclic backend fallback declaration",
        )
        return None
    seen.add(name)
    factory = registry._factories.get(name)
    if factory is None:
        raise UnknownBackendError(
            f"[{registry.module}].backend = {name!r} is not a known backend "
            f"(registered: {registry.names()})"
        )
    fallback = registry._fallbacks.get(name)
    try:
        return factory()
    except Exception as exc:  # noqa: BLE001 — intentional: any load error degrades
        reason = f"{type(exc).__name__}: {exc}"
        record_backend_failure(
            registry.module, name, reason, fallback=fallback
        )
        if fallback is None:
            return None
        log.info(
            "%s backend %r unavailable; trying fallback %r",
            registry.module,
            name,
            fallback,
        )
        return _resolve_chain(registry, fallback, seen=seen)
