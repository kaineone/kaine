# SPDX-License-Identifier: LicenseRef-CAL-0.2
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


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


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
        volition_stream: str = "volition.out",
        learning_progress_fast_weight: float = 0.1,
        learning_progress_slow_weight: float = 0.02,
        alert_rate_weight: float = 0.05,
        intent_rate_weight: float = 0.05,
        valence_time_constant_s: float = 30.0,
        valence_progress_gain: float = 2.0,
        clock: Optional[Callable[[], float]] = None,
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
        for name, w in (
            ("learning_progress_fast_weight", learning_progress_fast_weight),
            ("learning_progress_slow_weight", learning_progress_slow_weight),
            ("alert_rate_weight", alert_rate_weight),
            ("intent_rate_weight", intent_rate_weight),
        ):
            if not (0.0 < w <= 1.0):
                raise ValueError(f"{name} must be in (0, 1]")
        if valence_time_constant_s <= 0:
            raise ValueError("valence_time_constant_s must be > 0")

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
        self._volition_stream = volition_stream
        self._learning_progress_fast_weight = float(learning_progress_fast_weight)
        self._learning_progress_slow_weight = float(learning_progress_slow_weight)
        self._alert_rate_weight = float(alert_rate_weight)
        self._intent_rate_weight = float(intent_rate_weight)
        self._valence_time_constant_s = float(valence_time_constant_s)
        self._valence_progress_gain = float(valence_progress_gain)

        # Perceptual learning-progress state.
        self._err_fast: dict[str, float] = {}
        self._err_slow: dict[str, float] = {}
        self._alert_rate = 0.0
        self._intent_rate = 0.0
        self._intents_since_broadcast = 0
        self._wellness = 0.5  # neutral prior: no Soma wellness information yet
        self._interaction_seen = False
        self._last_tsli: Optional[float] = None

        # Precedence: an explicit `clock` callable (test seam) > the injected
        # subjective `entity_clock.now` > a real-time EntityClock. All of
        # Thymos's time constants read through `self._clock`, so injecting the
        # shared subjective clock dilates them coherently with the cycle.
        self._entity_clock = entity_clock
        if clock is not None:
            self._clock = clock
        else:
            self._clock = (entity_clock or EntityClock()).now
        self._last_tick_at = self._clock()
        self._last_publish_at = 0.0
        self._last_emotion: CategoricalEmotion = CategoricalEmotion.NEUTRAL
        self._cursors: dict[str, str] = {}
        self.modulator = StateModulator(lambda: self._state)
        # Affect coupling (thymos-affect-coupling change).
        self._coupling = coupling or CouplingConfig()
        self._familiarity_cache: dict[str, float] = {}  # agent_id → familiarity
        # Transient perceived-emotion signal folded into appraisal (decays).
        # None until the first audition.emotion arrives while coupling enabled.
        self._perceived_emotion: Optional[dict[str, float]] = None
        # Goal-significance method flag, disclosed in thymos.emotion events.
        self._goal_method = "unavailable"
        # Drive-to-source table and dominant-drive selector, injected at cycle
        # assembly so Thymos never imports the workspace.
        self._drive_sources: Optional[Mapping[str, frozenset[str]]] = None
        self._dominant_drive: Optional[
            Callable[[Mapping[str, float]], tuple[str, float] | None]
        ] = None
        # Streams for coupling inputs (populated in initialize).
        self._audition_emotion_stream = "audition.out"
        self._empatheia_agent_model_stream = "empatheia.out"
        # Perception→arousal coupling: perceptual surprise (topos scene dynamics,
        # audition acoustic onsets) arouses the entity, scaled by the normalised
        # prediction error, mirroring the interoceptive soma-alert→arousal path.
        # These streams are read UNCONDITIONALLY (arousal is pre-attentive — a
        # startle does not require the emotion-coupling path to be enabled).
        self._topos_stream = "topos.out"
        self._perception_streams = [self._topos_stream, self._audition_emotion_stream]
        # Gain on the normalised-surprise → arousal nudge (per alert event). The
        # per-event contribution is capped so arousal BUILDS over sustained surprise
        # rather than saturating on one frame.
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
    def last_emotion(self) -> CategoricalEmotion:
        return self._last_emotion

    def _progress(self) -> tuple[float, float]:
        """Return (learning_progress, signed_progress).

        `learning_progress` is max(0, g) where g is the per-module relative
        fall of the raw forward-model prediction error, averaged over the
        perceptual modules (Oudeyer and Kaplan 2007; Schmidhuber 2010).
        """
        g_values: list[float] = []
        for source, slow in self._err_slow.items():
            if slow <= 1e-9:
                continue
            fast = self._err_fast.get(source, slow)
            g_m = (slow - fast) / slow
            g_m = max(-1.0, min(1.0, g_m))
            g_values.append(g_m)
        if not g_values:
            return 0.0, 0.0
        g = sum(g_values) / len(g_values)
        return max(0.0, g), g

    def set_drive_relevance(
        self,
        drive_sources: Mapping[str, frozenset[str]],
        dominant: Callable[[Mapping[str, float]], tuple[str, float] | None],
    ) -> None:
        """Store the drive-to-source table and the dominant-drive helper.

        Both are injected by the cycle composition root; Thymos does not import
        the workspace layer.
        """
        self._drive_sources = drive_sources
        self._dominant_drive = dominant

    async def initialize(self) -> None:
        peer_streams = [
            self._soma_stream,
            self._chronos_stream,
            self._mnemos_stream,
            self._volition_stream,
        ]
        # Perception→arousal streams are read unconditionally (topos.out always;
        # audition.out carries both perception and, when coupling is on, emotion).
        peer_streams.append(self._topos_stream)
        peer_streams.append(self._audition_emotion_stream)
        if self._coupling.enabled:
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

    async def _tick(self) -> None:
        now = self._clock()
        dt = max(0.0, now - self._last_tick_at)
        self._last_tick_at = now
        lp, g = self._progress()

        # Arousal and dominance drift toward baseline; valence is overwritten below.
        drifted = self._state.drift_toward(
            self._baseline, self._drift_rate, dt
        )
        v = self._state.valence  # pre-drift valence
        coupling_pleasantness = self._perceived_appraisal_contribution()[0]
        if dt > 0.0:
            v_target = math.tanh(
                self._valence_progress_gain * g
                + (self._wellness - 0.5)
                + coupling_pleasantness
            )
            k = 1.0 - math.exp(-dt / self._valence_time_constant_s)
            new_valence = v + (v_target - v) * k
        else:
            new_valence = v
        self._state = DimensionalState(
            valence=new_valence,
            arousal=drifted.arousal,
            dominance=drifted.dominance,
        ).clamped()

        social_signal = 1.0 if self._interaction_seen else 0.0
        crossings = self._drives.tick(
            dt,
            novelty_signal=max(0.0, 1.0 - lp),
            activity_signal=max(0.0, 1.0 - self._alert_rate),
            social_signal=social_signal,
            action_signal=max(0.0, 1.0 - self._intent_rate),
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
        # Update the exponential intent-rate estimate and reset the counter.
        self._intent_rate += self._intent_rate_weight * (
            min(1, self._intents_since_broadcast) - self._intent_rate
        )
        self._intents_since_broadcast = 0

        scores = self._score_snapshot(snapshot)
        emotion = classify(scores)
        # Surprise reaches arousal through the perceptual-alert path;
        # valence follows learning progress.
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
                    "goal_significance_method": self._goal_method,
                },
                salience=self._alert_salience
                if emotion != CategoricalEmotion.NEUTRAL
                else self._baseline_salience,
            )
            self._last_emotion = emotion

    def _score_snapshot(self, snapshot: WorkspaceSnapshot) -> AppraisalScores:
        selected = snapshot.selected_events

        # Novelty (suddenness / unexpectedness) from normalised_error ratios.
        prod_factor = 1.0
        has_novel = False
        for _, ev in selected:
            payload = ev.payload or {}
            raw = payload.get("normalised_error")
            if raw is None:
                continue
            try:
                r = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(r) or r <= 0.0:
                continue
            s = math.log(r) / math.log(3.0)
            s = max(0.0, min(1.0, s))
            prod_factor *= 1.0 - s
            has_novel = True
        novelty = 1.0 - prod_factor if has_novel else 0.0

        # Pleasantness tracks signed learning progress.
        _, g = self._progress()
        pleas = math.tanh(self._valence_progress_gain * g)

        # Goal/need-relevance check (Scherer 2009, "The dynamic architecture of
        # emotion"; the component process model the paper cites): scored against the
        # entity's homeostatic drives, which build from its own state.
        has_table = (
            self._drive_sources is not None and self._dominant_drive is not None
        )
        if has_table:
            top = self._dominant_drive(self._drives.to_dict())
            if top is None or top[1] <= 0.0:
                drive_score = 0.0
            else:
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
                drive_score = v * (2.0 * f - 1.0)
        else:
            drive_score = 0.0

        active_goals = self._goals.active()
        ledger_score = 0.0
        if active_goals:
            event_text = " ".join(
                f"{ev.source} {ev.type} {' '.join(str(v) for v in ev.payload.values())}"
                for _, ev in selected
            )
            ledger_score = self._goals.relevance(event_text) * 2.0 - 1.0

        if has_table and active_goals:
            goal_score = max(drive_score, ledger_score)
            self._goal_method = "drive_relevance_v1+token_overlap_v1"
        elif has_table:
            goal_score = drive_score
            self._goal_method = "drive_relevance_v1"
        elif active_goals:
            goal_score = ledger_score
            self._goal_method = "token_overlap_v1"
        else:
            goal_score = 0.0
            self._goal_method = "unavailable"

        goal_score = max(-1.0, min(1.0, goal_score))
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
                    log.exception("thymos state timer tick failed")
        except asyncio.CancelledError:
            raise

    async def _peer_consumer_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                progressed = False
                peer_streams = [
                    self._soma_stream,
                    self._chronos_stream,
                    self._mnemos_stream,
                    self._volition_stream,
                    self._topos_stream,              # perception→arousal (always)
                    self._audition_emotion_stream,   # perception + emotion (always)
                ]
                if self._coupling.enabled:
                    peer_streams.append(self._empatheia_agent_model_stream)
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
                            await self._handle_peer_event(stream, event)
                if not progressed:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _handle_peer_event(self, stream: str, event: Event) -> None:
        # Perception→arousal coupling: ALL perceptual reports update the
        # pooled prediction-error trackers and relieve curiosity by learning
        # progress; alerts additionally relieve boredom and arouse the entity.
        if event.type in ("topos.report", "audition.perception"):
            payload = event.payload or {}

            def _to_error(value: object) -> float | None:
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    return None
                if math.isfinite(v) and v >= 0.0:
                    return v
                return None

            e = _to_error(payload.get("prediction_error"))
            if e is not None:
                source: str = getattr(event, "source", None) or event.type
                if source not in self._err_slow:
                    self._err_fast[source] = e
                    self._err_slow[source] = e
                else:
                    self._err_fast[source] += self._learning_progress_fast_weight * (
                        e - self._err_fast[source]
                    )
                    self._err_slow[source] += self._learning_progress_slow_weight * (
                        e - self._err_slow[source]
                    )
            alert = bool(payload.get("alert"))
            self._alert_rate += self._alert_rate_weight * (
                (1.0 if alert else 0.0) - self._alert_rate
            )
            lp, _ = self._progress()
            self._drives.relieve("curiosity", lp)
            if alert:
                self._drives.relieve("boredom", 1.0)
                norm = float(payload.get("normalised_error", 0.0) or 0.0)
                surprise = min(self._perception_arousal_cap, max(0.0, norm - 1.0))
                if surprise > 0.0:
                    self._state = self._state.nudged(
                        arousal=self._perception_arousal_gain * surprise,
                    )
            return
        if stream == self._soma_stream and event.type == "soma.report":
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
        elif stream == self._chronos_stream and event.type == "chronos.report":
            tsli = event.payload.get("time_since_last_interaction_s")
            if isinstance(tsli, (int, float)) and math.isfinite(tsli):
                if not self._interaction_seen:
                    self._interaction_seen = True
                elif self._last_tsli is not None and tsli < self._last_tsli:
                    self._drives.relieve("social_drive", 1.0)
                self._last_tsli = float(tsli)
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
        elif (
            stream == self._volition_stream
            and event.type.startswith("intent.")
            and event.type != "intent.rest"
        ):
            self._intents_since_broadcast += 1
            self._drives.relieve("restlessness", 1.0)

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
            # Goals: the entity's own intentions, not sense data, so they also
            # satisfy the zero raw-sense-data persistence rule.
            "goals": self._goals.to_dict(),
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
        if "goals" in state:
            # A restore is not a lifecycle change: no thymos.goal events.
            self._goals.load_dict(state["goals"])
