# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The shared subjective clock for the entity's mind.

Every module that times a *cognitive* process (the cognitive-cycle tick pacing,
fatigue accumulation, perception sampling cadence, attentional locus dwell,
drive/affect time constants, recall throttling) derives its "now" and its
durations from one injected ``EntityClock`` instead of reading the wall clock
directly. The clock exposes the entity's **subjective** time as

    subjective = origin + (wall_elapsed) * time_scale

so a single ``time_scale`` knob dilates the entire mind coherently and no two
cognitive timers desynchronize from each other:

    time_scale == 1.0   real-time (the shipped default; behavior-identical)
    time_scale  < 1.0   deliberately slowed subjective time
    time_scale  > 1.0   dilated-fast (an aspirational target — the cycle attempts
                        the faster rate and throttles honestly when the hardware
                        cannot hold it; see the cognitive-cycle slip measurement)
    time_scale == 0     frozen — the subjective clock stops. Freeze is driven by
                        the existing pause/suspend path (``control_state.py``);
                        this clock does not invent a second freeze. ``sleep`` at
                        scale 0 is a no-op (see ``sleep`` below).

Infrastructure timers that must track *real* wall-clock time regardless of the
entity's subjective rate — the Spot liveness watchdog, the preservation monitor
poll, network request timeouts, the voice-alignment GPU window — deliberately do
NOT use this clock (a watchdog must not slow down because the mind sped up, nor
speed up because it slowed). Wiring those cognitive-vs-infrastructural sites is
Phase 2; this module is the Phase 1 primitive.

Boundary-neutral: this module imports nothing from ``kaine.cycle`` or
``kaine.modules`` so it can be injected anywhere without an import-cycle. The
real clock and real sleep are injectable so tests run deterministically.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable


class EntityClock:
    """The single source of the entity's subjective time and durations.

    ``wall()`` is the real monotonic clock (for slip/health only). ``now()`` is
    subjective seconds. ``scale`` is the ``time_scale`` multiplier. ``sleep`` and
    ``period`` translate between subjective and real time. The real clock and
    real sleep are injectable for deterministic tests.
    """

    def __init__(
        self,
        *,
        scale: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
        real_sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        origin: float = 0.0,
    ) -> None:
        if scale < 0:
            raise ValueError("time_scale must be >= 0 (0 = frozen)")
        self._scale = float(scale)
        self._monotonic = monotonic
        self._real_sleep = real_sleep
        # The wall reading at construction anchors subjective time so that
        # now() starts at `origin` and advances at `scale` × real time.
        self._wall_origin = self._monotonic()
        self._origin = float(origin)

    # -- real (infrastructural) time ---------------------------------------

    def wall(self) -> float:
        """Real monotonic seconds. For slip/health/latency only — never for
        cognitive timing. Unaffected by ``time_scale``."""
        return self._monotonic()

    # -- subjective (cognitive) time ---------------------------------------

    def now(self) -> float:
        """Subjective seconds = ``origin + (wall_elapsed) * time_scale``.

        At ``scale == 0`` this stops advancing (the frozen entity's subjective
        clock is stopped); at ``scale == 1`` it tracks real elapsed time.
        """
        return self._origin + (self._monotonic() - self._wall_origin) * self._scale

    @property
    def scale(self) -> float:
        """The ``time_scale``: 0 = frozen, 1.0 = real-time, >1 = dilated-fast."""
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        if value < 0:
            raise ValueError("time_scale must be >= 0 (0 = frozen)")
        # Re-anchor so subjective time is continuous across a scale change: the
        # subjective `now()` already reached stays put and only its future rate
        # changes (no jump). This keeps cognitive integrals coherent when an
        # operator dilates a running mind.
        self._origin = self.now()
        self._wall_origin = self._monotonic()
        self._scale = float(value)

    def period(self, hz: float) -> float:
        """Real seconds per subjective-Hz tick = ``1 / (hz * scale)``.

        A ``hz``-rate event in *subjective* time happens every ``1/hz``
        subjective seconds, which is ``1/(hz*scale)`` real seconds. Raises at
        ``scale == 0`` (a frozen entity has no finite tick period — it is frozen
        via the pause path, not paced).
        """
        if hz <= 0:
            raise ValueError("hz must be positive")
        if self._scale <= 0:
            raise ValueError("period is undefined at time_scale 0 (frozen)")
        return 1.0 / (hz * self._scale)

    async def sleep(self, subjective_s: float) -> None:
        """Await a real sleep of ``subjective_s / scale`` real seconds.

        Sleeping for ``subjective_s`` subjective seconds takes ``subjective_s /
        scale`` real seconds (half the scale ⇒ twice the real wait). At
        ``scale == 0`` the entity is frozen via the existing pause path — there
        is no forward subjective time to wait out — so ``sleep`` is a **no-op**
        rather than a divide-by-zero. (The cycle never paces at scale 0: it is
        suspended on ``_paused.wait()``; a stray ``sleep(…)`` call must not crash
        or block forever, so we return immediately and let the pause gate hold
        the loop.)
        """
        if self._scale <= 0:
            # Frozen: no subjective time elapses; the pause path holds the loop.
            return
        await self._real_sleep(subjective_s / self._scale)
