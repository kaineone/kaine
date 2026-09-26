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

See `openspec/changes/wetware-substrate-foundation/`.
"""
from __future__ import annotations

import logging
import math
import queue
import threading
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
    _latest: dict[str, TerritoryObservation] = field(default_factory=dict, repr=False)
    _next: dict[str, list[StimRequest]] = field(default_factory=dict, repr=False)
    _beats: queue.Queue[int] = field(default_factory=queue.Queue, repr=False)
    _boundary: threading.Event = field(default_factory=threading.Event, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: Any = None
    _fps: int = field(default=25000, repr=False)

    def __post_init__(self) -> None:
        if not self._free:
            self._free = [
                c for c in range(self.channel_count) if c not in self.reserved_channels
            ]

    # -- allocation (pure) ------------------------------------------------------
    def allocate(self, module: str, count: int) -> ChannelTerritory:
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
    def route(self, spikes: Iterable) -> dict[str, list]:
        owner = {ch: m for m, t in self._territories.items() for ch in t.channels}
        out: dict[str, list] = {m: [] for m in self._territories}
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
        routed = self.route(in_window)
        return {
            module: TerritoryObservation(
                module=module,
                channels=t.channels,
                spikes=routed[module],
                from_timestamp=from_ts,
                frame_count=frames,
            )
            for module, t in self._territories.items()
        }

    def run_cognitive_tick(self) -> dict[str, TerritoryObservation]:
        """Advance one cognitive tick (a fixed `_span`-frame window), delivering
        queued stim at the window start, and return one aggregated observation per
        territory. Spikes past the window boundary are buffered for the next tick,
        so the per-tick spike set is a deterministic function of the timeline."""
        if self._loop_it is None:
            raise RuntimeError("broker is not open; call open(neurons) first")
        return self._run_window(self._span)

    # -- beat mode --------------------------------------------------------------
    def exchange(self, module: str, requests: Sequence[StimRequest]) -> TerritoryObservation:
        reqs = self._validate(module, requests)
        if not self._beat_mode:
            self.queue_stim(module, reqs)
            return self.run_cognitive_tick()[module]
        with self._lock:
            self._next[module] = reqs
        latest = self._latest.get(module)
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
        )

    def start_beat(self, *, accelerated: bool) -> None:
        if self._loop_it is None:
            raise RuntimeError("broker is not open; call open(neurons) first")
        if self._beat_mode:
            return
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
        mode = "accelerated" if accelerated else "real time"
        log.info("CL1 substrate switched to beat mode (%s): one window per cycle tick", mode)

    def beat(self, period_s: float) -> None:
        if not self._beat_mode:
            raise RuntimeError("broker is not in beat mode")
        if self._accelerated:
            self._beats.put(max(1, int(round(period_s * self._fps))))
        else:
            self._boundary.set()

    def _beat_loop(self) -> None:
        try:
            if self._accelerated:
                while not self._stop.is_set():
                    try:
                        frames = self._beats.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    with self._lock:
                        self._pending = {m: list(r) for m, r in self._next.items()}
                        self._next.clear()
                    obs = self._run_window(frames)
                    with self._lock:
                        self._latest.update(obs)
            else:
                collected: list[Any] = []
                window_start: int | None = None
                for tick in self._loop_it:
                    if self._stop.is_set():
                        break
                    collected.extend(tick.analysis.spikes)
                    if window_start is None:
                        window_start = int(tick.analysis.start_timestamp)
                    if self._boundary.is_set():
                        self._boundary.clear()
                        stop_ts = int(tick.analysis.stop_timestamp)
                        assert window_start is not None
                        routed = self.route(collected)
                        obs = {
                            module: TerritoryObservation(
                                module=module,
                                channels=t.channels,
                                spikes=routed.get(module, []),
                                from_timestamp=window_start,
                                frame_count=stop_ts - window_start,
                            )
                            for module, t in self._territories.items()
                        }
                        with self._lock:
                            self._latest.update(obs)
                            snapshot = {m: list(r) for m, r in self._next.items()}
                            self._next.clear()
                        for requests in snapshot.values():
                            for req in requests:
                                self._neurons.stim(*req.to_cl())
                        collected = []
                        window_start = stop_ts
        except Exception:
            log.exception("CL1 substrate beat loop stopped")

    def stop_beat(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None
        self._beat_mode = False

    @property
    def beat_mode(self) -> bool:
        return self._beat_mode
