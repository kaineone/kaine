# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""The substrate broker: share one 64-channel array across converted modules.

KAINE's silicon modules never contend for their models; on CL1 the resource is
scarce and shared: 64 channels, one culture, one closed loop. The broker is the
multiplexer:

- **Channel allocation.** Each module leases a disjoint block of the 64 channels,
  fixed for the run. The sum cannot exceed 64 (enforced at allocation).
- **One closed loop.** The broker runs the single `neurons.loop(...)`.
- **Windows.** Before beat mode, each consumer step runs one `_span`-frame window,
  delivering queued stim at the start and returning one observation per territory.
  In beat mode (KAINE's cycle hook), exactly one window closes per processing tick
  on a background thread. Consumers queue stim for the next window through
  `exchange()` and read their territory's latest window; the cycle hook never waits
  on the substrate.
- **Health.** `coalesced_beats`, `failed`, and `broken` expose the beat thread state
  for diagnostics.

See `openspec/changes/wetware-substrate-foundation/`.
"""
from __future__ import annotations

import dataclasses
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from kaine_cl1.substrate.codec import StimRequest

log = logging.getLogger(__name__)

_CHANNELS_TOTAL = 64  # matches cl.ChannelSet._CHANNELS_TOTAL in the simulator


def nesting_factor_for(ticks_per_second: int, cognitive_rate: float) -> int:
    """Substrate sub-ticks per cognitive tick. Requires an ~integer nesting."""
    n = ticks_per_second / cognitive_rate
    r = round(n)
    if r < 1 or abs(n - r) > 0.05:
        raise ValueError(
            f"substrate ticks_per_second ({ticks_per_second}) must be an integer "
            f"multiple of the cognitive rate ({cognitive_rate}); got {n:.3f}"
        )
    return r


@dataclass(frozen=True)
class ChannelTerritory:
    """A disjoint block of electrodes leased to one module for a run."""

    module: str
    channels: tuple[int, ...]


@dataclass(frozen=True)
class TerritoryObservation:
    """One cognitive tick's aggregated response on a module's territory."""

    module: str
    channels: tuple[int, ...]
    spikes: list[Any]
    from_timestamp: int
    frame_count: int
    #: The caller's tag of the stimulation this window answers (tagged exchanges only).
    tag: Any = None


class OversubscribedError(RuntimeError):
    """Raised when channel allocations would exceed the 64-electrode array."""


@dataclass
class SubstrateBroker:
    """Allocates territories and drives the single closed loop."""

    channel_count: int = _CHANNELS_TOTAL
    ticks_per_second: int = 100
    nesting_factor: int = 30
    #: Channels withheld from every territory. Channel 0 is reserved because the
    #: vendored simulator silently swallows stimulation delivered to it (a
    #: 0-is-falsy quirk in the SDK stim path: `ChannelSet(0)` stims never commit
    #: and never evoke), so no module may depend on stimulating it. Verified in
    #: tests/test_foundation_sim.py::test_channel_zero_is_unstimulable.
    reserved_channels: frozenset[int] = frozenset({0})
    _territories: dict[str, ChannelTerritory] = field(default_factory=dict)
    _free: list[int] = field(default_factory=list)
    _pending: dict[str, list[StimRequest]] = field(default_factory=dict)
    _neurons: Any = None
    _loop_it: Any = None
    _span: int = 0
    _cursor: Any = None
    _spillover: list[Any] = field(default_factory=list)
    _beat_mode: bool = field(default=False, repr=False)
    _accelerated: bool = field(default=True, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    #: Serialises synchronous (pre-beat) windows and the switch to beat mode across threads:
    #: Nous steps its engine in a worker thread while Chronos and Soma step on the event loop.
    _sync_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _latest: dict[str, TerritoryObservation] = field(default_factory=dict, repr=False)
    _next: dict[str, list[StimRequest]] = field(default_factory=dict, repr=False)
    _next_tags: dict[str, Any] = field(default_factory=dict, repr=False)
    _latest_response: dict[str, TerritoryObservation] = field(default_factory=dict, repr=False)
    _pending_frames: int | None = field(default=None, repr=False)
    _coalesced: int = field(default=0, repr=False)
    _beat_signal: threading.Event = field(default_factory=threading.Event, repr=False)
    _boundary: threading.Event = field(default_factory=threading.Event, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _failed: bool = field(default=False, repr=False)
    _broken: bool = field(default=False, repr=False)
    _thread: Any = None
    _last_beat_at: float | None = field(default=None, repr=False)
    _period_s: float = field(default=0.1, repr=False)
    _discarded_stim: int = field(default=0, repr=False)
    _rt_overruns: int = field(default=0, repr=False)
    _fps: int = field(default=25000, repr=False)

    def __post_init__(self) -> None:
        if not self._free:
            self._free = [
                c for c in range(self.channel_count) if c not in self.reserved_channels
            ]

    # -- allocation (pure) ------------------------------------------------------
    def allocate(self, module: str, count: int) -> ChannelTerritory:
        with self._lock:
            if module in self._territories:
                raise ValueError(f"module {module!r} already has a territory")
            if count <= 0:
                raise ValueError("territory size must be positive")
            if count > len(self._free):
                raise OversubscribedError(
                    f"cannot lease {count} channels to {module!r}: only "
                    f"{len(self._free)} of {self.channel_count} remain "
                    f"(64-electrode array is the hard ceiling)"
                )
            leased = tuple(self._free[:count])
            self._free = self._free[count:]
            territory = ChannelTerritory(module=module, channels=leased)
            self._territories[module] = territory
            return territory

    def _territories_snapshot(self) -> dict[str, ChannelTerritory]:
        with self._lock:
            return dict(self._territories)

    def territory(self, module: str) -> ChannelTerritory:
        return self._territories[module]

    def has_territory(self, module: str) -> bool:
        """Return whether the module currently holds a territory."""
        return module in self._territories

    def discard_pending(self, module: str) -> None:
        """Remove any stimulation queued for the module."""
        self._pending.pop(module, None)

    def territory_map(self) -> dict[str, tuple[int, ...]]:
        """The full lease map, recorded into the run manifest for reproducibility."""
        return {m: t.channels for m, t in self._territories.items()}

    # -- spike routing (pure) ---------------------------------------------------
    def route(
        self, spikes: Iterable, territories: dict[str, ChannelTerritory] | None = None
    ) -> dict[str, list]:
        territories = self._territories if territories is None else territories
        owner = {ch: m for m, t in territories.items() for ch in t.channels}
        out: dict[str, list] = {m: [] for m in territories}
        for s in spikes:
            m = owner.get(int(s.channel))
            if m is not None:
                out[m].append(s)
        return out

    # -- loop driving (integration) ---------------------------------------------
    def open(self, neurons: Any) -> None:
        self._neurons = neurons
        fps = int(neurons.get_frames_per_second())
        self._fps = fps
        frames_per_subtick = max(1, fps // self.ticks_per_second)
        # A cognitive tick spans exactly this many frames of the substrate
        # timeline. Aggregating by timestamp span (not by counting loop ticks)
        # is what makes the observation reproducible: the reference source is
        # deterministic per timestamp, and accelerated-mode `loop()` chunks
        # frames-per-tick nondeterministically.
        self._span = self.nesting_factor * frames_per_subtick
        self._cursor = None
        self._spillover = []
        self._loop_it = iter(neurons.loop(ticks_per_second=self.ticks_per_second))

    def _validate(self, module: str, requests: Sequence[StimRequest]) -> list[StimRequest]:
        if module not in self._territories:
            raise KeyError(f"module {module!r} has no territory")
        requests = list(requests)
        # The broker enforces territory isolation and finite currents before anything is queued.
        for req in requests:
            if req.channel not in self._territories[module].channels:
                raise ValueError(
                    f"module {module!r} may not stimulate channel {req.channel}: "
                    f"it is outside its territory {self._territories[module].channels}"
                )
            if not math.isfinite(req.amplitude_uA):
                raise ValueError(
                    f"module {module!r} queued a non-finite amplitude "
                    f"{req.amplitude_uA!r} on channel {req.channel}"
                )
        return requests

    def queue_stim(self, module: str, requests: Sequence[StimRequest]) -> None:
        reqs = self._validate(module, requests)
        self._pending.setdefault(module, []).extend(reqs)

    def _deliver_pending(self) -> None:
        if not self._pending:
            return
        for requests in self._pending.values():
            for req in requests:
                channel_set, design = req.to_cl()
                self._neurons.stim(channel_set, design)
        self._pending.clear()

    def _run_window(self, frames: int) -> dict[str, TerritoryObservation]:
        collected: list[Any] = list(self._spillover)
        self._spillover = []
        delivered = False
        while True:
            tick = next(self._loop_it)
            if self._cursor is None:
                self._cursor = int(tick.analysis.start_timestamp)
            if not delivered:
                self._deliver_pending()  # stim at the window start, inside the loop
                delivered = True
            collected.extend(tick.analysis.spikes)
            if int(tick.analysis.stop_timestamp) >= self._cursor + frames:
                break
        window_end = self._cursor + frames
        in_window = [s for s in collected if int(s.timestamp) < window_end]
        self._spillover = [s for s in collected if int(s.timestamp) >= window_end]
        from_ts = self._cursor
        self._cursor = window_end
        territories = self._territories_snapshot()
        routed = self.route(in_window, territories)
        return {
            module: TerritoryObservation(
                module=module,
                channels=t.channels,
                spikes=routed[module],
                from_timestamp=from_ts,
                frame_count=frames,
            )
            for module, t in territories.items()
        }

    def run_cognitive_tick(self) -> dict[str, TerritoryObservation]:
        """Advance one cognitive tick (a fixed `_span`-frame window), delivering
        queued stim at the window start, and return one aggregated observation per
        territory. Spikes past the window boundary are buffered for the next tick,
        so the per-tick spike set is a deterministic function of the timeline."""
        self._check_usable()
        if self._loop_it is None:
            raise RuntimeError("broker is not open; call open(neurons) first")
        with self._sync_lock:
            return self._run_window(self._span)

    # -- beat mode --------------------------------------------------------------
    def exchange(
        self, module: str, requests: Sequence[StimRequest], *, tag: Any = None
    ) -> TerritoryObservation:
        """Queue stimulation and return the latest territory observation.

        With ``tag`` set, the call returns the response window to this
        module's most recent tagged stimulation, carrying that
        stimulation's tag, rather than the latest window; before any tagged
        response exists it returns an empty observation with ``tag=None``.
        Before beat mode the window runs now, so its response carries this
        call's tag.
        """
        self._check_usable()
        reqs = self._validate(module, requests)
        if not self._beat_mode:
            with self._sync_lock:
                if not self._beat_mode:
                    self.queue_stim(module, reqs)
                    obs = self.run_cognitive_tick()[module]
                    if tag is None:
                        return obs
                    obs = dataclasses.replace(obs, tag=tag)
                    with self._lock:
                        self._latest_response[module] = obs
                    return obs
        with self._lock:
            self._next[module] = reqs
            if tag is None:
                self._next_tags.pop(module, None)
                latest = self._latest.get(module)
            else:
                self._next_tags[module] = tag
                latest = self._latest_response.get(module)
        if latest is None:
            return TerritoryObservation(
                module=module,
                channels=self._territories[module].channels,
                spikes=[],
                from_timestamp=-1,
                frame_count=0,
            )
        return TerritoryObservation(
            module=latest.module,
            channels=latest.channels,
            spikes=list(latest.spikes),
            from_timestamp=latest.from_timestamp,
            frame_count=latest.frame_count,
            tag=latest.tag,
        )

    def start_beat(self, *, accelerated: bool, blocking: bool = True) -> bool:
        """Switch to beat mode: one window per cycle tick on a background thread.

        Returns True once beat mode is running. With ``blocking=False`` it returns False instead
        of waiting when a synchronous window holds the substrate, so a caller on KAINE's event
        loop never waits for one.
        """
        if self._loop_it is None:
            raise RuntimeError("broker is not open; call open(neurons) first")
        self._check_usable()
        if self._beat_mode and self._thread is not None and self._thread.is_alive():
            return True
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("CL1 substrate beat thread is already running")
        if not self._sync_lock.acquire(blocking=blocking):
            return False
        try:
            if self._beat_mode and self._thread is not None and self._thread.is_alive():
                return True
            self._stop.clear()
            self._failed = False
            self._beat_signal.clear()
            # Treat a long gap from start (for example a boot-time freeze) like any other gap.
            self._last_beat_at = time.monotonic()
            self._beat_mode = True
            self._accelerated = accelerated
            with self._lock:
                for module, reqs in list(self._pending.items()):
                    self._next[module] = list(reqs)
                self._pending.clear()
            self._thread = threading.Thread(
                target=self._beat_loop,
                name="cl1-substrate-beat",
                daemon=True,
            )
            self._thread.start()
        finally:
            self._sync_lock.release()
        mode = "accelerated" if accelerated else "real time"
        log.info("CL1 substrate switched to beat mode (%s): one window per cycle tick", mode)
        return True

    def beat(self, period_s: float) -> None:
        self._check_usable()
        if not self._beat_mode:
            raise RuntimeError("broker is not in beat mode")
        now = time.monotonic()
        last = self._last_beat_at
        if last is not None and now - last > 2 * period_s:
            gap = now - last
            with self._lock:
                count = sum(len(v) for v in self._next.values())
                self._next.clear()
                self._next_tags.clear()
                self._pending_frames = None
            if count:
                self._discarded_stim += count
                log.warning(
                    "CL1 substrate discarded %d queued stimulation request(s) after a %.2f s gap "
                    "between cycle ticks (cycle frozen or stalled)",
                    count,
                    gap,
                )
        self._last_beat_at = now
        self._period_s = period_s
        if self._accelerated:
            frames = max(1, int(round(period_s * self._fps)))
            with self._lock:
                if self._pending_frames is not None:
                    self._coalesced += 1
                    if self._coalesced == 1 or self._coalesced % 100 == 0:
                        log.warning(
                            "CL1 substrate is behind the cycle: coalesced %d beat(s) so far; "
                            "substrate time is running slower than cognitive time",
                            self._coalesced,
                        )
                self._pending_frames = frames
                self._beat_signal.set()
        else:
            if self._boundary.is_set():
                self._rt_overruns += 1
                if self._rt_overruns == 1 or self._rt_overruns % 100 == 0:
                    log.warning(
                        "CL1 substrate (real time) is behind the cycle: %d beat(s) arrived before "
                        "the previous window closed",
                        self._rt_overruns,
                    )
            self._boundary.set()

    def _beat_loop(self) -> None:
        try:
            if self._accelerated:
                while not self._stop.is_set():
                    if not self._beat_signal.wait(timeout=0.1):
                        continue
                    self._beat_signal.clear()
                    with self._lock:
                        frames = self._pending_frames
                        self._pending_frames = None
                        if frames is None:
                            continue
                        self._pending = {m: list(r) for m, r in self._next.items()}
                        tags = dict(self._next_tags)
                        self._next.clear()
                        self._next_tags.clear()
                    obs = self._run_window(frames)
                    with self._lock:
                        self._latest.update(obs)
                        for m, t in tags.items():
                            if m in obs:
                                self._latest_response[m] = dataclasses.replace(obs[m], tag=t)
            else:
                collected: list[Any] = []
                window_start: int | None = None
                delivered_tags: dict[str, Any] = {}
                for tick in self._loop_it:
                    if self._stop.is_set():
                        break
                    collected.extend(tick.analysis.spikes)
                    if window_start is None:
                        window_start = int(tick.analysis.start_timestamp)
                    cap = max(1, int(round(self._period_s * self._fps)))
                    stop_ts = int(tick.analysis.stop_timestamp)
                    if stop_ts - window_start > 2 * cap:
                        collected = [s for s in collected if int(s.timestamp) >= stop_ts - cap]
                        window_start = stop_ts - cap
                    if self._boundary.is_set():
                        self._boundary.clear()
                        stop_ts = int(tick.analysis.stop_timestamp)
                        assert window_start is not None
                        territories = self._territories_snapshot()
                        routed = self.route(collected, territories)
                        obs = {
                            module: TerritoryObservation(
                                module=module,
                                channels=t.channels,
                                spikes=routed.get(module, []),
                                from_timestamp=window_start,
                                frame_count=stop_ts - window_start,
                            )
                            for module, t in territories.items()
                        }
                        with self._lock:
                            self._latest.update(obs)
                            for m, t in delivered_tags.items():
                                if m in obs:
                                    self._latest_response[m] = dataclasses.replace(
                                        obs[m], tag=t
                                    )
                            delivered_tags = dict(self._next_tags)
                            self._next_tags.clear()
                            snapshot = {m: list(r) for m, r in self._next.items()}
                            self._next.clear()
                        for requests in snapshot.values():
                            for req in requests:
                                self._neurons.stim(*req.to_cl())
                        collected = []
                        window_start = stop_ts
        except Exception:
            log.exception("CL1 substrate beat loop stopped")
            self._failed = True

    def stop_beat(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                log.warning(
                    "CL1 substrate beat thread did not stop within %.1f s; "
                    "the broker is now unusable",
                    timeout,
                )
                self._broken = True
                return
        self._thread = None
        self._beat_mode = False

    def _check_usable(self) -> None:
        if self._failed:
            raise RuntimeError(
                "CL1 substrate beat loop has stopped after an error; see the earlier log"
            )
        if self._broken:
            raise RuntimeError("CL1 substrate broker is broken; open a new session")

    @property
    def beat_mode(self) -> bool:
        """Whether the broker is currently running in beat mode."""
        return self._beat_mode

    @property
    def coalesced_beats(self) -> int:
        """Number of accelerated beats coalesced because a window was pending."""
        return self._coalesced

    @property
    def discarded_stim(self) -> int:
        """Number of queued stimulation requests discarded after a frozen cycle tick."""
        return self._discarded_stim

    @property
    def realtime_overruns(self) -> int:
        """Number of real-time beats that arrived before the previous window closed."""
        return self._rt_overruns

    @property
    def failed(self) -> bool:
        """Whether the beat loop stopped after an unhandled exception."""
        return self._failed

    @property
    def broken(self) -> bool:
        """Whether stop_beat timed out and the broker is no longer usable."""
        return self._broken
