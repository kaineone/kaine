# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Apply a fork's subjective-time profile at spawn (Phase 4 of biological timing).

When a fork carrying a :class:`~kaine.lifecycle.timing_profile.ForkTimingProfile`
is restored to run, the runtime applies that profile so the being runs at its own
subjective speed. This seam owns the wiring between the *parsed* profile (a pure
lifecycle data object) and the *runtime* it must touch — the shared
``EntityClock`` and the ``CognitiveCycle`` — which is why it lives in
``kaine.cycle`` (the runtime layer that may legally import the clock, the cycle,
and the Topos perception knob) rather than in the boundary-neutral lifecycle
profile module.

It reuses **only existing seams** — it introduces no new throttle, freeze, or
rate mechanism:

- ``EntityClock.scale`` setter (Phase 1) — re-anchors subjective time, so
  applying a scale to a just-restored fork does not jump its cognitive integrals.
- ``CognitiveCycle.set_processing_rate`` / ``set_experiential_rate`` (Phase 1's
  single unified rate setters) for the optional rate overrides.
- ``LiveCamera.set_vision_sample_hz`` (Phase 3's vision knob) for the optional
  perception-rate override.

A ``time_scale > 1`` keeps the existing aspirational-target-then-throttle
semantics: the cycle attempts the faster real rate and the Phase-3 pacing report
+ Soma ``reduce_rate`` honestly surface/throttle an overrun. This seam adds no
second throttle.

It is a deliberate **no-op for a profile-less fork** (``profile is None``), so a
fork with no timing profile changes neither the clock scale nor the cycle rates —
the behavior-preserving default for every fork today.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from kaine.lifecycle.timing_profile import ForkTimingProfile

log = logging.getLogger(__name__)


@runtime_checkable
class _ClockLike(Protocol):
    @property
    def scale(self) -> float:
        """The subjective time_scale."""

    @scale.setter
    def scale(self, value: float) -> None:
        """Set the subjective time_scale."""


@runtime_checkable
class _CycleLike(Protocol):
    def set_processing_rate(self, hz: float) -> None:
        """Set the processing (workspace tick) rate in Hz."""

    def set_experiential_rate(self, hz: float) -> None:
        """Set the experiential broadcast rate in Hz."""


@runtime_checkable
class _VisionRateSink(Protocol):
    def set_vision_sample_hz(self, vision_sample_hz: float) -> None:
        """Set the perception (vision) sample rate in Hz."""


def _resolve_vision_sink(vision_rate_sink: Any) -> _VisionRateSink | None:
    """Find an object exposing ``set_vision_sample_hz`` on the given handle.

    The runtime may pass the Topos module, its ``LiveCamera`` directly, or any
    object with a ``live_camera`` attribute. We probe those in order and return
    the first that exposes the vision-rate knob, or ``None`` when no clean
    runtime seam is reachable (so the caller can honestly record the limitation
    instead of faking the override).
    """
    if vision_rate_sink is None:
        return None
    if isinstance(vision_rate_sink, _VisionRateSink):
        return vision_rate_sink
    for attr in ("live_camera", "_live_camera"):
        candidate = getattr(vision_rate_sink, attr, None)
        if isinstance(candidate, _VisionRateSink):
            return candidate
    return None


def apply_fork_timing_profile(
    profile: ForkTimingProfile | None,
    entity_clock: _ClockLike,
    cycle: _CycleLike,
    *,
    vision_rate_sink: Any | None = None,
) -> dict[str, Any]:
    """Apply a fork's timing profile to the running clock + cycle at spawn.

    Wire this where a fork is restored-to-run, AFTER ``ForkManager.restore(...)``
    has rehydrated module state (restore deliberately does not touch the
    clock/cycle, so this is the seam that does).

    Parameters
    ----------
    profile:
        The validated profile (from
        :func:`kaine.lifecycle.timing_profile.fork_timing_profile`), or ``None``
        for a profile-less fork.
    entity_clock:
        The shared ``EntityClock`` (its ``scale`` setter re-anchors subjective
        time).
    cycle:
        The ``CognitiveCycle`` (its single ``set_processing_rate`` /
        ``set_experiential_rate`` setters apply rate overrides).
    vision_rate_sink:
        Optional handle exposing (or owning) ``set_vision_sample_hz`` — the
        running Topos module or its ``LiveCamera``. When the running config does
        not expose a vision-rate seam, the ``vision_sample_hz`` override is
        honestly reported as not-applied rather than faked.

    Returns
    -------
    A summary dict for logging / Nexus. For a profile-less fork it is
    ``{"applied": False, ...}`` and nothing is mutated.
    """
    if profile is None:
        return {
            "applied": False,
            "time_scale": None,
            "processing_rate_hz": None,
            "experiential_rate_hz": None,
            "vision_sample_hz": None,
        }

    summary: dict[str, Any] = {
        "applied": True,
        "time_scale": profile.time_scale,
        "processing_rate_hz": None,
        "experiential_rate_hz": None,
        "vision_sample_hz": None,
    }

    # 1) Subjective time scale — the existing re-anchoring setter (Phase 1).
    entity_clock.scale = profile.time_scale

    # 2) Optional rate overrides through the existing single setters (Phase 1).
    if profile.processing_rate_hz is not None:
        cycle.set_processing_rate(profile.processing_rate_hz)
        summary["processing_rate_hz"] = profile.processing_rate_hz
    if profile.experiential_rate_hz is not None:
        cycle.set_experiential_rate(profile.experiential_rate_hz)
        summary["experiential_rate_hz"] = profile.experiential_rate_hz

    # 3) Optional perception-rate override through the existing Topos knob
    #    (Phase 3). If no clean runtime seam is reachable on the running config,
    #    record the limitation honestly rather than pretend it was applied.
    if profile.vision_sample_hz is not None:
        sink = _resolve_vision_sink(vision_rate_sink)
        if sink is not None:
            sink.set_vision_sample_hz(profile.vision_sample_hz)
            summary["vision_sample_hz"] = profile.vision_sample_hz
        else:
            summary["vision_sample_hz"] = None
            summary["vision_sample_hz_unapplied"] = profile.vision_sample_hz
            log.warning(
                "fork timing profile requested vision_sample_hz=%.3f but no "
                "runtime vision-rate seam was reachable; not applied",
                profile.vision_sample_hz,
            )

    log.info("applied fork timing profile: %s", summary)
    return summary
