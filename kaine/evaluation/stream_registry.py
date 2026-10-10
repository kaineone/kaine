# SPDX-License-Identifier: LicenseRef-CAL-0.4
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

- Curated research log: ``vox.out`` (raw audio content) and ``lingua.out``
  (transcripts) are NEVER curated — the research log stays content-free.
- Nexus diagnostics additionally excludes the low-signal operational streams
  (``volition.out``, ``mundus.out``, ``perception.out``, ``welfare.out``,
  ``preservation.out``, ``individuation.out``) and adds the non-module
  ``workspace.broadcast`` stream. It tails ``cycle.out``, which carries the
  cycle's ``cycle.tick``, ``cycle.rates`` and ``cycle.time_scale`` events.
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

#: Streams with content-bearing payloads that are never curated.
_CURATED_EXCLUSIONS: frozenset[str] = frozenset({"lingua.out", "vox.out"})

#: Operational streams the nexus diagnostics monitor does not tail.
#: ``cycle.out`` carries the cycle's operational events (``cycle.tick``,
#: ``cycle.rates``, ``cycle.time_scale``) and Nexus tails it.
_DIAGNOSTICS_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "volition.out",
        "mundus.out",
        "perception.out",
        "welfare.out",
        "preservation.out",
        "individuation.out",
    }
)

#: Additional module-produced streams that are not ``<module>.out``.
_ADDITIONAL_PRODUCED_STREAMS: tuple[str, ...] = ("volition_feedback.out",)


def canonical_module_streams() -> tuple[str, ...]:
    """The canonical ``<module>.out`` set."""
    return tuple(module_stream(name) for name in CANONICAL_MODULE_NAMES)


def _all_produced_streams() -> tuple[str, ...]:
    """Canonical module streams plus additional produced streams."""
    return canonical_module_streams() + _ADDITIONAL_PRODUCED_STREAMS


def curated_module_streams() -> tuple[str, ...]:
    """Curated research-log streams: produced streams minus content streams."""
    return tuple(s for s in _all_produced_streams() if s not in _CURATED_EXCLUSIONS)


def raw_archive_module_streams() -> tuple[str, ...]:
    """Raw archive streams: the full produced set."""
    return _all_produced_streams()


def diagnostics_streams() -> tuple[str, ...]:
    """Nexus diagnostics streams: filtered module streams plus non-module
    extras (``workspace.broadcast``)."""
    module_part = tuple(s for s in canonical_module_streams() if s not in _DIAGNOSTICS_EXCLUSIONS)
    return module_part + ("workspace.broadcast",)
