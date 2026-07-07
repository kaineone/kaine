# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.topos.change import ChangeDetector, CosineChangeDetector
from kaine.modules.topos.encoder import (
    DEFAULT_DINOV2_MODEL_ID,
    DINOv2Encoder,
    Encoder,
)
from kaine.modules.topos.habituation import (
    RollingMeanHabituator,
    SceneHabituator,
)
from kaine.modules.topos.live import (
    LiveCamera,
    LiveCameraConfig,
    PerceptionUnavailableError,
)

log = logging.getLogger(__name__)

_HYPNOS_STREAM: str = "hypnos.out"


class Topos(BaseModule):
    name: ClassVar[str] = "topos"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        encoder: Optional[Encoder] = None,
        change_detector: Optional[ChangeDetector] = None,
        habituator: Optional[SceneHabituator] = None,
        encoder_model_id: str = DEFAULT_DINOV2_MODEL_ID,
        device_preference: str | None = "auto",
        baseline_salience: float = 0.2,
        alert_salience: float = 0.7,
        change_alert_threshold: float = 0.5,
        # Live camera (eyes-only). See kaine/modules/topos/live.py.
        capture_enabled: bool = False,
        live_camera: Optional[LiveCamera] = None,
        live_camera_config: Optional[LiveCameraConfig] = None,
        # Deterministic perception feed (reproducible-perception-feed). When a
        # seeded/playlist source_factory is supplied, LiveCamera reads frames
        # from it instead of cv2. None = the live cv2 camera path (the default).
        # See kaine/modules/topos/feed.py.
        source_factory: Optional[Any] = None,
        # Forward prediction (disabled by default; pure additive).
        forward_prediction: bool = False,
        forward_model_units: int = 128,
        prediction_error_window: int = 32,
        visual_buffer_size: int = 16,
        # Shared subjective clock (injected at boot). Threaded into LiveCamera so
        # the capture cadence runs in subjective time (the entity's perception
        # sampling rhythm dilates with the mind). Defaults to a real-time clock
        # → behavior-identical.
        entity_clock: Optional[EntityClock] = None,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if change_alert_threshold < 0:
            raise ValueError("change_alert_threshold must be >= 0")
        if prediction_error_window < 2:
            raise ValueError("prediction_error_window must be >= 2")
        self._encoder: Encoder = encoder or DINOv2Encoder(
            model_id=encoder_model_id,
            device_preference=device_preference,
        )
        self._change_detector: ChangeDetector = (
            change_detector or CosineChangeDetector()
        )
        self._habituator: SceneHabituator = habituator or RollingMeanHabituator()
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._change_alert_threshold = float(change_alert_threshold)
        self._capture_enabled = bool(capture_enabled)
        self._source_factory = source_factory
        self._clock = entity_clock or EntityClock()
        self._live_camera: Optional[LiveCamera] = None
        if self._capture_enabled or live_camera is not None:
            self._live_camera = live_camera or self._build_default_live_camera(
                live_camera_config
            )

        # Forward prediction — disabled by default; behaviour is unchanged
        # when forward_prediction=False (the legacy change_score/habituation
        # path is always used for the alert threshold check).
        self._forward_prediction: bool = bool(forward_prediction)
        self._forward_model_units: int = int(forward_model_units)
        self._prediction_error_window: int = int(prediction_error_window)
        self._visual_buffer_size: int = int(visual_buffer_size)
        self._forward_model: Optional[Any] = None  # LatentForwardModel, lazy

        from collections import deque
        self._pred_errors: deque[float] = deque(maxlen=self._prediction_error_window)

        # Hypnos sleep flag — suspend forward-model adaptation during sleep.
        self._in_hypnos: bool = False
        self._hypnos_cursor: str = "$"

        # Dev-gated preview slot (KAINE_PERCEPTION_PREVIEW=1). A single overwritten
        # in-memory JPEG of the most recent frame — never persisted, no file. Off
        # by default; stays None unless the operator sets the dev override. See
        # kaine/perception_preview.py for the zero-persistence contract.
        self._preview_jpeg: Optional[bytes] = None

    async def initialize(self) -> None:
        import asyncio

        await self._encoder.load()

        if self._forward_prediction and self._forward_model is None:
            from kaine.modules.topos.forward import LatentForwardModel

            self._forward_model = LatentForwardModel(
                latent_dim=self._encoder.latent_dim,
                units=self._forward_model_units,
                visual_buffer_size=self._visual_buffer_size,
            )

        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._hypnos_loop(), name=f"{self.name}-hypnos-consumer"
            )
        )
        if self._live_camera is not None:
            try:
                await self._live_camera.initialize()
            except PerceptionUnavailableError as exc:
                log.warning(
                    "live camera disabled: %s (install kaine[vision] to enable)",
                    exc,
                )
                self._live_camera = None

    async def shutdown(self) -> None:
        if self._live_camera is not None:
            try:
                await self._live_camera.shutdown()
            except Exception:
                log.warning("live camera shutdown failed", exc_info=True)
        await super().shutdown()
        try:
            await self._encoder.shutdown()
        except Exception:
            log.warning("topos encoder shutdown failed", exc_info=True)
        # Drop any dev preview so no stale frame lingers once capture stops.
        self._preview_jpeg = None
        try:
            from kaine import perception_preview

            perception_preview.set_video_jpeg(None)
        except Exception:
            # Best-effort: worst case a stale preview frame lingers briefly;
            # not worth failing shutdown over, but log it like the two
            # shutdown steps above for consistency.
            log.debug("clearing perception preview failed", exc_info=True)

    def _build_default_live_camera(
        self, config: Optional[LiveCameraConfig]
    ) -> LiveCamera:
        from kaine import perception_state

        # Locus gate selection: a wired deterministic source_factory IS the
        # virtual world (seeded/playlist feed), so it binds to the `virtual`
        # locus; the bare cv2 path is the real camera and binds to `physical`.
        # Picking the matching gate is what makes the configured seeded feed
        # actually deliver — the physical gate would keep the virtual feed dark
        # forever (it requires locus == "physical").
        desired_reader = (
            perception_state.effective_virtual_video_capture
            if self._source_factory is not None
            else perception_state.effective_video_capture
        )

        return LiveCamera(
            sink=self.process_frame,
            config=config or LiveCameraConfig(),
            state_writer=perception_state.update_video_runtime,
            # locus-gated: the real camera runs only when video is desired AND
            # the perceptual locus is `physical`; the virtual (seeded/playlist)
            # feed runs only when video is desired AND the locus is `virtual`.
            desired_state_reader=desired_reader,
            # When a deterministic feed is configured, frames come from the
            # seeded/playlist source instead of cv2; None => the live cv2 path.
            source_factory=self._source_factory,
            # Shared subjective clock so the capture cadence dilates with the mind.
            entity_clock=self._clock,
        )

    async def process_frame(self, image: Any) -> str:
        embedding = await self._encoder.encode(image)
        change = float(self._change_detector.observe(embedding))
        habituation = float(self._habituator.observe(embedding))

        # Forward-prediction salience path.
        prediction_error: float = 0.0
        if self._forward_prediction and self._forward_model is not None:
            self._forward_model.suspended = self._in_hypnos
            prediction_error = self._forward_model.step(embedding)
            self._pred_errors.append(prediction_error)

            # Normalise error against the rolling window mean so a steady,
            # predictable motion yields low salience even at non-zero error.
            if self._pred_errors:
                mean_err = sum(self._pred_errors) / len(self._pred_errors)
                normalised = prediction_error / mean_err if mean_err > 0 else 0.0
            else:
                normalised = 0.0
            # Use normalised error as a proxy for the alert threshold check.
            # Threshold of 2.0 means the frame's error must be twice the
            # rolling mean before it is considered surprising.  This matches
            # the Chronos convention (normalised vs anomaly_alert_threshold).
            alert = normalised >= 2.0 or change >= self._change_alert_threshold
            salience = self._alert_salience if alert else self._baseline_salience
        else:
            salience = (
                self._alert_salience
                if change >= self._change_alert_threshold
                else self._baseline_salience
            )

        # Dev-gated preview tap (LAST thing, after all real perception work):
        # mirror this frame as a single in-memory JPEG so a Nexus diagnostic can
        # show what the entity currently sees. No-op unless KAINE_PERCEPTION_PREVIEW
        # is set; encodes to a BytesIO (never a file); wrapped so it can never
        # break the perception path. The single slot is overwritten each frame.
        try:
            from kaine import perception_preview

            if perception_preview.preview_enabled():
                jpeg = perception_preview.encode_jpeg_preview(image, quality=50)
                self._preview_jpeg = jpeg
                perception_preview.set_video_jpeg(jpeg)
        except Exception:
            log.debug("topos preview tap failed (non-fatal)", exc_info=True)

        return await self.publish(
            "topos.report",
            {
                "latent": embedding,
                "change_score": change,
                "habituation_score": habituation,
                "encoder_model_id": self._encoder.model_id,
                "prediction_error": prediction_error,
            },
            salience=salience,
        )

    async def _hypnos_loop(self) -> None:
        """Subscribe to hypnos.out to gate adaptation during sleep."""
        import asyncio

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
                                if self._forward_model is not None:
                                    self._forward_model.suspended = True
                                log.debug(
                                    "topos: adaptation suspended (hypnos sleep started)"
                                )
                            elif event.type == "hypnos.sleep.completed":
                                self._in_hypnos = False
                                if self._forward_model is not None:
                                    self._forward_model.suspended = False
                                log.debug(
                                    "topos: adaptation resumed (hypnos sleep completed)"
                                )
                    else:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("topos hypnos consumer iteration failed")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    def serialize(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "encoder_model_id": self._encoder.model_id,
        }
        if self._forward_model is not None:
            state["forward_model"] = self._forward_model.state_dict()
            # Buffer summary: statistical descriptor only — no raw latents.
            state["buffer_summary"] = self._forward_model.buffer_summary()
        return state

    def deserialize(self, state: dict[str, Any]) -> None:
        # Encoder identity is immutable per Topos instance; just note any
        # divergence in the log for forensic value.
        recorded = state.get("encoder_model_id")
        if recorded and recorded != self._encoder.model_id:
            log.warning(
                "topos snapshot recorded encoder %s but this instance uses %s",
                recorded,
                self._encoder.model_id,
            )
        if "forward_model" in state and self._forward_model is not None:
            self._forward_model.load_state_dict(state["forward_model"])
