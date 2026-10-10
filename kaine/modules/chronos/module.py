# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from typing import Any, ClassVar, Iterable, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import OPERATOR_SOURCES, Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.chronos.anomaly import AnomalyDetector, RollingZScoreAnomaly
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.rumination import (
    RecurrenceRuminationDetector,
    RuminationDetector,
)

log = logging.getLogger(__name__)


DEFAULT_USER_INPUT_STREAMS: tuple[str, ...] = ("audition.out",)
DEFAULT_INTERACTION_EVENT_TYPES: tuple[str, ...] = (
    "audition.transcription",
    "audition.emotion",
)
_HYPNOS_STREAM: str = "hypnos.out"


class Chronos(BaseModule):
    name: ClassVar[str] = "chronos"
    relieves_drives: ClassVar[frozenset[str]] = frozenset({"social_drive"})

    def __init__(
        self,
        bus: AsyncBus,
        *,
        featurizer: Optional[SnapshotFeaturizer] = None,
        network: Optional[Any] = None,
        anomaly: Optional[AnomalyDetector] = None,
        rumination: Optional[RuminationDetector] = None,
        cfc_units: int = 32,
        cfc_backend: str = "numpy",
        reservoir_seed: Optional[int] = None,
        baseline_salience: float = 0.1,
        alert_salience: float = 0.7,
        anomaly_alert_threshold: float = 3.0,
        anomaly_window: int = 64,
        rumination_window: int = 32,
        rumination_threshold: int = 4,
        rumination_bucket_resolution: float = 0.25,
        user_input_streams: Iterable[str] = DEFAULT_USER_INPUT_STREAMS,
        interaction_event_types: Iterable[str] = DEFAULT_INTERACTION_EVENT_TYPES,
        entity_clock: Optional[EntityClock] = None,
        clock: Optional[callable] = None,
        # Forward prediction config
        forward_prediction: bool = False,
        prediction_error_window: int = 32,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if anomaly_alert_threshold < 0:
            raise ValueError("anomaly_alert_threshold must be >= 0")
        if prediction_error_window < 2:
            raise ValueError("prediction_error_window must be >= 2")
        self._clock = clock or (entity_clock.now if entity_clock is not None else time.time)
        self._featurizer = featurizer or SnapshotFeaturizer(clock=self._clock)
        self._network = network  # lazy import to avoid torch unless used
        # An injected network (a plugin substrate, or a test double) brings its
        # own hidden width; the prediction head must be sized from it.
        self._network_injected = network is not None
        if self._network_injected and forward_prediction and getattr(network, "units", None) is None:
            raise ValueError(
                "Chronos: an injected network must expose `units` (its hidden "
                "width) when forward prediction is enabled"
            )
        self._cfc_units = int(cfc_units)
        self._cfc_backend = cfc_backend
        self._reservoir_seed = reservoir_seed
        # When no detector is injected, size it from config. An injected
        # detector (e.g. in tests) brings its own window/threshold settings.
        self._anomaly = anomaly or RollingZScoreAnomaly(window=int(anomaly_window))
        self._rumination = rumination or RecurrenceRuminationDetector(
            window=int(rumination_window),
            threshold=int(rumination_threshold),
            bucket_resolution=float(rumination_bucket_resolution),
        )
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._anomaly_alert_threshold = float(anomaly_alert_threshold)
        self._user_input_streams = tuple(user_input_streams)
        self._interaction_event_types = tuple(interaction_event_types)
        self._last_interaction_at: Optional[float] = None
        self._user_input_cursors: dict[str, str] = {
            stream: "$" for stream in self._user_input_streams
        }

        # Timespan tracking relative to the featurizer's broadcast cadence.
        self._dt_window: deque[float] = deque(maxlen=32)

        # Forward-prediction head (lazy — created alongside the network)
        self._forward_prediction: bool = bool(forward_prediction)
        self._prediction_error_window: int = int(prediction_error_window)
        self._pred_head: Optional[Any] = None  # ForwardPredictionHead or None
        self._pred_errors: deque[float] = deque(maxlen=self._prediction_error_window)
        self._last_hidden: Optional[list[float]] = None  # hidden state from previous tick

        # Hypnos sleep flag — set True when hypnos.sleep.started, False on completed
        self._in_hypnos: bool = False
        # Initialize resolves this to the current stream tail via last_entry_id().
        self._hypnos_cursor: str = "$"

    @property
    def has_network(self) -> bool:
        return self._network is not None

    @property
    def interaction_event_types(self) -> tuple[str, ...]:
        return self._interaction_event_types

    def _is_interaction(self, event: Event) -> bool:
        if event.type not in self._interaction_event_types:
            return False
        source_label = event.payload.get("source_label")
        if source_label not in OPERATOR_SOURCES:
            return False
        if event.type == "audition.transcription":
            text = event.payload.get("text")
            return isinstance(text, str) and text.strip() != ""
        return True

    async def initialize(self) -> None:
        if self._network is None:
            from kaine.modules.chronos.network import CfCNetwork

            self._network = CfCNetwork(
                input_size=self._featurizer.feature_dim,
                units=self._cfc_units,
                backend=self._cfc_backend,
                seed=self._reservoir_seed,
            )

        if self._forward_prediction and self._pred_head is None:
            from kaine.modules.chronos.network import ForwardPredictionHead

            # The head reads the network's hidden state, so its width must be
            # the width of the network actually in use.
            if self._network_injected:
                units = getattr(self._network, "units", None)
                if units is None:
                    raise ValueError(
                        "Chronos: an injected network must expose `units` (its "
                        "hidden width) when forward prediction is enabled"
                    )
                head_units = int(units)
            else:
                head_units = self._cfc_units
            # A built-in network shares its seed so the head's initial readout
            # follows the reservoir draws; an injected network has no seed, so
            # the head draws its own (from the ambient NumPy state, reproducible
            # under experiment seeding), and its trained weights persist with
            # the head's state either way.
            self._pred_head = ForwardPredictionHead(
                input_size=self._featurizer.feature_dim,
                units=head_units,
                backend=self._cfc_backend,
                seed=getattr(self._network, "reservoir_seed", None),
            )

        # Resolve cursors before starting tasks so initial events aren't missed
        for stream in self._user_input_streams:
            try:
                latest = await self._bus.client.xrevrange(stream, count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                self._user_input_cursors[stream] = entry_id
            else:
                self._user_input_cursors[stream] = "0-0"

        # Seed the hypnos cursor from the stream tail before starting the loop,
        # otherwise a literal "$" under a non-blocking XREAD never advances.
        self._hypnos_cursor = await self._bus.last_entry_id(_HYPNOS_STREAM)

        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._user_input_loop(), name=f"{self.name}-user-input-consumer"
            )
        )
        self._tasks.append(
            asyncio.create_task(
                self._hypnos_loop(), name=f"{self.name}-hypnos-consumer"
            )
        )

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        feature_vec = self._featurizer.featurize(snapshot)
        dt = self._featurizer.last_dt_s
        if dt is None:
            ts = 1.0
        else:
            raw = max(dt, 0.0)
            prev_mean = (
                sum(self._dt_window) / len(self._dt_window) if self._dt_window else 0.0
            )
            if prev_mean > 0:
                self._dt_window.append(min(raw, 10.0 * prev_mean))
            else:
                self._dt_window.append(raw)
            mean_dt = sum(self._dt_window) / len(self._dt_window)
            ts = 1.0 if mean_dt <= 0 else min(10.0, max(0.0, raw / mean_dt))
            # Clipping before the interval enters the window keeps one long pause
            # from dominating the mean for the next 31 steps.

        if self._network is None:
            hidden = feature_vec
        elif getattr(self._network, "accepts_timespan", False):
            hidden = self._network.tick(feature_vec, timespan=ts)
        else:
            hidden = self._network.tick(feature_vec)

        anomaly_score = self._anomaly.observe(hidden)
        rumination = self._rumination.observe(hidden)
        tsli = self._time_since_last_interaction_s()

        # Forward prediction: compute error from last tick's prediction,
        # then adapt, then store hidden for next tick.
        temporal_prediction_error: float = 0.0
        if self._forward_prediction and self._pred_head is not None:
            if self._last_hidden is not None:
                # Predict what feature_vec should have been, based on previous hidden
                predicted = self._pred_head.predict(self._last_hidden)
                temporal_prediction_error = self._pred_head.prediction_error(
                    predicted, feature_vec
                )
                self._pred_errors.append(temporal_prediction_error)
                # Online adaptation step toward the observed feature vector
                self._pred_head.suspended = self._in_hypnos
                self._pred_head.adapt(self._last_hidden, feature_vec)
            self._last_hidden = list(hidden)

        # Anomaly salience: driven by prediction error when forward_prediction
        # is enabled, otherwise fall back to z-score threshold.
        if self._forward_prediction and self._pred_errors:
            # Normalise against the rolling window mean so a stable cadence
            # yields low salience even when the absolute error is non-zero.
            mean_err = sum(self._pred_errors) / len(self._pred_errors)
            # Use temporal_prediction_error relative to mean; scale to match
            # the existing anomaly_alert_threshold convention.
            if mean_err > 0:
                normalised = temporal_prediction_error / mean_err
            else:
                normalised = 0.0
            alert = rumination.detected or normalised >= self._anomaly_alert_threshold
        else:
            alert = (
                rumination.detected
                or anomaly_score >= self._anomaly_alert_threshold
            )

        salience = self._alert_salience if alert else self._baseline_salience
        await self.publish(
            "chronos.report",
            {
                "temporal_context": hidden,
                "anomaly_score": anomaly_score,
                "habituation_score": rumination.habituation,
                "rumination_detected": rumination.detected,
                "time_since_last_interaction_s": tsli,
                "feature_vector": feature_vec,
                "temporal_prediction_error": temporal_prediction_error,
            },
            salience=salience,
        )

    def _time_since_last_interaction_s(self) -> float:
        if self._last_interaction_at is None:
            return math.inf
        return max(0.0, float(self._clock()) - self._last_interaction_at)

    async def _user_input_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                drained_any = False
                for stream in self._user_input_streams:
                    try:
                        entries, last_scanned = await self._bus.read_entries(
                            stream,
                            last_id=self._user_input_cursors.get(stream, "0"),
                            count=64,
                            block_ms=0,
                        )
                    except Exception:
                        log.exception("chronos user-input read failed for %s", stream)
                        continue
                    if last_scanned is not None:
                        drained_any = True
                        self._user_input_cursors[stream] = last_scanned
                    if entries:
                        # Only speech-path events on operator channels count as
                        # an interaction. The cursor advances over every entry.
                        for _, event in entries:
                            if self._is_interaction(event):
                                # Bus event stamps are wall epoch seconds; cognitive
                                # time-since-interaction must run on the subjective clock.
                                self._last_interaction_at = float(self._clock())
                if not drained_any:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _hypnos_loop(self) -> None:
        """Subscribe to hypnos.out to gate adaptation during sleep."""
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        _HYPNOS_STREAM,
                        last_id=self._hypnos_cursor,
                        count=64,
                        block_ms=0,
                    )
                    if last_scanned is not None:
                        self._hypnos_cursor = last_scanned
                        for _, event in entries:
                            if event.type == "hypnos.sleep.started":
                                self._in_hypnos = True
                                if self._pred_head is not None:
                                    self._pred_head.suspended = True
                                log.debug("chronos: adaptation suspended (hypnos sleep started)")
                            elif event.type == "hypnos.sleep.completed":
                                self._in_hypnos = False
                                if self._pred_head is not None:
                                    self._pred_head.suspended = False
                                log.debug("chronos: adaptation resumed (hypnos sleep completed)")
                    else:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("chronos hypnos consumer iteration failed")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    def serialize(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "last_interaction_at": self._last_interaction_at,
            "user_input_cursors": dict(self._user_input_cursors),
            "featurizer_layout": self._featurizer.layout,
        }
        state["time_since_last_interaction_s"] = (
            None
            if self._last_interaction_at is None
            else self._time_since_last_interaction_s()
        )
        if self._network is not None and hasattr(self._network, "reservoir_seed"):
            state["reservoir_seed"] = self._network.reservoir_seed
        if self._pred_head is not None:
            state["pred_head"] = self._pred_head.state_dict()
        return state

    def deserialize(self, state: dict[str, Any]) -> None:
        # The layout comes first so a snapshot with an unknown layout fails
        # before any other state is restored. A snapshot written before the
        # layout was versioned is layout 1: a trained being keeps the input
        # layout its network and head learned on.
        if "featurizer_layout" in state:
            self._featurizer.set_layout(int(state["featurizer_layout"]))
        else:
            self._featurizer.set_layout(1)
            log.info(
                "chronos: being keeps featurizer layout 1 "
                "(Audition shares the overflow bin)"
            )
        # Time the entity was not running is not time alone; restore the lived
        # interval relative to the new boot clock.
        if "time_since_last_interaction_s" in state:
            value = state["time_since_last_interaction_s"]
            self._last_interaction_at = (
                None if value is None else float(self._clock()) - float(value)
            )
        elif "last_interaction_at" in state:
            value = state["last_interaction_at"]
            self._last_interaction_at = (
                None if value is None else min(float(value), float(self._clock()))
            )
        if "user_input_cursors" in state:
            self._user_input_cursors.update(
                {str(k): str(v) for k, v in state["user_input_cursors"].items()}
            )

        if "reservoir_seed" in state:
            # Kept on the module too, so a network built later by initialize()
            # uses the preserved reservoir whatever the call order.
            self._reservoir_seed = int(state["reservoir_seed"])
        if self._network is not None and hasattr(self._network, "reservoir_seed"):
            if "reservoir_seed" in state:
                self._network.load_state(
                    {"reservoir_seed": int(state["reservoir_seed"])}
                )
            else:
                log.warning(
                    "chronos: snapshot has no reservoir seed; the reservoir is new"
                )

        if "pred_head" in state and self._pred_head is not None:
            self._pred_head.load_state_dict(state["pred_head"])
