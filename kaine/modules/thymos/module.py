# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.thymos.appraisal import (
    AppraisalScores,
    CategoricalEmotion,
    classify,
)
from kaine.modules.thymos.coupling import (
    EMOTION_VAD,
    CouplingConfig,
    compute_coupling,
)
from kaine.modules.thymos.drives import DriveSet
from kaine.modules.thymos.goals import GoalLedger
from kaine.modules.thymos.modulator import StateModulator
from kaine.modules.thymos.regulation import PassiveDecay, RegulationPolicy
from kaine.modules.thymos.state import DimensionalState

log = logging.getLogger(__name__)


class Thymos(BaseModule):
    name: ClassVar[str] = "thymos"

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
        soma_stream: str = "soma.out",
        chronos_stream: str = "chronos.out",
        mnemos_stream: str = "mnemos.out",
        social_drive_time_scale_s: float = 600.0,
        clock: Optional[callable] = None,
        # Shared subjective clock (injected at boot). Affect drift, the publish
        # interval, and the time-alone → social-drive mapping
        # (social_drive_time_scale_s) are all cognitive time constants, so they
        # run in subjective time. When given, it supplies `now()` as this
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
        if social_drive_time_scale_s <= 0:
            raise ValueError("social_drive_time_scale_s must be positive")
        self._baseline = (baseline or DimensionalState()).clamped()
        self._state = DimensionalState(
            valence=self._baseline.valence,
            arousal=self._baseline.arousal,
            dominance=self._baseline.dominance,
        )
        self._drift_rate = float(drift_rate_per_s)
        self._publish_interval = float(publish_interval_s)
        self._regulation: RegulationPolicy = regulation or PassiveDecay()
        self._drives = drives or DriveSet()
        self._goals = goals or GoalLedger()
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._soma_stream = soma_stream
        self._chronos_stream = chronos_stream
        self._mnemos_stream = mnemos_stream
        self._social_drive_time_scale_s = float(social_drive_time_scale_s)
        # Precedence: an explicit `clock` callable (test seam) > the injected
        # subjective `entity_clock.now` > a real-time EntityClock. All of
        # Thymos's time constants read through `self._clock`, so injecting the
        # shared subjective clock dilates them coherently with the cycle.
        if clock is not None:
            self._clock = clock
        else:
            self._clock = (entity_clock or EntityClock()).now
        self._last_tick_at = self._clock()
        self._last_publish_at = 0.0
        self._last_emotion: CategoricalEmotion = CategoricalEmotion.NEUTRAL
        self._cursors: dict[str, str] = {}
        self._recent_novelty_proxy = 0.0
        self._recent_activity_proxy = 0.0
        self.modulator = StateModulator(lambda: self._state)
        # Affect coupling (thymos-affect-coupling change).
        self._coupling = coupling or CouplingConfig()
        self._familiarity_cache: dict[str, float] = {}  # agent_id → familiarity
        # Transient perceived-emotion signal folded into appraisal (decays).
        # None until the first audition.emotion arrives while coupling enabled.
        self._perceived_emotion: Optional[dict[str, float]] = None
        # Streams for coupling inputs (populated in initialize).
        self._audition_emotion_stream = "audition.out"
        self._empatheia_agent_model_stream = "empatheia.out"

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
    def last_emotion(self) -> CategoricalEmotion:
        return self._last_emotion

    async def initialize(self) -> None:
        peer_streams = [self._soma_stream, self._chronos_stream, self._mnemos_stream]
        if self._coupling.enabled:
            peer_streams.append(self._audition_emotion_stream)
            peer_streams.append(self._empatheia_agent_model_stream)
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

    async def shutdown(self) -> None:
        await super().shutdown()

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        await self._tick()
        await self._appraise_snapshot(snapshot)
        await self._maybe_publish_state()

    async def _tick(self) -> None:
        now = self._clock()
        dt = max(0.0, now - self._last_tick_at)
        self._last_tick_at = now
        self._state = self._state.drift_toward(
            self._baseline, self._drift_rate, dt
        )
        crossings = self._drives.tick(
            dt,
            novelty_signal=max(0.0, 1.0 - self._recent_novelty_proxy),
            activity_signal=max(0.0, 1.0 - self._recent_activity_proxy),
            social_signal=0.0,  # updated by chronos events in peer loop
            action_signal=0.0,
        )
        for crossing in crossings:
            await self.publish(
                "thymos.drive",
                {"drive": crossing.name, "value": crossing.value},
                salience=self._alert_salience,
            )
        adj = await self._regulation.suggest(self._state)
        self._state = self._state.nudged(
            valence=adj.valence,
            arousal=adj.arousal,
            dominance=adj.dominance,
        )

    async def _appraise_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        scores = self._score_snapshot(snapshot)
        emotion = classify(scores)
        # Activity proxy: how many selected events; novelty proxy: salience std.
        self._recent_activity_proxy = min(
            1.0, len(snapshot.selected_events) / 10.0
        )
        if snapshot.salience_scores:
            sals = list(snapshot.salience_scores.values())
            mean = sum(sals) / len(sals)
            var = sum((s - mean) ** 2 for s in sals) / max(len(sals), 1)
            self._recent_novelty_proxy = min(1.0, var * 2.0)
        else:
            self._recent_novelty_proxy = 0.0
        if emotion != self._last_emotion:
            await self.publish(
                "thymos.emotion",
                {
                    "emotion": emotion.value,
                    "scores": scores.as_tuple(),
                    "state": self._state.to_dict(),
                    # norm_compatibility is hardcoded 0.0 until Eidolon norm
                    # signals are wired (see _score_snapshot).  DISGUST
                    # (requires norm <= -0.4) is therefore unreachable by
                    # design until that integration lands.
                    "norm_compatibility_available": False,
                    "goal_significance_method": "token_overlap_v1",
                },
                salience=self._alert_salience
                if emotion != CategoricalEmotion.NEUTRAL
                else self._baseline_salience,
            )
            self._last_emotion = emotion
        # Nudge dimensional state by the appraisal — pleasant raises
        # valence, novelty raises arousal.
        self._state = self._state.nudged(
            valence=0.05 * scores.intrinsic_pleasantness,
            arousal=0.05 * scores.novelty,
        )

    def _score_snapshot(self, snapshot: WorkspaceSnapshot) -> AppraisalScores:
        # Novelty proxy: variance of salience across selected events.
        sals = [float(ev.salience) for _, ev in snapshot.selected_events]
        if sals:
            mean = sum(sals) / len(sals)
            var = sum((s - mean) ** 2 for s in sals) / len(sals)
            novelty = max(-1.0, min(1.0, var * 4.0 - 0.2))
        else:
            novelty = 0.0
        # Pleasantness proxy: mean salience (positive = pleasant).
        pleas = max(-1.0, min(1.0, (sum(sals) / len(sals)) * 2.0 - 0.5)) if sals else 0.0
        # Goal significance: against current goal ledger.
        event_text = " ".join(
            f"{ev.source} {ev.type} {' '.join(str(v) for v in ev.payload.values())}"
            for _, ev in snapshot.selected_events
        )
        goal_score = max(-1.0, min(1.0, self._goals.relevance(event_text) * 2.0 - 0.2))
        # Coping potential: high arousal but low valence → low coping.
        coping = max(
            -1.0,
            min(1.0, self._state.valence + (0.5 - self._state.arousal)),
        )
        # Norm compatibility: fixed 0.0 — not a real measurement.
        # Eidolon norm signals are not yet wired; until they are, the DISGUST
        # classification branch (norm <= -0.4) is unreachable by design.
        # The published thymos.emotion event carries norm_compatibility_available=False
        # so consumers know this dimension is unavailable, not zero.
        norm = 0.0
        # Perceived-emotion appraisal contribution (thymos-emergent-affect-coupling).
        # A perceived speaker emotion is an INPUT to the entity's own appraisal,
        # weighted by familiarity and decayed by recency — not a direct state
        # write. The perceived other's pleasantness raises intrinsic_pleasantness
        # and the perceived intensity raises novelty, so the entity's *own*
        # appraisal→state path (below) produces its response.
        pp, pn = self._perceived_appraisal_contribution()
        pleas = max(-1.0, min(1.0, pleas + pp))
        novelty = max(-1.0, min(1.0, novelty + pn))
        return AppraisalScores(
            novelty=novelty,
            intrinsic_pleasantness=pleas,
            goal_significance=goal_score,
            coping_potential=coping,
            norm_compatibility=norm,
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
            "thymos.state",
            {
                "state": self._state.to_dict(),
                "drives": self._drives.to_dict(),
                "emotion": self._last_emotion.value,
            },
            salience=self._baseline_salience,
        )

    async def _peer_consumer_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                progressed = False
                peer_streams = [
                    self._soma_stream,
                    self._chronos_stream,
                    self._mnemos_stream,
                ]
                if self._coupling.enabled:
                    peer_streams.append(self._audition_emotion_stream)
                    peer_streams.append(self._empatheia_agent_model_stream)
                for stream in peer_streams:
                    try:
                        entries = await self._bus.read(
                            stream,
                            last_id=self._cursors.get(stream, "0"),
                            count=64,
                            block_ms=0,
                        )
                    except Exception:
                        continue
                    if entries:
                        progressed = True
                        self._cursors[stream] = entries[-1][0]
                        for _, event in entries:
                            await self._handle_peer_event(stream, event)
                if not progressed:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _handle_peer_event(self, stream: str, event: Event) -> None:
        if stream == self._soma_stream and event.type == "soma.report":
            wellness = float(event.payload.get("wellness", 1.0))
            # Low wellness drags valence down; high arousal alerts spike arousal.
            valence_nudge = (wellness - 0.5) * 0.05
            alerts = event.payload.get("alerts") or []
            arousal_nudge = 0.05 if alerts else 0.0
            self._state = self._state.nudged(
                valence=valence_nudge,
                arousal=arousal_nudge,
            )
        elif stream == self._chronos_stream and event.type == "chronos.report":
            tsli = event.payload.get("time_since_last_interaction_s")
            if isinstance(tsli, (int, float)) and tsli != float("inf"):
                # Map TSLI onto social_drive build signal: longer alone → higher.
                ratio = min(1.0, float(tsli) / self._social_drive_time_scale_s)
                # Apply directly on the drive (not via tick — TSLI is already a
                # cumulative quantity, not a rate).
                self._drives.social_drive.value = min(1.0, ratio)
                if self._drives.social_drive.consume_crossing():
                    await self.publish(
                        "thymos.drive",
                        {
                            "drive": "social_drive",
                            "value": self._drives.social_drive.value,
                        },
                        salience=self._alert_salience,
                    )
        elif stream == self._mnemos_stream and event.type == "mnemos.recall":
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
            stream == self._empatheia_agent_model_stream
            and event.type == "empatheia.agent_model"
        ):
            agent_id = event.payload.get("agent_id")
            familiarity = event.payload.get("familiarity")
            if agent_id and isinstance(familiarity, (int, float)):
                self._familiarity_cache[str(agent_id)] = float(familiarity)

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
        # to coupling_base when no prior empatheia.agent_model has arrived.
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
            "thymos coupling: recorded perceived emotion category=%s "
            "(pleasantness=%.2f, intensity=%.2f, weight=%.3f, familiarity=%.2f)",
            category, pleasantness, intensity, weight, familiarity,
        )

    async def affective_reset(self) -> None:
        self._state = DimensionalState(
            valence=self._baseline.valence,
            arousal=self._baseline.arousal,
            dominance=self._baseline.dominance,
        )
        self._drives.reset_all()
        self._last_emotion = CategoricalEmotion.NEUTRAL
        await self.publish(
            "thymos.state",
            {
                "state": self._state.to_dict(),
                "drives": self._drives.to_dict(),
                "emotion": self._last_emotion.value,
                "reset": True,
            },
            salience=self._alert_salience,
        )

    async def add_goal(self, description: str, *, priority: float = 0.5) -> str:
        goal = self._goals.add(description, priority=priority)
        await self.publish(
            "thymos.goal",
            {
                "action": "added",
                "id": goal.id,
                "description": goal.description,
                "priority": goal.priority,
            },
            salience=self._baseline_salience,
        )
        return goal.id

    async def complete_goal(self, goal_id: str) -> None:
        goal = self._goals.complete(goal_id)
        await self.publish(
            "thymos.goal",
            {
                "action": "completed",
                "id": goal.id,
                "description": goal.description,
            },
            salience=self._baseline_salience,
        )

    async def abandon_goal(self, goal_id: str) -> None:
        goal = self._goals.abandon(goal_id)
        await self.publish(
            "thymos.goal",
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
            "last_emotion": self._last_emotion.value,
            # Coupling: only numeric familiarity values — zero raw-sense-data
            # persistence; agent ids are opaque strings from Empatheia.
            "familiarity_cache": dict(self._familiarity_cache),
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
