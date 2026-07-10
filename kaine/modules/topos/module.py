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
    DEFAULT_CLIP_LEN,
    DEFAULT_CLIP_RESOLUTION,
    DEFAULT_ENCODER_BACKEND,
    DEFAULT_POOLING,
    Encoder,
    make_encoder,
)
from kaine.modules.topos.habituation import (
    RollingMeanHabituator,
    SceneHabituator,
)
from kaine.modules.topos.foveation import (
    FoveaPredictor,
    FoveaTarget,
    SpatialSaliency,
    combine_saliency,
    foveate,
    select_fovea,
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
        encoder_backend: str = DEFAULT_ENCODER_BACKEND,
        encoder_model_id: str | None = None,
        encoder_weights_dir: Any = None,
        encoder_pooling: str = DEFAULT_POOLING,
        encoder_clip_resolution: int = DEFAULT_CLIP_RESOLUTION,
        encoder_clip_len: int = DEFAULT_CLIP_LEN,
        # Strided sliding window (topos-temporal-video-encoder §1b): produce one
        # clip latent every `clip_stride` frame-ticks once the ring buffer fills.
        # The shipped config sets clip_stride = 3 (~3.33 Hz, the experiential
        # rate) for InternVideo-Next; the class default of 1 preserves the
        # per-frame cadence for the DINOv2 (clip_len=1) fallback and test doubles.
        clip_stride: int = 1,
        device_preference: str | None = "auto",
        baseline_salience: float = 0.2,
        alert_salience: float = 0.7,
        # Calibrated for the InternVideo-Next clip encoder by the GPU shakedown
        # (config/kaine.toml [topos] carries the rationale + measured distribution).
        # Cosine change on attention-pooled clip embeddings is far more compressed
        # than DINOv2 per-frame CLS was (genuine scene cuts ~0.008-0.043, routine
        # <=0.0004), so the alert threshold sits low; the old DINOv2-era 0.5 was
        # unreachable. The runtime value comes from config; this is the fallback.
        change_alert_threshold: float = 0.005,
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
        # Attention-driven foveation (topos-foveation). Off by default → the
        # existing single whole-frame encode is unchanged. When enabled, each
        # native-resolution frame yields a coarse spatial saliency map, a single
        # precision-weighted fovea target (bottom-up saliency + an optional
        # top-down bias, sized by arousal), and two encodes — a downsampled
        # peripheral gist plus a native foveal crop. See
        # kaine/modules/topos/foveation.py and openspec topos-foveation.
        foveation_enabled: bool = False,
        foveation_grid: tuple[int, int] = (12, 12),
        foveation_hysteresis: float = 0.15,
        foveation_size_range: tuple[float, float] = (0.12, 0.5),
        peripheral_size: tuple[int, int] = (320, 180),
        foveal_size: tuple[int, int] = (224, 224),
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
        if int(clip_stride) < 1:
            raise ValueError("clip_stride must be >= 1")
        # Encoder selection (topos-temporal-video-encoder). An explicitly injected
        # encoder wins (tests, custom wiring); otherwise the encoder_backend
        # selector builds one (default: the temporally-native InternVideo-Next
        # clip encoder). model_id=None lets make_encoder pick the per-backend id.
        self._encoder: Encoder = encoder or make_encoder(
            encoder_backend,
            model_id=encoder_model_id,
            device_preference=device_preference,
            weights_dir=encoder_weights_dir,
            clip_len=encoder_clip_len,
            pooling=encoder_pooling,
            clip_resolution=encoder_clip_resolution,
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

        # Clip-native seam (topos-temporal-video-encoder §1a). The ring buffer is
        # a bounded, RAM-ONLY deque of the most recent `clip_len` frames — it is
        # NEVER serialized (see serialize()) and NEVER written to disk; each frame
        # is released as it ages out of the bounded deque, exactly as a single
        # frame was dropped before. `clip_len` is the encoder's frame count
        # (1 for the DINOv2 fallback / per-frame test doubles, 16 for
        # InternVideo-Next). One clip latent is produced every `clip_stride`
        # frame-ticks once the buffer fills; no topos.report is published during
        # the warmup before the first fill.
        self._clip_len: int = int(getattr(self._encoder, "clip_len", 1))
        self._clip_stride: int = int(clip_stride)
        self._frame_buffer: deque[Any] = deque(maxlen=self._clip_len)
        self._frames_seen: int = 0

        # Spatial foveation (per-frame, topos-foveation) and a temporally-native
        # multi-frame clip encoder are alternative encoding regimes and do not
        # compose; the design specifies foveation against a per-frame encoder.
        # Reject the combination loudly rather than silently mis-encode.
        if foveation_enabled and self._clip_len > 1:
            raise ValueError(
                "foveation requires a per-frame encoder (clip_len == 1); the "
                f"selected encoder has clip_len == {self._clip_len}. Use "
                "encoder_backend='dinov2' with foveation, or disable foveation."
            )

        # Hypnos sleep flag — suspend forward-model adaptation during sleep.
        self._in_hypnos: bool = False
        self._hypnos_cursor: str = "$"

        # Attention-driven foveation state (topos-foveation). All memory-only.
        self._foveation_enabled: bool = bool(foveation_enabled)
        self._foveation_size_range: tuple[float, float] = (
            float(foveation_size_range[0]),
            float(foveation_size_range[1]),
        )
        self._foveation_hysteresis: float = float(foveation_hysteresis)
        self._peripheral_size: tuple[int, int] = (
            int(peripheral_size[0]),
            int(peripheral_size[1]),
        )
        self._foveal_size: tuple[int, int] = (
            int(foveal_size[0]),
            int(foveal_size[1]),
        )
        self._saliency: Optional[SpatialSaliency] = (
            SpatialSaliency(grid=foveation_grid) if self._foveation_enabled else None
        )
        self._prev_fovea: Optional[FoveaTarget] = None
        # Attention schema (topos-foveation Phase 2): a small forward model of the
        # fovea's own trajectory. Each foveated tick it predicts the *next* fovea
        # location from the recent gaze motion; the content-free prediction rides
        # in the report for the self-model and diagnostics. Memory-only, only
        # instantiated when foveation is on.
        self._fovea_predictor: Optional[FoveaPredictor] = (
            FoveaPredictor() if self._foveation_enabled else None
        )
        # Injected seams (wired at boot, like the affect / speaking-gate seams).
        # Topos never imports the workspace: the top-down bias provider returns a
        # saliency-grid-shaped bias map (or None) sourced from the workspace /
        # Nous / a goal, and the arousal provider returns the current Thymos
        # arousal scalar in [0, 1] that sizes the fovea (Easterbrook narrowing).
        self._top_down_bias_provider: Optional[Any] = None
        self._arousal_provider: Optional[Any] = None

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

    @property
    def foveation_enabled(self) -> bool:
        """Whether attention-driven foveation is active (topos-foveation)."""
        return self._foveation_enabled

    def set_top_down_bias_provider(self, provider: Optional[Any]) -> None:
        """Inject the workspace→Topos top-down attention channel.

        ``provider`` is a zero-arg callable returning either ``None`` (no bias
        this tick) or a 2-D saliency bias map; a map whose shape differs from the
        spatial-saliency grid is resized to the grid before combination. Topos
        never imports the workspace — this seam is wired at boot.
        """
        self._top_down_bias_provider = provider

    def set_arousal_provider(self, provider: Optional[Any]) -> None:
        """Inject the Thymos arousal channel that sizes the fovea.

        ``provider`` is a zero-arg callable returning the current arousal scalar
        in [0, 1]. This is the distinct *visual* coupling (Easterbrook
        narrowing), NOT the Syneidesis salience-selection window.
        """
        self._arousal_provider = provider

    def _read_top_down_bias(self, grid_shape: tuple[int, int]) -> Any:
        """Pull the top-down bias map from the provider, resized to the saliency
        grid. Returns None on no provider, no bias, or any provider failure —
        foveation degrades to bottom-up-only rather than breaking perception."""
        if self._top_down_bias_provider is None:
            return None
        try:
            bias = self._top_down_bias_provider()
        except Exception:
            log.debug("topos top-down bias provider failed (non-fatal)", exc_info=True)
            return None
        if bias is None:
            return None
        import numpy as np

        arr = np.asarray(bias, dtype=np.float32)
        if arr.shape == grid_shape:
            return arr
        from kaine.modules.topos.foveation import _lazy_cv2

        cv2 = _lazy_cv2()
        gh, gw = grid_shape
        return cv2.resize(arr, (gw, gh), interpolation=cv2.INTER_AREA)

    def _read_arousal(self) -> float:
        """Pull the current arousal scalar; 0.0 (widest fovea) on absence/failure."""
        if self._arousal_provider is None:
            return 0.0
        try:
            return float(self._arousal_provider())
        except Exception:
            log.debug("topos arousal provider failed (non-fatal)", exc_info=True)
            return 0.0

    async def _encode_clip(self, frames: list[Any]) -> list[float]:
        """Encode the current clip via the encoder's clip seam.

        Prefers ``encode_clip`` (DINOv2 fallback encodes the last frame;
        InternVideo-Next pools a 16-frame clip). Minimal per-frame test doubles
        that predate the clip seam fall back to ``encode(frames[-1])``."""
        enc = self._encoder
        encode_clip = getattr(enc, "encode_clip", None)
        if encode_clip is not None:
            return await encode_clip(frames)
        return await enc.encode(frames[-1])

    async def process_frame(self, image: Any) -> str:
        # Clip-native ring buffer (topos-temporal-video-encoder §1a/§1b). Append
        # the incoming frame; publish nothing until the buffer first fills
        # (warmup), then produce one clip latent every `clip_stride` frame-ticks.
        self._frame_buffer.append(image)
        self._frames_seen += 1
        if len(self._frame_buffer) < self._clip_len:
            return ""  # warmup: no report until the ring buffer first fills
        if (self._frames_seen - self._clip_len) % self._clip_stride != 0:
            return ""  # off the strided-clip cadence; buffer and wait

        fovea: Optional[FoveaTarget] = None
        predicted_fovea: Optional[FoveaTarget] = None
        peripheral_latent: Any = None
        foveal_latent: Any = None
        if self._foveation_enabled and self._saliency is not None:
            # Spatial attention: coarse per-tile saliency, precision-weighted
            # combination with the top-down bias, arousal-sized single fovea.
            bottom_up = self._saliency.observe(image)
            top_down = self._read_top_down_bias(self._saliency.grid)
            combined = combine_saliency(bottom_up, top_down)
            fovea = select_fovea(
                combined,
                arousal=self._read_arousal(),
                size_range=self._foveation_size_range,
                prev=self._prev_fovea,
                hysteresis=self._foveation_hysteresis,
            )
            self._prev_fovea = fovea
            # Attention schema: predict where the fovea will be next tick from its
            # recent trajectory. Content-free; published alongside the fovea.
            if self._fovea_predictor is not None:
                predicted_fovea = self._fovea_predictor.predict_next(fovea)
            peripheral_view, foveal_view = foveate(
                image,
                fovea,
                peripheral_size=self._peripheral_size,
                foveal_size=self._foveal_size,
            )
            # Two encodes: peripheral gist drives change/habituation/salience
            # (whole-field continuity); foveal carries the attended detail.
            peripheral_latent = await self._encoder.encode(peripheral_view)
            foveal_latent = await self._encoder.encode(foveal_view)
            embedding = peripheral_latent
        else:
            embedding = await self._encode_clip(list(self._frame_buffer))
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

        report: dict[str, Any] = {
            "latent": embedding,
            "change_score": change,
            "habituation_score": habituation,
            "encoder_model_id": self._encoder.model_id,
            "prediction_error": prediction_error,
        }
        if fovea is not None:
            # Foveation on: `latent` is the peripheral gist (kept for backward-
            # compatible consumers); the attended detail and the content-free
            # fovea location ride alongside it.
            report["peripheral"] = peripheral_latent
            report["foveal"] = foveal_latent
            report["fovea"] = fovea.to_dict()
            # Attention schema: the content-free predicted next fovea location.
            if predicted_fovea is not None:
                report["predicted_fovea"] = predicted_fovea.to_dict()
        return await self.publish(
            "topos.report",
            report,
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
        # The frame ring buffer is RAM-only and is deliberately NOT included here
        # (zero-raw-sense-data persistence): only the encoder id and the forward
        # model's weights + a statistical buffer summary are emitted.
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
            fm_state = state["forward_model"]
            # Dim-cascade guard (topos-temporal-video-encoder §3, task 4.2): a
            # checkpoint sized to a different encoder latent_dim (e.g. an old
            # 384-dim DINOv2 snapshot loaded under the 768-dim InternVideo-Next
            # encoder) must NOT be forced into the running model. Discard it with
            # a warning; the online forward model re-learns from scratch (it is an
            # online adapter — safe) rather than raising a shape error.
            if not self._forward_model.matches_state_shape(fm_state):
                log.warning(
                    "topos: discarding forward-model checkpoint — its tensor "
                    "shapes do not match the running encoder latent_dim %d; the "
                    "online forward model will re-learn from scratch",
                    self._forward_model.latent_dim,
                )
            else:
                self._forward_model.load_state_dict(fm_state)
