# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Callable, ClassVar, Mapping, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.affect.appraisal import (
    AppraisalScores,
    CategoricalEmotion,
    classify,
)
from kaine.modules.affect.coupling import (
    EMOTION_VAD,
    CouplingConfig,
    compute_coupling,
)
from kaine.modules.affect.drives import DriveSet
from kaine.modules.affect.goals import GoalLedger, GoalState
from kaine.modules.affect.modulator import StateModulator
from kaine.modules.affect.regulation import (
    PassiveDecay,
    RegulationPolicy,
    ThreeTierRegulation,
)
from kaine.modules.affect.state import DimensionalState
from kaine.modules.base import BaseModule

log = logging.getLogger(__name__)


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _clip(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v):
        return None
    return v


class Affect(BaseModule):
    name: ClassVar[str] = "affect"

    def __init__(
        self,
        bus: AsyncBus,
        *,
        baseline: Optional[DimensionalState] = None,
        drift_rate_per_s: float = 0.05,
        publish_interval_s: float = 1.0,
        regulation: Optional[RegulationPolicy] = None,
        drives: Optional[DriveSet] = None,
        goals: Optional[GoalLedger] = None,
        baseline_salience: float = 0.1,
        alert_salience: float = 0.7,
        interoception_stream: str = "interoception.out",
        sequence_stream: str = "sequence.out",
        episodic_memory_stream: str = "episodic_memory.out",
        action_selection_stream: str = "action_selection.out",
        fast_time_constant_s: float = 10.0,
        slow_time_constant_s: float = 100.0,
        learning_progress_floor: float = 0.05,
        alert_excess_margin: float = 0.5,
        intent_rate_weight: float = 0.05,
        valence_time_constant_s: float = 30.0,
        valence_progress_gain: float = 2.0,
        goal_stall_s: float = 600.0,
        goal_cap: int = 3,
        goal_response_window_s: float = 10.0,
        goal_likelihood_fall: float = 0.5,
        drive_arousal_gain: float = 0.2,
        clock: Optional[Callable[[], float]] = None,
        # Shared subjective clock (injected at boot). Affect drift and the
        # publish interval are cognitive time constants, so they run in subjective
        # time. When given, it supplies `now()` as this
        # module's clock; an explicit `clock` callable still wins (tests inject a
        # fake monotonic). Absent both, a real-time EntityClock →
        # behavior-identical.
        entity_clock: Optional[EntityClock] = None,
        coupling: Optional[CouplingConfig] = None,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if drift_rate_per_s < 0:
            raise ValueError("drift_rate_per_s must be >= 0")
        if publish_interval_s <= 0:
            raise ValueError("publish_interval_s must be positive")
        if not math.isfinite(fast_time_constant_s) or fast_time_constant_s <= 0:
            raise ValueError("fast_time_constant_s must be finite and > 0")
        if not math.isfinite(slow_time_constant_s) or slow_time_constant_s <= 0:
            raise ValueError("slow_time_constant_s must be finite and > 0")
        if fast_time_constant_s >= slow_time_constant_s:
            raise ValueError("fast_time_constant_s must be < slow_time_constant_s")
        if not math.isfinite(learning_progress_floor) or not (0.0 <= learning_progress_floor < 1.0):
            raise ValueError("learning_progress_floor must be finite and in [0, 1)")
        if not math.isfinite(alert_excess_margin) or alert_excess_margin < 0:
            raise ValueError("alert_excess_margin must be finite and >= 0")
        for name, w in (
            ("intent_rate_weight", intent_rate_weight),
        ):
            if not (0.0 < w <= 1.0):
                raise ValueError(f"{name} must be in (0, 1]")
        if not math.isfinite(valence_time_constant_s) or valence_time_constant_s <= 0:
            raise ValueError("valence_time_constant_s must be finite and > 0")
        if not math.isfinite(valence_progress_gain) or valence_progress_gain < 0:
            raise ValueError("valence_progress_gain must be finite and >= 0")
        if not math.isfinite(goal_stall_s) or goal_stall_s <= 0:
            raise ValueError("goal_stall_s must be finite and > 0")
        if not isinstance(goal_cap, int) or isinstance(goal_cap, bool) or goal_cap < 1:
            raise ValueError("goal_cap must be an int >= 1")
        if not math.isfinite(goal_response_window_s) or goal_response_window_s <= 0:
            raise ValueError("goal_response_window_s must be finite and > 0")
        if not math.isfinite(goal_likelihood_fall) or not (0.0 <= goal_likelihood_fall <= 1.0):
            raise ValueError("goal_likelihood_fall must be finite and in [0, 1]")
        if not math.isfinite(drive_arousal_gain) or not (0.0 <= drive_arousal_gain <= 1.0):
            raise ValueError("drive_arousal_gain must be finite and in [0, 1]")

        self._baseline = (baseline or DimensionalState()).clamped()
        self._state = DimensionalState(
            valence=self._baseline.valence,
            arousal=self._baseline.arousal,
            dominance=self._baseline.dominance,
        )
        self._drift_rate = float(drift_rate_per_s)
        self._publish_interval = float(publish_interval_s)

        self._regulation: RegulationPolicy = regulation or PassiveDecay()
        self._development_probe: Optional[Callable[[], bool]] = None
        self._last_pleasantness = 0.0
        self._last_goal_score = 0.0
        self._last_snapshot: Optional[WorkspaceSnapshot] = None
        self._drives = drives or DriveSet()
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._interoception_stream = interoception_stream
        self._sequence_stream = sequence_stream
        self._episodic_memory_stream = episodic_memory_stream
        self._action_selection_stream = action_selection_stream
        self._fast_time_constant_s = float(fast_time_constant_s)
        self._slow_time_constant_s = float(slow_time_constant_s)
        self._learning_progress_floor = float(learning_progress_floor)
        self._alert_excess_margin = float(alert_excess_margin)
        self._intent_rate_weight = float(intent_rate_weight)
        self._valence_time_constant_s = float(valence_time_constant_s)
        self._valence_progress_gain = float(valence_progress_gain)
        self._goal_stall_s = float(goal_stall_s)
        self._goal_cap = int(goal_cap)
        self._goal_response_window_s = float(goal_response_window_s)
        self._goal_likelihood_fall = float(goal_likelihood_fall)
        self._drive_arousal_gain = float(drive_arousal_gain)

        # Perceptual learning-progress state.
        # Time-decayed mean trackers per source: sum and count for each tau.
        self._err_fast_sum: dict[str, float] = {}
        self._err_fast_count: dict[str, float] = {}
        self._err_slow_sum: dict[str, float] = {}
        self._err_slow_count: dict[str, float] = {}
        self._err_last_at: dict[str, float] = {}
        self._alert_fast = 0.0
        self._alert_slow = 0.0
        self._intent_rate = 0.0
        self._intents_since_broadcast = 0
        self._wellness = 0.5  # neutral prior: no interoception module wellness information yet
        self._interaction_seen = False
        self._last_tsli: Optional[float] = None

        # Precedence: an explicit `clock` callable (test seam) > the injected
        # subjective `entity_clock.now` > a real-time EntityClock. All of
        # The affect module's time constants read through `self._clock`, so injecting the
        # shared subjective clock dilates them coherently with the cycle.
        self._entity_clock = entity_clock
        if clock is not None:
            self._clock = clock
        else:
            self._clock = (entity_clock or EntityClock()).now
        self._last_tick_at = self._clock()
        self._last_publish_at = 0.0
        # Goal ledger: injected ledgers, even empty ones, must be preserved.
        self._goals = goals if goals is not None else GoalLedger(clock=self._clock)
        # Snapshot of drive credit counters so completed/abandoned crossings can
        # be detected synchronously during ticks and peer events.
        self._drive_end_counts = {
            d.name: (d.own_ends, d.other_ends) for d in self._drives.all()
        }
        # Goal id -> entity time at which its drive has been continuously at or
        # above threshold.
        self._goal_above_since: dict[str, float] = {}
        # Active response windows: {"goal_id", "drive", "ref", "deadline"}.
        self._response_windows: list[dict[str, Any]] = []
        # Goal id -> accumulated Delta L to apply to the next appraisal.
        self._held_obstruction: dict[str, float] = {}
        self._last_obstruction = 0.0

        self._last_emotion: CategoricalEmotion = CategoricalEmotion.NEUTRAL
        self._cursors: dict[str, str] = {}
        self.modulator = StateModulator(lambda: self._state)
        # Affect coupling (thymos-affect-coupling change).
        self._coupling = coupling or CouplingConfig()
        self._familiarity_cache: dict[str, float] = {}  # agent_id and source_label -> familiarity
        # Transient perceived-emotion signal folded into appraisal (decays).
        # None until the first audition.emotion arrives while coupling enabled.
        self._perceived_emotion: Optional[dict[str, float]] = None
        # Goal-significance method flag, disclosed in affect.emotion events.
        self._goal_method = "unavailable"
        # Drive-to-source table and dominant-drive selector, injected at cycle
        # assembly so the affect module never imports the workspace.
        self._drive_sources: Optional[Mapping[str, frozenset[str]]] = None
        self._dominant_drive: Optional[
            Callable[[Mapping[str, float]], tuple[str, float] | None]
        ] = None
        # Streams for coupling inputs (populated in initialize).
        self._audition_emotion_stream = "audition.out"
        self._social_cognition_agent_model_stream = "social_cognition.out"
        # Perception→arousal coupling: perceptual surprise (the vision module's scene dynamics,
        # audition acoustic onsets) arouses the entity, scaled by the larger of the
        # normalised prediction error ratio and the normalised change ratio,
        # mirroring the interoception module's alert→arousal path.
        # These streams are read UNCONDITIONALLY (arousal is pre-attentive; a
        # startle does not require the emotion-coupling path to be enabled).
        self._vision_stream = "vision.out"
        self._perception_streams = [self._vision_stream, self._audition_emotion_stream]
        # Gain on the normalised-surprise → arousal nudge (per alert event). The
        # per-event contribution is capped so arousal BUILDS over sustained surprise
        # rather than saturating on one frame, and each step is scaled by the
        # habituation factor read before the alert's own increment.
        self._perception_arousal_gain = 0.15
        self._perception_arousal_cap = 4.0

    @property
    def state(self) -> DimensionalState:
        return self._state

    @property
    def baseline(self) -> DimensionalState:
        return self._baseline

    @property
    def drives(self) -> DriveSet:
        return self._drives

    @property
    def goals(self) -> GoalLedger:
        return self._goals

    @property
    def regulation(self) -> RegulationPolicy:
        return self._regulation

    @property
    def last_emotion(self) -> CategoricalEmotion:
        return self._last_emotion

    def set_development_probe(
        self, probe: Optional[Callable[[], bool]]
    ) -> None:
        """Store a callable that returns True while the entity is developing.

        Regulation is disabled during the developmental phase (paper §3.5).
        With no probe, regulation runs: staging disabled means the entity counts
        as matured. Injected at boot by the cycle.
        """
        self._development_probe = probe

    def _progress(self) -> tuple[float, float]:
        """Return (learning_progress, signed_progress).

        `learning_progress` is max(0, g - floor) / (1 - floor) where g is
        the per-module relative fall of the raw forward-model prediction
        error, averaged over the perceptual modules (Oudeyer and Kaplan
        2007; Schmidhuber 2010).
        """
        g_values: list[float] = []
        for source, n_slow in self._err_slow_count.items():
            if n_slow <= 0.0:
                continue
            slow = self._err_slow_sum[source] / n_slow
            if slow <= 1e-9:
                continue
            n_fast = self._err_fast_count.get(source, 0.0)
            if n_fast <= 0.0:
                continue
            fast = self._err_fast_sum[source] / n_fast
            g_m = (slow - fast) / slow
            g_m = max(-1.0, min(1.0, g_m))
            g_values.append(g_m)
        if not g_values:
            return 0.0, 0.0
        g = sum(g_values) / len(g_values)
        floor = self._learning_progress_floor
        lp = max(0.0, g - floor) / (1.0 - floor)
        return lp, g

    def _pleasantness(self, g: float) -> float:
        """Appraisal pleasantness for signed progress `g`.

        Coupling contributes only through the appraisal: the perceived
        other's pleasantness is added to tanh(valence_progress_gain * g),
        then clipped to [-1, 1]. This value is what valence relaxes toward
        (shifted by wellness).
        """
        coupling_pleasantness = self._perceived_appraisal_contribution()[0]
        return _clip(
            math.tanh(self._valence_progress_gain * g) + coupling_pleasantness,
            -1.0, 1.0,
        )

    _ALERT_RATE_FLOOR_PER_S: ClassVar[float] = 0.05

    def _alert_rate_ratio(self) -> float:
        return self._alert_fast / max(self._alert_slow, self._ALERT_RATE_FLOOR_PER_S)

    def _alert_excess(self) -> float:
        """Return alert-stream novelty relative to its own habituated rate."""
        return _clip(self._alert_rate_ratio() - 1.0 - self._alert_excess_margin, 0.0, 1.0)

    def _habituation(self) -> float:
        """Return the habituation factor h = max(h_burst, h_n).

        The burst term h_burst = clip(r_f / max(r_s, r_0) - 1, 0, 1) is the
        alert-rate excess of paper A.4 without the boredom margin; it is 0 while
        alerts arrive at the habituated base rate and rises when they come faster.
        The presentation term h_n = exp(-r_s * tau_s) treats r_s * tau_s as the
        expected number of recent alerts, so it is 1 after quiet or a reset, about
        0.37 after one presentation, and near 0 at a steady base rate, then recovers
        as r_s decays. Together the factor is full for a first presentation and
        decrements with repeats, consistent with locus coeruleus cells responding
        fully to first presentations and then habituating (Herve-Minvielle and
        Sara 1995; Vankov, Herve-Minvielle and Sara 1995).
        """
        return max(
            _clip(self._alert_rate_ratio() - 1.0, 0.0, 1.0),
            math.exp(-self._alert_slow * self._slow_time_constant_s),
        )

    def _arousal_target(self) -> float:
        """Return the relaxation target a_inf = a_0 + gamma_D (1 - a_0) v* (paper A.4 item 3).

        v* is the dominant (largest) drive value at the start of the update. Tonic locus
        coeruleus activity rises when the utility of the current engagement wanes
        (Aston-Jones and Cohen 2005), and drive energizes behavior (Hull 1943).
        """
        v_star = max((d.value for d in self._drives.all()), default=0.0)
        a_0 = self._baseline.arousal
        return a_0 + self._drive_arousal_gain * (1.0 - a_0) * v_star

    def set_drive_relevance(
        self,
        drive_sources: Mapping[str, frozenset[str]],
        dominant: Callable[[Mapping[str, float]], tuple[str, float] | None],
    ) -> None:
        """Store the drive-to-source table and the dominant-drive helper.

        Both are injected by the cycle composition root; the affect module does not import
        the workspace layer.
        """
        self._drive_sources = drive_sources
        self._dominant_drive = dominant

    async def initialize(self) -> None:
        peer_streams = [
            self._interoception_stream,
            self._sequence_stream,
            self._episodic_memory_stream,
            self._action_selection_stream,
        ]
        # Perception→arousal streams are read unconditionally (vision.out always;
        # audition.out carries both perception and, when coupling is on, emotion).
        peer_streams.append(self._vision_stream)
        peer_streams.append(self._audition_emotion_stream)
        if self._coupling.enabled:
            peer_streams.append(self._social_cognition_agent_model_stream)
        for stream in peer_streams:
            try:
                latest = await self._bus.client.xrevrange(stream, count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                self._cursors[stream] = entry_id
            else:
                self._cursors[stream] = "0-0"
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._peer_consumer_loop(), name=f"{self.name}-peer-consumer"
            )
        )
        self._tasks.append(
            asyncio.create_task(
                self._state_timer_loop(), name=f"{self.name}-state-timer"
            )
        )

    async def shutdown(self) -> None:
        await super().shutdown()

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        await self._tick()
        await self._appraise_snapshot(snapshot)
        await self._maybe_publish_state()

    async def _publish_goal_events(self, payloads: list[dict[str, Any]]) -> None:
        """Publish goal lifecycle events after all synchronous state changes."""
        for payload in payloads:
            await self.publish(
                "affect.goal", payload, salience=self._baseline_salience
            )

    def _drop_goal_state(self, goal_id: str) -> None:
        """Remove per-goal transient state for ``goal_id``."""
        self._goal_above_since.pop(goal_id, None)
        self._held_obstruction.pop(goal_id, None)
        self._response_windows = [
            w for w in self._response_windows if w.get("goal_id") != goal_id
        ]

    def _end_goal(
        self, goal_id: str, outcome: str, reason: str
    ) -> Optional[dict[str, Any]]:
        """Complete or abandon a goal, cleaning up its per-goal state.

        Returns a payload dict if and only if the goal was active and transitioned.
        """
        target = GoalState.COMPLETED if outcome == "completed" else GoalState.ABANDONED
        before = self._goals.get(goal_id).state
        if outcome == "completed":
            goal = self._goals.complete(goal_id)
        else:
            goal = self._goals.abandon(goal_id)
        if before != GoalState.ACTIVE or goal.state != target:
            return None
        self._drop_goal_state(goal.id)
        return {
            "action": outcome,
            "id": goal.id,
            "description": goal.description,
            "drive": goal.drive,
            "reason": reason,
        }

    def _settle_goal_ends(self) -> list[dict[str, Any]]:
        """Detect credit-rule ends for active goals and end them."""
        payloads: list[dict[str, Any]] = []
        for drive in self._drives.all():
            name = drive.name
            old_own, old_other = self._drive_end_counts.get(name, (0, 0))
            self._drive_end_counts[name] = (drive.own_ends, drive.other_ends)
            goal = self._goals.active_for_drive(name)
            if goal is None:
                continue
            if drive.own_ends > old_own:
                payload = self._end_goal(goal.id, "completed", "own_response")
                if payload is not None:
                    payloads.append(payload)
            elif drive.other_ends > old_other:
                payload = self._end_goal(goal.id, "abandoned", "without_response")
                if payload is not None:
                    payloads.append(payload)
        return payloads

    def _enforce_goal_cap(self) -> list[dict[str, Any]]:
        """Abandon the lowest-priority active goals while over the cap."""
        payloads: list[dict[str, Any]] = []
        while len(self._goals.active()) > self._goal_cap:
            active = self._goals.active()
            victim = min(active, key=lambda g: (g.priority, g.created_at, g.id))
            payload = self._end_goal(victim.id, "abandoned", "cap")
            if payload is not None:
                payloads.append(payload)
        return payloads

    def _create_goals(self, crossings: list[Any], now: float) -> list[dict[str, Any]]:
        """Create goals for drives that just crossed theta_D, then enforce cap."""
        payloads: list[dict[str, Any]] = []
        for crossing in crossings:
            if self._goals.active_for_drive(crossing.name) is not None:
                continue
            drive = getattr(self._drives, crossing.name)
            goal = self._goals.add(
                f"relieve {crossing.name}",
                priority=_clip01(crossing.value),
                drive=crossing.name,
                likelihood=drive.power(),
            )
            self._goal_above_since[goal.id] = now
            payloads.append(
                {
                    "action": "added",
                    "id": goal.id,
                    "description": goal.description,
                    "priority": goal.priority,
                    "drive": goal.drive,
                    "likelihood": goal.likelihood,
                }
            )
        payloads += self._enforce_goal_cap()
        return payloads

    def _check_stalls(self, now: float) -> list[dict[str, Any]]:
        """Abandon goals whose drive has stayed above threshold too long."""
        payloads: list[dict[str, Any]] = []
        for goal in list(self._goals.active()):
            if not goal.drive:
                continue
            drive = getattr(self._drives, goal.drive, None)
            if drive is None:
                continue
            if drive.value >= drive.threshold:
                since = self._goal_above_since.setdefault(goal.id, now)
                if now - since >= self._goal_stall_s:
                    payload = self._end_goal(goal.id, "abandoned", "stalled")
                    if payload is not None:
                        payloads.append(payload)
            else:
                self._goal_above_since.pop(goal.id, None)
        return payloads

    def _check_response_windows(self, now: float) -> None:
        """Expire windows; when a drive did not fall, reduce L and hold Delta L."""
        kept: list[dict[str, Any]] = []
        for window in list(self._response_windows):
            try:
                goal = self._goals.get(window["goal_id"])
            except KeyError:
                continue
            if goal.state != GoalState.ACTIVE:
                continue
            drive = getattr(self._drives, window["drive"], None)
            if drive is not None and drive.value < window["ref"]:
                continue
            if now >= window["deadline"]:
                L = goal.likelihood if goal.likelihood is not None else 0.0
                dL = self._goal_likelihood_fall * L
                self._goals.set_likelihood(goal.id, _clip01(L - dL))
                self._held_obstruction[goal.id] = (
                    self._held_obstruction.get(goal.id, 0.0) + dL
                )
                log.debug(
                    "goal %s likelihood fell by %.3f (response window expired)",
                    goal.id, dL,
                )
                continue
            kept.append(window)
        self._response_windows = kept

    def _open_response_windows(self, now: float) -> None:
        """Open a response window for every active goal with a drive."""
        for goal in self._goals.active():
            if not goal.drive:
                continue
            drive = getattr(self._drives, goal.drive, None)
            if drive is None:
                continue
            self._response_windows.append(
                {
                    "goal_id": goal.id,
                    "drive": goal.drive,
                    "ref": drive.value,
                    "deadline": now + self._goal_response_window_s,
                }
            )

    async def _tick(self) -> None:
        now = self._clock()
        dt = max(0.0, now - self._last_tick_at)
        self._last_tick_at = now
        lp, g = self._progress()

        # Decay alert-rate estimates before using them.
        fast_tau = self._fast_time_constant_s
        slow_tau = self._slow_time_constant_s
        self._alert_fast *= math.exp(-dt / fast_tau)
        self._alert_slow *= math.exp(-dt / slow_tau)
        nb = self._alert_excess()

        # Arousal drifts toward the drive-raised target; dominance drifts toward baseline; valence relaxes below.
        target = DimensionalState(
            valence=self._baseline.valence,
            arousal=self._arousal_target(),
            dominance=self._baseline.dominance,
        )
        drifted = self._state.drift_toward(target, self._drift_rate, dt)
        v = self._state.valence  # pre-drift valence
        if dt > 0.0:
            # Valence relaxes toward the appraisal's pleasantness shifted by
            # wellness; coupling reaches valence only through the appraisal.
            v_target = _clip(self._pleasantness(g) + (self._wellness - 0.5), -1.0, 1.0)
            k = 1.0 - math.exp(-dt / self._valence_time_constant_s)
            new_valence = v + (v_target - v) * k
        else:
            new_valence = v
        self._state = DimensionalState(
            valence=new_valence,
            arousal=drifted.arousal,
            dominance=drifted.dominance,
        ).clamped()

        # Continuous drive relief: curiosity at full strength = learning progress,
        # boredom at full strength = alert-stream novelty excess. Rate-based relief
        # is independent of the report rate, so drives can still build under noise.
        # own marks relief produced by the entity's own response, which coping
        # counts as success (paper A.4).
        self._drives.relieve_rate("curiosity", lp, dt, own=True)
        self._drives.relieve_rate("boredom", nb, dt, own=False)

        social_signal = 1.0 if self._interaction_seen else 0.0
        crossings = self._drives.tick(
            dt,
            novelty_signal=max(0.0, 1.0 - lp),
            activity_signal=max(0.0, 1.0 - nb),
            social_signal=social_signal,
            action_signal=max(0.0, 1.0 - self._intent_rate),
        )
        for crossing in crossings:
            await self.publish(
                "affect.drive",
                {"drive": crossing.name, "value": crossing.value, "alert": True},
                salience=self._alert_salience,
            )
        # Goal lifecycle (paper A.4): settle credit ends first so a drive that
        # ended and re-crossed in the same tick is handled correctly, then create
        # goals for new crossings, check stall timers, and expire response windows.
        # All state changes are synchronous; events are published afterwards.
        payloads = self._settle_goal_ends()
        payloads += self._create_goals(crossings, now)
        payloads += self._check_stalls(now)
        self._check_response_windows(now)
        await self._publish_goal_events(payloads)
        adj = await self._regulation.suggest(self._state)
        self._state = self._state.nudged(
            valence=adj.valence,
            arousal=adj.arousal,
            dominance=adj.dominance,
        )
        if isinstance(self._regulation, ThreeTierRegulation):
            await self._run_regulation(now)

    def _emotion_payload(
        self, emotion: CategoricalEmotion, scores: AppraisalScores
    ) -> dict[str, Any]:
        """Build the payload published on ``affect.emotion``."""
        return {
            "emotion": emotion.value,
            "alert": emotion != CategoricalEmotion.NEUTRAL,
            "scores": scores.as_tuple(),
            "state": self._state.to_dict(),
            # norm_compatibility is fixed at 0.0 and undefined: KAINE
            # has no standards until an operator writes a list (see
            # _score_snapshot). No categorical rule reads it.
            "norm_compatibility_available": False,
            # False when the coalition is irrelevant (goal score 0):
            # coping is undefined. When the goal score is nonzero,
            # including negative values from obstruction, coping is
            # defined and fear, anger or sadness may be eligible.
            "coping_available": scores.coping_available,
            "obstruction": self._last_obstruction,
            "goal_significance_method": self._goal_method,
        }

    async def _run_regulation(self, now: float) -> None:
        """Execute the three-tier regulation rule for the current tick."""
        if self._development_probe is not None:
            try:
                developing = self._development_probe()
            except Exception:
                log.warning(
                    "affect regulation: development probe failed, treating entity as developing"
                )
                developing = True
            if developing:
                self._regulation.reset()
                return

        intensity = ThreeTierRegulation.intensity(
            self._state.valence, self._state.arousal, self._baseline.arousal
        )
        negative = self._last_pleasantness < 0.0 or self._last_goal_score < 0.0
        act = self._regulation.update(
            now=now, intensity=intensity, negative=negative
        )
        if act is None:
            return

        cfg = self._regulation.config
        if act.tier == 1:
            bias = cfg.selection_bias if act.target_source is not None else 0.0
            payload = {
                "tier": 1,
                "action": "attentional_deployment",
                "source": act.target_source,
                "bias": bias,
                "decay_s": cfg.bias_decay_s,
                "intensity": act.intensity,
                "episode_s": act.episode_s,
                "size": bias,
            }
            log.info(
                "affect regulation activation: tier=%d action=%s size=%.3f source=%s",
                act.tier, payload["action"], payload["size"], act.target_source,
            )
            await self.publish(
                "affect.regulation", payload, salience=self._baseline_salience
            )
        elif act.tier == 2:
            before = self._last_emotion
            emotion = before
            if self._regulation.take_reappraisal() and self._last_snapshot is not None:
                scores = self._score_snapshot(self._last_snapshot)
                emotion = classify(scores)
                if emotion != before:
                    self._last_emotion = emotion
                    await self.publish(
                        "affect.emotion",
                        {**self._emotion_payload(emotion, scores), "reappraised": True},
                        salience=self._alert_salience
                        if emotion != CategoricalEmotion.NEUTRAL
                        else self._baseline_salience,
                    )
            payload = {
                "tier": 2,
                "action": "reappraisal",
                "intensity": act.intensity,
                "episode_s": act.episode_s,
                "emotion_before": before.value,
                "emotion_after": emotion.value,
                "size": 1.0 if emotion != before else 0.0,
            }
            log.info(
                "affect regulation activation: tier=%d action=%s size=%.3f",
                act.tier, payload["action"], payload["size"],
            )
            await self.publish(
                "affect.regulation", payload, salience=self._baseline_salience
            )
        elif act.tier == 3:
            payload = {
                "tier": 3,
                "action": "request_maintenance",
                "intensity": act.intensity,
                "episode_s": act.episode_s,
                "size": act.intensity,
            }
            log.info(
                "affect regulation activation: tier=%d action=%s size=%.3f",
                act.tier, payload["action"], payload["size"],
            )
            await self.publish(
                "affect.regulation", payload, salience=self._baseline_salience
            )

    async def _appraise_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        # Update the exponential intent-rate estimate and reset the counter.
        self._intent_rate += self._intent_rate_weight * (
            min(1, self._intents_since_broadcast) - self._intent_rate
        )
        self._intents_since_broadcast = 0

        scores = self._score_snapshot(snapshot)
        # Held obstruction applies to one appraisal only.
        self._held_obstruction.clear()
        self._last_pleasantness = scores.intrinsic_pleasantness
        self._last_goal_score = scores.goal_significance
        self._last_snapshot = snapshot
        if isinstance(self._regulation, ThreeTierRegulation):
            self._regulation.observe_coalition(
                ((ev.source, float(ev.salience)) for _, ev in snapshot.selected_events),
                negative=(
                    scores.intrinsic_pleasantness < 0.0 or scores.goal_significance < 0.0
                ),
            )

        emotion = classify(scores)
        # Surprise reaches arousal through the perceptual-alert path;
        # valence follows learning progress.
        if emotion != self._last_emotion:
            await self.publish(
                "affect.emotion",
                self._emotion_payload(emotion, scores),
                salience=self._alert_salience
                if emotion != CategoricalEmotion.NEUTRAL
                else self._baseline_salience,
            )
            self._last_emotion = emotion

    def _score_snapshot(self, snapshot: WorkspaceSnapshot) -> AppraisalScores:
        selected = snapshot.selected_events

        # Novelty: suddenness from the change ratio, predictability from the error
        # ratio, and familiarity from the habituation factor (Sander, Grandjean and
        # Scherer 2005; paper A.4). For each selected event with a positive finite
        # normalised_error or normalised_change, combine the two as 1 - prod(1 - s_e),
        # where s_e = clip(ln(max ratio) / ln 3, 0, 1). Vision and audition reports
        # are additionally scaled by the current habituation factor, which is full
        # for a first presentation and decrements with repeats unless alerts arrive
        # faster than the habituated rate.
        h = self._habituation()
        log3 = math.log(3.0)
        prod_factor = 1.0
        has_novel = False
        for _, ev in selected:
            payload = ev.payload or {}
            ratios: list[float] = []
            for key in ("normalised_error", "normalised_change"):
                raw = payload.get(key)
                if raw is None:
                    continue
                try:
                    r = float(raw)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(r) or r <= 0.0:
                    continue
                ratios.append(r)
            if not ratios:
                continue
            s = math.log(max(ratios)) / log3
            s = _clip(s, 0.0, 1.0)
            if ev.type in ("vision.report", "audition.perception"):
                s *= h
            prod_factor *= 1.0 - s
            has_novel = True
        novelty = 1.0 - prod_factor if has_novel else 0.0

        # Pleasantness is the appraisal's signed learning progress; coupling
        # contributes only through the appraisal, not by a direct state write.
        _, g = self._progress()
        pleas = self._pleasantness(g)

        # Goal/need-relevance check (Scherer 2009, "The dynamic architecture of
        # emotion"; the component process model the paper cites): scored against the
        # entity's homeostatic drives, which build from its own state.
        has_table = (
            self._drive_sources is not None and self._dominant_drive is not None
        )
        top = None
        drive_score = 0.0
        if has_table:
            top = self._dominant_drive(self._drives.to_dict())
            if top is not None and top[1] > 0.0:
                v = top[1]
                serving = self._drive_sources.get(top[0], frozenset())
                total_salience = sum(float(ev.salience) for _, ev in selected)
                if total_salience == 0.0:
                    f = 0.0
                else:
                    f = (
                        sum(
                            float(ev.salience)
                            for _, ev in selected
                            if ev.source in serving
                        )
                        / total_salience
                    )
                drive_score = v * f

        active_goals = self._goals.active()
        ledger_score = 0.0
        if active_goals:
            event_text = " ".join(
                f"{ev.source} {ev.type} {' '.join(str(v) for v in ev.payload.values())}"
                for _, ev in selected
            )
            ledger_score = self._goals.relevance(event_text)

        if has_table and active_goals:
            r = max(drive_score, ledger_score)
            self._goal_method = "drive_relevance_v1+token_overlap_v1"
        elif has_table:
            r = drive_score
            self._goal_method = "drive_relevance_v1"
        elif active_goals:
            r = ledger_score
            self._goal_method = "token_overlap_v1"
        else:
            r = 0.0
            self._goal_method = "unavailable"

        # Obstruction (paper A.4): held Delta L for the dominant drive's active
        # goal scales the drive value and is subtracted before clipping.
        o = 0.0
        if has_table and top is not None and top[1] > 0.0:
            g = self._goals.active_for_drive(top[0])
            if g is not None:
                o = top[1] * self._held_obstruction.get(g.id, 0.0)
        self._last_obstruction = o
        goal_score = max(-1.0, min(1.0, r - o))

        # Coping potential (paper A.4): checked only when the goal score is
        # nonzero; otherwise it is undefined. Obstruction can make the score
        # negative, and coping is still checked then. When the drive term sets
        # the score (also on a tie), power is the dominant drive's
        # Laplace-smoothed success ratio of own-response ends to total ended
        # crossings. When the ledger sets it, completed and abandoned goals
        # supply the ratio. Arousal and valence do not enter it.
        if goal_score == 0.0:
            coping = 0.0
            coping_available = False
        else:
            coping_available = True
            if has_table and top is not None and drive_score >= ledger_score:
                p = getattr(self._drives, top[0]).power()
            else:
                completed, abandoned = self._goals.outcome_counts()
                p = (completed + 1) / (completed + abandoned + 2)
            coping = 2.0 * p - 1.0

        # Norm compatibility: fixed 0.0, not a real measurement. The models the
        # paper reviews take standards as authored input, and KAINE has none
        # until an operator writes a list, so the check stays undefined and no
        # categorical rule reads it (disgust follows Sander, Grandjean and
        # Scherer 2005, Table 3, with standards left open). The published
        # affect.emotion event carries norm_compatibility_available=False so
        # consumers know this dimension is unavailable, not zero.
        norm = 0.0
        # Perceived-emotion appraisal contribution (thymos-emergent-affect-coupling).
        # A perceived speaker emotion is an INPUT to the entity's own appraisal,
        # weighted by familiarity and decayed by recency — not a direct state
        # write. The perceived other's pleasantness raises intrinsic_pleasantness
        # and the perceived intensity raises novelty, so the entity's *own*
        # appraisal→state path (below) produces its response.
        pp, pn = self._perceived_appraisal_contribution()
        novelty = _clip(novelty + pn, -1.0, 1.0)
        return AppraisalScores(
            novelty=novelty,
            intrinsic_pleasantness=pleas,
            goal_significance=goal_score,
            coping_potential=coping,
            norm_compatibility=norm,
            coping_available=coping_available,
        )

    #: Scale of the perceived-emotion intensity contribution to ``novelty``,
    #: kept small relative to its pleasantness contribution.
    _PERCEIVED_NOVELTY_K: ClassVar[float] = 0.5

    def _perceived_appraisal_contribution(self) -> tuple[float, float]:
        """Return (intrinsic_pleasantness, novelty) contributions from the
        currently-perceived other-emotion, decayed by recency.

        Both are zero when coupling is disabled, no signal has been recorded,
        or the signal is older than ``decay_s``.
        """
        signal = self._perceived_emotion
        if not self._coupling.enabled or signal is None:
            return 0.0, 0.0
        decay_s = self._coupling.decay_s
        age = self._clock() - signal["ts"]
        decay = max(0.0, 1.0 - age / decay_s)
        if decay <= 0.0:
            return 0.0, 0.0
        weight = signal["weight"]
        pleas = weight * decay * signal["pleasantness"]
        novelty = weight * decay * signal["intensity"] * self._PERCEIVED_NOVELTY_K
        return pleas, novelty

    async def _maybe_publish_state(self) -> None:
        now = self._clock()
        if now - self._last_publish_at < self._publish_interval:
            return
        self._last_publish_at = now
        await self.publish(
            "affect.state",
            {
                "state": self._state.to_dict(),
                "drives": self._drives.to_dict(),
                "emotion": self._last_emotion.value,
            },
            salience=self._baseline_salience,
        )

    async def _state_timer_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                # The publish interval is a subjective cognitive time constant.
                # When an EntityClock with a time scale is available, divide the
                # wall wait by the scale so that faster subjective time still
                # observes the same subjective interval; at time scale 1 wall and
                # subjective seconds coincide.
                interval = self._publish_interval
                scale = getattr(self._entity_clock, "scale", None)
                if scale is not None and scale > 0.0:
                    wall_wait = interval / scale
                else:
                    wall_wait = interval
                try:
                    await asyncio.wait_for(
                        self._stopped.wait(), timeout=wall_wait
                    )
                except asyncio.TimeoutError:
                    # The timeout is the normal tick; only a stop request ends the wait early.
                    pass
                if self._stopped.is_set():
                    break
                try:
                    await self._tick()
                    await self._maybe_publish_state()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("affect state timer tick failed")
        except asyncio.CancelledError:
            raise

    async def _peer_consumer_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                progressed = False
                peer_streams = [
                    self._interoception_stream,
                    self._sequence_stream,
                    self._episodic_memory_stream,
                    self._action_selection_stream,
                    self._vision_stream,              # perception→arousal (always)
                    self._audition_emotion_stream,   # perception + emotion (always)
                ]
                if self._coupling.enabled:
                    peer_streams.append(self._social_cognition_agent_model_stream)
                for stream in peer_streams:
                    try:
                        entries, last_scanned = await self._bus.read_entries(
                            stream,
                            last_id=self._cursors.get(stream, "0"),
                            count=64,
                            block_ms=0,
                        )
                    except Exception:
                        continue
                    if last_scanned is not None:
                        progressed = True
                        self._cursors[stream] = last_scanned
                        for _, event in entries:
                            try:
                                await self._handle_peer_event(stream, event)
                            except Exception:
                                log.exception("Error handling peer event from %s", stream)
                if not progressed:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _handle_peer_event(self, stream: str, event: Event) -> None:
        # Perception→arousal coupling: ALL perceptual reports update the
        # pooled prediction-error trackers and relieve curiosity by learning
        # progress; alerts additionally relieve boredom and arouse the entity.
        if event.type in ("vision.report", "audition.perception"):
            payload = event.payload or {}

            def _to_error(value: object) -> float | None:
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    return None
                if math.isfinite(v) and v >= 0.0:
                    return v
                return None

            def _to_ratio(value: object) -> float:
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    return 0.0
                if math.isfinite(v):
                    return v
                return 0.0

            e = _to_error(payload.get("prediction_error"))
            if e is not None:
                source: str = getattr(event, "source", None) or event.type
                now = self._clock()
                if source not in self._err_slow_count:
                    if e > 0.0:
                        self._err_fast_sum[source] = e
                        self._err_fast_count[source] = 1.0
                        self._err_slow_sum[source] = e
                        self._err_slow_count[source] = 1.0
                        self._err_last_at[source] = now
                else:
                    dt = max(0.0, now - self._err_last_at[source])
                    d_fast = math.exp(-dt / self._fast_time_constant_s)
                    d_slow = math.exp(-dt / self._slow_time_constant_s)
                    self._err_fast_sum[source] = (
                        d_fast * self._err_fast_sum[source] + e
                    )
                    self._err_fast_count[source] = (
                        d_fast * self._err_fast_count[source] + 1.0
                    )
                    self._err_slow_sum[source] = (
                        d_slow * self._err_slow_sum[source] + e
                    )
                    self._err_slow_count[source] = (
                        d_slow * self._err_slow_count[source] + 1.0
                    )
                    self._err_last_at[source] = now
            alert = bool(payload.get("alert"))
            if alert:
                # Habituation is read before the alert's own increment so the step
                # is full for a first presentation and decrements with repeats,
                # unless alerts arrive faster than the habituated rate.
                h = self._habituation()
                self._alert_fast += 1.0 / self._fast_time_constant_s
                self._alert_slow += 1.0 / self._slow_time_constant_s
                err_ratio = _to_ratio(payload.get("normalised_error"))
                chg_ratio = _to_ratio(payload.get("normalised_change"))
                surprise = min(self._perception_arousal_cap, max(0.0, max(err_ratio, chg_ratio) - 1.0))
                if surprise > 0.0:
                    self._state = self._state.nudged(
                        arousal=self._perception_arousal_gain * h * surprise,
                    )
            return
        if stream == self._interoception_stream and event.type == "interoception.report":
            wellness = event.payload.get("wellness")
            try:
                w = float(wellness)
            except (TypeError, ValueError):
                pass
            else:
                if math.isfinite(w):
                    self._wellness = _clip01(w)
            alerts = event.payload.get("alerts") or []
            if alerts:
                self._state = self._state.nudged(arousal=0.05)
        elif stream == self._sequence_stream and event.type == "sequence.report":
            tsli = event.payload.get("time_since_last_interaction_s")
            if isinstance(tsli, (int, float)) and math.isfinite(tsli):
                if not self._interaction_seen:
                    self._interaction_seen = True
                elif self._last_tsli is not None and tsli < self._last_tsli:
                    self._drives.relieve("social_drive", 1.0, own=False)
                    payloads = self._settle_goal_ends()
                    self._check_response_windows(self._clock())
                    await self._publish_goal_events(payloads)
                self._last_tsli = float(tsli)
        elif stream == self._episodic_memory_stream and event.type == "episodic_memory.recall":
            intensity = float(event.payload.get("max_affect_intensity", 0.0))
            if intensity > 0:
                self._state = self._state.nudged(
                    arousal=0.05 * intensity,
                )
        elif (
            stream == self._audition_emotion_stream
            and event.type == "audition.emotion"
        ):
            self._record_perceived_emotion(event)
        elif (
            stream == self._social_cognition_agent_model_stream
            and event.type == "social_cognition.agent_model"
        ):
            agent_id = event.payload.get("agent_id")
            familiarity = event.payload.get("familiarity")
            source_label = event.payload.get("source_label")
            if agent_id and isinstance(familiarity, (int, float)):
                self._familiarity_cache[str(agent_id)] = float(familiarity)
            if (
                isinstance(source_label, str)
                and source_label
                and isinstance(familiarity, (int, float))
            ):
                self._familiarity_cache[str(source_label)] = float(familiarity)
        elif (
            stream == self._action_selection_stream
            and event.type.startswith("intent.")
            and event.type != "intent.rest"
        ):
            self._open_response_windows(self._clock())
            self._intents_since_broadcast += 1
            self._drives.relieve("restlessness", 1.0, own=True)
            payloads = self._settle_goal_ends()
            self._check_response_windows(self._clock())
            await self._publish_goal_events(payloads)

    def _record_perceived_emotion(self, event: Event) -> None:
        """Record a transient perceived-emotion signal for appraisal.

        The detected speaker emotion is NOT written to the dimensional state.
        It is stored as a familiarity-weighted, timestamped signal that
        ``_score_snapshot`` folds — decayed by recency — into the entity's own
        Scherer appraisal. The entity's appraisal then determines its response
        through the existing appraisal→state nudge.
        """
        if not self._coupling.enabled:
            return

        category = str(event.payload.get("category", "neutral")).lower()
        vad = EMOTION_VAD.get(category, EMOTION_VAD["neutral"])
        # Perceived other's pleasantness (valence sign/magnitude) and intensity
        # (arousal) — derived from the reference table, not used as a target.
        pleasantness, intensity, _ = vad

        # Familiarity: use the source_label as the agent identifier; fall back
        # to coupling_base when no prior social_cognition.agent_model has arrived.
        agent_id = str(event.payload.get("source_label", ""))
        familiarity = self._familiarity_cache.get(agent_id, 0.0)

        weight = compute_coupling(
            coupling_base=self._coupling.coupling_base,
            coupling_familiarity_gain=self._coupling.coupling_familiarity_gain,
            familiarity=familiarity,
            coupling_ceiling=self._coupling.coupling_ceiling,
        )

        self._perceived_emotion = {
            "pleasantness": float(pleasantness),
            "intensity": float(intensity),
            "weight": float(weight),
            "ts": self._clock(),
        }
        log.debug(
            "affect coupling: recorded perceived emotion category=%s "
            "(pleasantness=%.2f, intensity=%.2f, weight=%.3f, familiarity=%.2f)",
            category, pleasantness, intensity, weight, familiarity,
        )

    async def affective_reset(self) -> None:
        if isinstance(self._regulation, ThreeTierRegulation):
            self._regulation.reset()
        self._last_pleasantness = 0.0
        self._last_goal_score = 0.0
        self._last_snapshot = None

        self._state = DimensionalState(
            valence=self._baseline.valence,
            arousal=self._baseline.arousal,
            dominance=self._baseline.dominance,
        )
        self._drives.reset_all()
        removed = self._goals.clear_active()
        self._goal_above_since.clear()
        self._response_windows.clear()
        self._held_obstruction.clear()
        self._last_obstruction = 0.0
        self._drive_end_counts = {
            d.name: (d.own_ends, d.other_ends) for d in self._drives.all()
        }
        self._last_emotion = CategoricalEmotion.NEUTRAL

        # Reset learning-progress trackers so post-sleep affect starts afresh.
        self._err_fast_sum.clear()
        self._err_fast_count.clear()
        self._err_slow_sum.clear()
        self._err_slow_count.clear()
        self._err_last_at.clear()
        self._alert_fast = 0.0
        self._alert_slow = 0.0
        self._intent_rate = 0.0
        self._intents_since_broadcast = 0
        self._perceived_emotion = None

        # A goal cleared by sleep counts as neither completed nor abandoned (paper A.4),
        # so the ledger's outcome counts are unchanged.
        payloads = [
            {
                "action": "cleared",
                "id": goal.id,
                "description": goal.description,
                "drive": goal.drive,
                "reason": "sleep_reset",
            }
            for goal in removed
        ]
        await self._publish_goal_events(payloads)

        await self.publish(
            "affect.state",
            {
                "state": self._state.to_dict(),
                "drives": self._drives.to_dict(),
                "emotion": self._last_emotion.value,
                "reset": True,
                "alert": True,
            },
            salience=self._alert_salience,
        )

    async def add_goal(self, description: str, *, priority: float = 0.5) -> str:
        goal = self._goals.add(description, priority=priority)
        await self.publish(
            "affect.goal",
            {
                "action": "added",
                "id": goal.id,
                "description": goal.description,
                "priority": goal.priority,
            },
            salience=self._baseline_salience,
        )
        cap_payloads = self._enforce_goal_cap()
        await self._publish_goal_events(cap_payloads)
        return goal.id

    async def complete_goal(self, goal_id: str) -> None:
        goal = self._goals.complete(goal_id)
        self._drop_goal_state(goal.id)
        await self.publish(
            "affect.goal",
            {
                "action": "completed",
                "id": goal.id,
                "description": goal.description,
            },
            salience=self._baseline_salience,
        )

    async def abandon_goal(self, goal_id: str) -> None:
        goal = self._goals.abandon(goal_id)
        self._drop_goal_state(goal.id)
        await self.publish(
            "affect.goal",
            {
                "action": "abandoned",
                "id": goal.id,
                "description": goal.description,
            },
            salience=self._baseline_salience,
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "state": self._state.to_dict(),
            "baseline": self._baseline.to_dict(),
            "drives": self._drives.to_dict(),
            "drive_outcomes": self._drives.outcomes_to_dict(),
            # Persist the crossing latch so a revive does not re-fire a drive
            # that already fired.
            "drive_fired": self._drives.fired_to_dict(),
            "last_emotion": self._last_emotion.value,
            # Coupling: only numeric familiarity values — zero raw-sense-data
            # persistence; agent ids are opaque strings from the social cognition module.
            "familiarity_cache": dict(self._familiarity_cache),
            # Goals: the entity's own intentions, not sense data, so they also
            # satisfy the zero raw-sense-data persistence rule.
            "goals": self._goals.to_dict(),
            # Perceptual alert rates r_f and r_s (alerts per entity second; paper A.4 boredom alert excess).
            "alert_rates": {"fast": self._alert_fast, "slow": self._alert_slow},
            # Scalar error statistics, not sense data, so they satisfy the zero raw-sense-data persistence rule.
            "error_means": {
                source: {
                    "fast_sum": self._err_fast_sum.get(source, 0.0),
                    "fast_count": self._err_fast_count.get(source, 0.0),
                    "slow_sum": self._err_slow_sum[source],
                    "slow_count": self._err_slow_count[source],
                }
                for source in self._err_slow_count
            },
            # Intent rate r_int, the restlessness build input (paper A.4).
            "intent_rate": self._intent_rate,
            # Last wellness w from interoception (paper A.4 valence).
            "wellness": self._wellness,
            # Whether the sequence module has reported an interaction (social drive input).
            "interaction_seen": self._interaction_seen,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        if "state" in state:
            s = state["state"]
            self._state = DimensionalState(
                valence=float(s.get("valence", 0.0)),
                arousal=float(s.get("arousal", 0.3)),
                dominance=float(s.get("dominance", 0.0)),
            ).clamped()
        if "baseline" in state:
            b = state["baseline"]
            self._baseline = DimensionalState(
                valence=float(b.get("valence", 0.0)),
                arousal=float(b.get("arousal", 0.3)),
                dominance=float(b.get("dominance", 0.0)),
            ).clamped()
        if "drives" in state:
            for name, value in state["drives"].items():
                drive = getattr(self._drives, name, None)
                if drive is not None:
                    drive.value = max(0.0, min(1.0, float(value)))
        # Restore the crossing latch after values because the fallback for
        # older state reads the restored drive values.
        if "drives" in state or "drive_fired" in state:
            self._drives.load_fired(state.get("drive_fired"))
        if "drive_outcomes" in state:
            self._drives.load_outcomes(state["drive_outcomes"])
        if "last_emotion" in state:
            try:
                self._last_emotion = CategoricalEmotion(state["last_emotion"])
            except ValueError:
                self._last_emotion = CategoricalEmotion.NEUTRAL
        if "familiarity_cache" in state:
            raw = state["familiarity_cache"]
            if isinstance(raw, dict):
                self._familiarity_cache = {
                    str(k): float(v)
                    for k, v in raw.items()
                    if isinstance(v, (int, float))
                }
        if "goals" in state:
            # A restore is not a lifecycle change: no affect.goal events.
            self._goals.load_dict(state["goals"])

        raw_alert_rates = state.get("alert_rates")
        if isinstance(raw_alert_rates, dict):
            fast = _finite_number(raw_alert_rates.get("fast"))
            if fast is not None and fast >= 0.0:
                self._alert_fast = fast
            slow = _finite_number(raw_alert_rates.get("slow"))
            if slow is not None and slow >= 0.0:
                self._alert_slow = slow

        raw_error_means = state.get("error_means")
        if isinstance(raw_error_means, dict):
            self._err_fast_sum.clear()
            self._err_fast_count.clear()
            self._err_slow_sum.clear()
            self._err_slow_count.clear()
            self._err_last_at.clear()
            for source, entry in raw_error_means.items():
                if not isinstance(source, str) or not isinstance(entry, dict):
                    continue
                fast_sum = _finite_number(entry.get("fast_sum"))
                fast_count = _finite_number(entry.get("fast_count"))
                slow_sum = _finite_number(entry.get("slow_sum"))
                slow_count = _finite_number(entry.get("slow_count"))
                if (
                    fast_sum is None
                    or fast_sum < 0.0
                    or fast_count is None
                    or fast_count <= 0.0
                    or slow_sum is None
                    or slow_sum < 0.0
                    or slow_count is None
                    or slow_count <= 0.0
                ):
                    continue
                self._err_fast_sum[source] = fast_sum
                self._err_fast_count[source] = fast_count
                self._err_slow_sum[source] = slow_sum
                self._err_slow_count[source] = slow_count
                self._err_last_at[source] = self._clock()

        v = _finite_number(state.get("intent_rate"))
        if v is not None and 0.0 <= v <= 1.0:
            self._intent_rate = v
        v = _finite_number(state.get("wellness"))
        if v is not None and 0.0 <= v <= 1.0:
            self._wellness = v
        raw_seen = state.get("interaction_seen")
        if isinstance(raw_seen, bool):
            self._interaction_seen = raw_seen

        # Transient state is not restored: resync end counters so restored
        # outcomes do not look like new ones, and restart stall/response timers.
        # Running estimates above are restored from saved numbers; the
        # sequence-reported interaction gap is read fresh after a boot, so
        # _last_tsli is intentionally left None.
        self._drive_end_counts = {
            d.name: (d.own_ends, d.other_ends) for d in self._drives.all()
        }
        self._goal_above_since.clear()
        self._response_windows.clear()
        self._held_obstruction.clear()
