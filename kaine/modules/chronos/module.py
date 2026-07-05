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
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.chronos.anomaly import AnomalyDetector, RollingZScoreAnomaly
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.rumination import (
    RecurrenceRuminationDetector,
    RuminationDetector,
)

log = logging.getLogger(__name__)


DEFAULT_USER_INPUT_STREAMS: tuple[str, ...] = ("audition.out",)
_HYPNOS_STREAM: str = "hypnos.out"


class Chronos(BaseModule):
    name: ClassVar[str] = "chronos"

    def __init__(
        self,
        bus: AsyncBus,
        *,
        featurizer: Optional[SnapshotFeaturizer] = None,
        network: Optional[Any] = None,
        anomaly: Optional[AnomalyDetector] = None,
        rumination: Optional[RuminationDetector] = None,
        cfc_units: int = 32,
        baseline_salience: float = 0.1,
        alert_salience: float = 0.7,
        anomaly_alert_threshold: float = 3.0,
        anomaly_window: int = 64,
        rumination_window: int = 32,
        rumination_threshold: int = 4,
        rumination_bucket_resolution: float = 0.25,
        user_input_streams: Iterable[str] = DEFAULT_USER_INPUT_STREAMS,
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
        self._featurizer = featurizer or SnapshotFeaturizer()
        self._network = network  # lazy import to avoid torch unless used
        self._cfc_units = int(cfc_units)
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
        self._last_interaction_at: Optional[float] = None
        self._user_input_cursors: dict[str, str] = {
            stream: "$" for stream in self._user_input_streams
        }
        self._clock = clock or time.time

        # Forward-prediction head (lazy — created alongside the network)
        self._forward_prediction: bool = bool(forward_prediction)
        self._prediction_error_window: int = int(prediction_error_window)
        self._pred_head: Optional[Any] = None  # ForwardPredictionHead or None
        self._pred_errors: deque[float] = deque(maxlen=self._prediction_error_window)
        self._last_hidden: Optional[list[float]] = None  # hidden state from previous tick

        # Hypnos sleep flag — set True when hypnos.sleep.started, False on completed
        self._in_hypnos: bool = False
        self._hypnos_cursor: str = "$"

    @property
    def has_network(self) -> bool:
        return self._network is not None

    async def initialize(self) -> None:
        if self._network is None:
            from kaine.modules.chronos.network import CfCNetwork

            self._network = CfCNetwork(
                input_size=self._featurizer.feature_dim,
                units=self._cfc_units,
            )

        if self._forward_prediction and self._pred_head is None:
            from kaine.modules.chronos.network import ForwardPredictionHead

            self._pred_head = ForwardPredictionHead(
                input_size=self._featurizer.feature_dim,
                units=self._cfc_units,
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
        hidden = self._network.tick(feature_vec) if self._network else feature_vec
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
                        entries = await self._bus.read(
                            stream,
                            last_id=self._user_input_cursors.get(stream, "0"),
                            count=64,
                            block_ms=0,
                        )
                    except Exception:
                        log.exception("chronos user-input read failed for %s", stream)
                        continue
                    if entries:
                        drained_any = True
                        self._user_input_cursors[stream] = entries[-1][0]
                        latest_ts = entries[-1][1].timestamp.timestamp()
                        self._last_interaction_at = float(latest_ts)
                if not drained_any:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _hypnos_loop(self) -> None:
        """Subscribe to hypnos.out to gate adaptation during sleep."""
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        _HYPNOS_STREAM,
                        last_id=self._hypnos_cursor,
                        count=64,
                        block_ms=0,
                    )
                    if entries:
                        self._hypnos_cursor = entries[-1][0]
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
        }
        if self._pred_head is not None:
            state["pred_head"] = self._pred_head.state_dict()
        return state

    def deserialize(self, state: dict[str, Any]) -> None:
        if "last_interaction_at" in state:
            value = state["last_interaction_at"]
            self._last_interaction_at = (
                None if value is None else float(value)
            )
        if "user_input_cursors" in state:
            self._user_input_cursors.update(
                {str(k): str(v) for k, v in state["user_input_cursors"].items()}
            )
        if "pred_head" in state and self._pred_head is not None:
            self._pred_head.load_state_dict(state["pred_head"])
