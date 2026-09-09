# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Canonical module-stream registry — the single source of truth for the
``<module>.out`` stream set, so the research-event observer, the raw bus
archive, and the nexus monitor never drift (shared-logic precedent:
welfare_observer.py re-exports the welfare signal core for the same reason).

Stream names are derived from registered module names via
``kaine.bus.schema.module_stream`` (import-boundary contract: kaine.modules
must never import kaine.evaluation, and this registry must not import
kaine.modules — hence the static name tuple below; the drift tests compare it
against the real module packages from the test side, where both imports are
allowed).

Documented exclusions:

- Lingua has NO single ``lingua.out``: it deliberately splits into
  ``lingua.external`` / ``lingua.internal`` (kaine/modules/lingua/module.py),
  so every stream list replaces ``lingua.out`` with that split.
- Curated research log: ``vox.out`` (raw audio content) and Lingua streams
  (transcripts) are NEVER curated — the research log stays content-free.
- Nexus diagnostics additionally excludes the low-signal operational streams
  (``volition.out``, ``mundus.out``, ``perception.out``, ``welfare.out``,
  ``preservation.out``, ``individuation.out``) and adds non-module streams
  (``cycle.tick`` event type, ``workspace.broadcast``).
"""

from __future__ import annotations

from kaine.bus.schema import module_stream

#: Every cognitive module that publishes a stream. Order is stable.
CANONICAL_MODULE_NAMES: tuple[str, ...] = (
    "cycle",
    "volition",
    "soma",
    "chronos",
    "topos",
    "phantasia",
    "nous",
    "thymos",
    "audition",
    "lingua",
    "vox",
    "mnemos",
    "hypnos",
    "eidolon",
    "empatheia",
    "praxis",
    "spot",
    "perception",
    "mundus",
    "welfare",
    "preservation",
    "individuation",
)

#: Lingua's deliberate split — there is no single ``lingua.out`` producer.
LINGUA_STREAMS: tuple[str, ...] = ("lingua.external", "lingua.internal")

#: Streams with content-bearing payloads that are never curated.
_CURATED_EXCLUSIONS: frozenset[str] = frozenset({"lingua.out", "vox.out"})

#: Operational streams the nexus diagnostics monitor does not tail.
#: (``lingua.out`` is NOT excluded — it is split into
#: ``lingua.external`` / ``lingua.internal``, which diagnostics tails;
#: ``cycle.out`` is excluded in favor of the ``cycle.tick`` event type.)
_DIAGNOSTICS_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "cycle.out",
        "volition.out",
        "mundus.out",
        "perception.out",
        "welfare.out",
        "preservation.out",
        "individuation.out",
    }
)


def canonical_module_streams() -> tuple[str, ...]:
    """The canonical ``<module>.out`` set (Lingua NOT yet split here)."""
    return tuple(module_stream(name) for name in CANONICAL_MODULE_NAMES)


def _expand(stream: str) -> tuple[str, ...]:
    return LINGUA_STREAMS if stream == "lingua.out" else (stream,)


def curated_module_streams() -> tuple[str, ...]:
    """Curated research-log streams: canonical set minus content streams."""
    return tuple(
        s
        for s in canonical_module_streams()
        if s not in _CURATED_EXCLUSIONS
    )


def raw_archive_module_streams() -> tuple[str, ...]:
    """Raw archive streams: the full canonical set, with Lingua split."""
    return tuple(
        sub for s in canonical_module_streams() for sub in _expand(s)
    )


def diagnostics_streams() -> tuple[str, ...]:
    """Nexus diagnostics streams: filtered module streams plus non-module
    extras (the ``cycle.tick`` event type and ``workspace.broadcast``)."""
    module_part = tuple(
        sub
        for s in canonical_module_streams()
        if s not in _DIAGNOSTICS_EXCLUSIONS
        for sub in _expand(s)
    )
    return ("cycle.tick",) + module_part + ("workspace.broadcast",)
