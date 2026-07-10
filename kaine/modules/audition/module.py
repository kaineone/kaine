# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable, ClassVar, Optional, TYPE_CHECKING

from kaine.bus.client import AsyncBus

if TYPE_CHECKING:
    from kaine.modules.vox.coordination import SpeakingGate
from kaine.modules.audition.emotion import (
    CATEGORIES,
    EmotionClassifier,
    Emotion2vecClassifier,
    EmotionResult,
    NullEmotionClassifier,
)
from kaine.modules.audition.acoustic import (
    AcousticEncoder,
    SpectralAcousticEncoder,
    arousal_to_window,
    cosine_change,
    detect_speech,
)
from kaine.modules.audition.forward import (
    AuditoryForwardModel,
    FEATURE_DIM,
    build_feature_vector,
)
from kaine.modules.audition.live import (
    LiveMicConfig,
    LiveMicrophone,
    PerceptionUnavailableError,
)
from kaine.modules.audition.stt_client import (
    SpeachesClient,
    STTClient,
    TranscriptionResult,
)
from kaine.modules.base import BaseModule

log = logging.getLogger(__name__)


class Audition(BaseModule):
    name: ClassVar[str] = "audition"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        stt_client: Optional[STTClient] = None,
        emotion_classifier: Optional[EmotionClassifier] = None,
        speaches_url: str = "http://127.0.0.1:8000",
        stt_model: str = "Systran/faster-distil-whisper-medium.en",
        emotion_model_id: str = "emotion2vec/emotion2vec_plus_base",
        emotion_device: str = "cpu",
        request_timeout_s: float = 60.0,
        baseline_salience: float = 0.4,
        alert_salience: float = 0.8,
        # Live microphone (eyes-and-ears). See kaine/modules/audition/live.py.
        capture_enabled: bool = False,
        live_microphone: Optional[LiveMicrophone] = None,
        live_mic_config: Optional[LiveMicConfig] = None,
        # Deterministic audio feed seam (unified-perception-feed). When boot
        # selects a seeded/playlist mode it injects an _AudioStream factory here,
        # the precise mirror of Topos.source_factory; None = the real mic.
        stream_factory: Optional[Callable[..., Any]] = None,
        # Self-hearing suppression. Shared gate injected in build_registry; while
        # vox is playing the entity's own voice, captured utterances are
        # dropped so the entity does not transcribe itself. None = no gate.
        speaking_gate: Optional["SpeakingGate"] = None,
        # Forward model knobs (disabled by default — purely additive).
        forward_model_units: int = 32,
        prediction_error_window: int = 32,
        auditory_buffer_size: int = 16,
        # Prosody extraction (disabled by default — purely additive).
        prosody_enabled: bool = False,
        # General auditory perception (auditory-perception). Off by default → the
        # existing speech pipeline is unchanged. When enabled, each captured window
        # is encoded to a general acoustic embedding and scored for salience by
        # change + forward-model prediction error over that embedding, so any sound
        # (not only a voice) is perceived; speech-to-text and vocal emotion run as
        # a specialization on windows detected as speech. See
        # kaine/modules/audition/acoustic.py and openspec auditory-perception.
        general_audition: bool = False,
        acoustic_encoder: Optional[AcousticEncoder] = None,
        arousal_window_range: tuple[float, float] = (0.15, 1.0),
        acoustic_change_alert_threshold: float = 0.35,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        self._stt_client: STTClient = stt_client or SpeachesClient(
            base_url=speaches_url, timeout_s=request_timeout_s
        )
        # Vocal emotion is a Tier-2-only faculty (emotion2vec+ has no clean edge
        # port). An empty emotion_model_id explicitly disables it — the Tier-0/1
        # case — via the Null classifier, which still lets speech be transcribed
        # (openspec runtime-backends). A non-empty id loads emotion2vec+ as before.
        if emotion_classifier is not None:
            self._emotion_classifier = emotion_classifier
        elif not (emotion_model_id or "").strip():
            self._emotion_classifier = NullEmotionClassifier()
        else:
            self._emotion_classifier = Emotion2vecClassifier(
                model_id=emotion_model_id, device=emotion_device
            )
        self._emotion_device = emotion_device
        self._stt_model = stt_model
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._capture_enabled = bool(capture_enabled)
        self._speaking_gate = speaking_gate
        self._stream_factory = stream_factory
        self._live_mic: Optional[LiveMicrophone] = None
        if self._capture_enabled or live_microphone is not None:
            self._live_mic = live_microphone or self._build_default_live_mic(
                live_mic_config
            )

        # Forward model — always instantiated (cheap, CPU-only MLP). Unlike
        # Chronos/Topos there is deliberately no `forward_prediction` toggle:
        # prediction error only ever *weights* salience here, never gates
        # transcription/emotion output, so it is safe to leave always-on.
        self._forward_model = AuditoryForwardModel(
            feature_dim=FEATURE_DIM,
            units=int(forward_model_units),
            auditory_buffer_size=int(auditory_buffer_size),
        )
        self._prediction_error_window_size = max(1, int(prediction_error_window))
        self._prediction_errors: deque[float] = deque(
            maxlen=self._prediction_error_window_size
        )

        # Prosody flag.
        self._prosody_enabled = bool(prosody_enabled)

        # General auditory perception (auditory-perception). All memory-only.
        self._general_audition = bool(general_audition)
        self._arousal_window_range = (
            float(arousal_window_range[0]),
            float(arousal_window_range[1]),
        )
        self._acoustic_change_alert_threshold = float(acoustic_change_alert_threshold)
        self._acoustic_encoder: Optional[AcousticEncoder] = None
        self._acoustic_forward_model: Optional[AuditoryForwardModel] = None
        self._prev_acoustic_embedding: Optional[list[float]] = None
        self._acoustic_errors: deque[float] = deque(
            maxlen=self._prediction_error_window_size
        )
        if self._general_audition:
            self._acoustic_encoder = acoustic_encoder or SpectralAcousticEncoder()
            self._acoustic_forward_model = AuditoryForwardModel(
                feature_dim=self._acoustic_encoder.embedding_dim,
                units=int(forward_model_units),
                auditory_buffer_size=int(auditory_buffer_size),
            )
        # Arousal seam (wired at boot, like the topos-arousal / affect seams): a
        # zero-arg callable returning the current Thymos arousal in [0, 1] that
        # sizes the auditory attentional window. Audition never imports the
        # workspace; None → widest window.
        self._arousal_provider: Optional[Callable[[], float]] = None

    @property
    def stt_client(self) -> STTClient:
        return self._stt_client

    @property
    def emotion_classifier(self) -> EmotionClassifier:
        return self._emotion_classifier

    def set_speaking_gate(self, gate: "SpeakingGate") -> None:
        """Inject the shared self-hearing gate (wired in build_registry)."""
        self._speaking_gate = gate

    @property
    def general_audition(self) -> bool:
        """Whether general auditory perception is active (auditory-perception)."""
        return self._general_audition

    def set_arousal_provider(self, provider: Optional[Callable[[], float]]) -> None:
        """Inject the Thymos arousal channel that sizes the auditory window.

        Zero-arg callable returning arousal in [0, 1]. Distinct affective→auditory
        coupling (Easterbrook), mirroring the topos-arousal seam.
        """
        self._arousal_provider = provider

    def _read_arousal(self) -> float:
        if self._arousal_provider is None:
            return 0.0
        try:
            return float(self._arousal_provider())
        except Exception:
            log.debug("audition arousal provider failed (non-fatal)", exc_info=True)
            return 0.0

    async def _perceive_acoustic(
        self, audio_bytes: bytes, sample_rate: int, source_label: str
    ) -> None:
        """General acoustic perception: encode the window, score salience by change
        and forward-model prediction error over the embedding, and publish a
        content-free ``audition.perception`` event so any sound — not only a voice —
        reaches the workspace. Memory-only; never writes audio."""
        assert self._acoustic_encoder is not None
        assert self._acoustic_forward_model is not None
        embedding = self._acoustic_encoder.embed(audio_bytes, sample_rate)
        change = cosine_change(embedding, self._prev_acoustic_embedding)
        self._prev_acoustic_embedding = embedding
        prediction_error = self._acoustic_forward_model.step(embedding)
        self._acoustic_errors.append(prediction_error)
        # Normalise the error against its rolling mean (Chronos/Topos convention):
        # steady, predictable sound stays low-salience even at non-zero error.
        mean_err = (
            sum(self._acoustic_errors) / len(self._acoustic_errors)
            if self._acoustic_errors
            else 0.0
        )
        normalised = prediction_error / mean_err if mean_err > 0 else 0.0
        alert = normalised >= 2.0 or change >= self._acoustic_change_alert_threshold
        salience = self._alert_salience if alert else self._baseline_salience
        window = arousal_to_window(
            self._read_arousal(), window_range=self._arousal_window_range
        )
        await self.publish(
            "audition.perception",
            {
                "source_label": source_label,
                "change_score": change,
                "prediction_error": prediction_error,
                "encoder_model_id": self._acoustic_encoder.model_id,
                "attended_window": window,
            },
            salience=salience,
        )

    async def initialize(self) -> None:
        await super().initialize()
        if self._live_mic is not None:
            try:
                await self._live_mic.initialize()
            except PerceptionUnavailableError as exc:
                log.warning(
                    "live microphone disabled: %s (install kaine[audio] to enable)",
                    exc,
                )
                self._live_mic = None

    async def shutdown(self) -> None:
        if self._live_mic is not None:
            try:
                await self._live_mic.shutdown()
            except Exception:
                log.warning("live mic shutdown failed", exc_info=True)
        await super().shutdown()
        for closeable in (self._stt_client, self._emotion_classifier):
            try:
                shutdown = getattr(closeable, "shutdown", None) or getattr(
                    closeable, "aclose", None
                )
                if shutdown:
                    await shutdown()
            except Exception:
                log.warning("audition collaborator shutdown failed", exc_info=True)

    def _build_default_live_mic(
        self, mic_config: Optional[LiveMicConfig]
    ) -> LiveMicrophone:
        from kaine import perception_state

        # Locus gate selection mirrors Topos: a wired deterministic stream_factory
        # IS the virtual world (seeded/playlist feed) and binds to the `virtual`
        # locus; the bare sounddevice path is the real mic and binds to
        # `physical`. Selecting the matching gate is what lets the configured
        # seeded feed deliver — the physical gate would keep the virtual feed
        # muted forever (it requires locus == "physical").
        desired_reader = (
            perception_state.effective_virtual_audio_capture
            if self._stream_factory is not None
            else perception_state.effective_audio_capture
        )

        return LiveMicrophone(
            sink=self.process_audio,
            config=mic_config or LiveMicConfig(),
            state_writer=perception_state.update_audio_runtime,
            # locus-gated: the real mic runs only when audio is desired AND the
            # perceptual locus is `physical`; the virtual (seeded/playlist) feed
            # runs only when audio is desired AND the locus is `virtual`.
            desired_state_reader=desired_reader,
            # Deterministic feed seam: when boot injected an _AudioStream
            # factory (seeded/playlist mode) the mic reads from it instead of
            # the real sounddevice input. None falls back to the live mic.
            stream_factory=self._stream_factory,
        )

    async def process_audio(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        *,
        source_label: str = "microphone",
    ) -> tuple[Optional[TranscriptionResult], Optional[EmotionResult]]:
        """Run STT and emotion classification in parallel. Publishes both
        events regardless of partial failure. Returns the results (or
        None on failure) for callers that need them directly.

        Self-hearing guard: if vox is currently playing the entity's own
        voice (the shared speaking gate is open), drop this capture entirely so
        the entity never transcribes itself as a user utterance."""
        if self._speaking_gate is not None and self._speaking_gate.is_speaking():
            log.debug("audition dropped self-heard capture during playback")
            return None, None

        # General auditory perception: perceive every window as sound (any sound,
        # not only a voice), then run the speech specialization only on windows
        # detected as speech. When disabled, the whole window is treated as speech
        # so the existing pipeline is byte-for-byte unchanged.
        if self._general_audition:
            await self._perceive_acoustic(audio_bytes, sample_rate, source_label)
            if not detect_speech(audio_bytes, sample_rate):
                return None, None

        start_time = time.monotonic()

        stt_task = asyncio.create_task(
            self._stt_client.transcribe(
                audio_bytes, sample_rate=sample_rate, model=self._stt_model
            )
        )
        emo_task = asyncio.create_task(
            self._emotion_classifier.classify(audio_bytes, sample_rate=sample_rate)
        )
        stt_result_or_exc, emo_result_or_exc = await asyncio.gather(
            stt_task, emo_task, return_exceptions=True
        )

        duration_s = time.monotonic() - start_time

        # ------------------------------------------------------------------
        # Forward model step: build feature vector from emotion result.
        # ------------------------------------------------------------------
        if isinstance(emo_result_or_exc, BaseException):
            # On error use a neutral distribution.
            emo_scores_for_fm = {
                c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES
            }
        else:
            emo_scores_for_fm = emo_result_or_exc.scores

        # Compute a simple mean energy from the audio bytes (in-memory only).
        mean_energy = _estimate_energy(audio_bytes)

        feature_vec = build_feature_vector(
            emo_scores_for_fm,
            CATEGORIES,
            duration_s=min(duration_s, 60.0) / 60.0,  # normalise to [0, 1] over 60 s
            mean_energy=mean_energy,
        )

        prediction_error = self._forward_model.step(feature_vec)
        self._prediction_errors.append(prediction_error)
        error_window = list(self._prediction_errors)

        # ------------------------------------------------------------------
        # Prosody (gated by prosody_enabled).
        # ------------------------------------------------------------------
        if self._prosody_enabled:
            asyncio.create_task(
                self._extract_and_publish_prosody(
                    audio_bytes, sample_rate, source_label
                )
            )

        # ------------------------------------------------------------------
        # Publish transcription and emotion, salience weighted by error.
        # ------------------------------------------------------------------
        stt_result: Optional[TranscriptionResult] = None
        if isinstance(stt_result_or_exc, BaseException):
            await self._publish_transcription_error(
                source_label=source_label,
                sample_rate=sample_rate,
                audio_bytes_length=len(audio_bytes),
                exc=stt_result_or_exc,
            )
        else:
            stt_result = stt_result_or_exc
            await self._publish_transcription(
                stt_result,
                source_label,
                sample_rate,
                len(audio_bytes),
                prediction_error=prediction_error,
                error_window=error_window,
            )

        emo_result: Optional[EmotionResult] = None
        if isinstance(emo_result_or_exc, BaseException):
            await self._publish_emotion_error(
                source_label=source_label,
                exc=emo_result_or_exc,
            )
        else:
            emo_result = emo_result_or_exc
            await self._publish_emotion(
                emo_result,
                source_label,
                prediction_error=prediction_error,
                error_window=error_window,
            )

        return stt_result, emo_result

    # ------------------------------------------------------------------
    # Prosody helper
    # ------------------------------------------------------------------

    async def _extract_and_publish_prosody(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        source_label: str,
    ) -> None:
        """Extract prosody features in a thread and publish audition.prosody.

        ZERO PERSISTENCE: the NumPy array lives only in the thread call and
        is released on return. Nothing is written to disk.
        """
        from kaine.modules.audition.prosody import (
            audio_bytes_to_float32,
            extract_prosody,
        )

        try:
            audio_array = await asyncio.to_thread(
                audio_bytes_to_float32, audio_bytes, sample_rate=sample_rate
            )
            features = await asyncio.to_thread(
                extract_prosody, audio_array, sample_rate=sample_rate
            )
            await self.publish(
                "audition.prosody",
                {
                    "source_label": source_label,
                    **features,
                },
                salience=self._baseline_salience,
            )
        except Exception:
            log.warning("audition prosody extraction failed", exc_info=True)

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------

    def _error_weighted_salience(
        self,
        base_salience: float,
        prediction_error: float,
        error_window: list[float],
    ) -> float:
        """Return a salience blended between base_salience and the forward-
        model error-weighted salience.  The error contribution is additive
        on top of the base; the result is clamped to [base_salience, alert].
        """
        error_salience = self._forward_model.prediction_error_to_salience(
            prediction_error,
            self._baseline_salience,
            self._alert_salience,
            error_window=error_window,
        )
        # Take the maximum: error can only raise salience, never lower it.
        blended = max(base_salience, error_salience)
        return min(blended, self._alert_salience)

    async def _publish_transcription(
        self,
        result: TranscriptionResult,
        source_label: str,
        sample_rate: int,
        audio_bytes_length: int,
        *,
        prediction_error: float = 0.0,
        error_window: Optional[list[float]] = None,
    ) -> None:
        salience = self._error_weighted_salience(
            self._baseline_salience,
            prediction_error,
            error_window or [],
        )
        await self.publish(
            "audition.transcription",
            {
                "text": result.text,
                "source_label": source_label,
                "model": result.model,
                "sample_rate": int(sample_rate),
                "audio_bytes_length": int(audio_bytes_length),
                "latency_ms": result.latency_ms,
                "prediction_error": prediction_error,
            },
            salience=salience,
        )

    async def _publish_transcription_error(
        self,
        *,
        source_label: str,
        sample_rate: int,
        audio_bytes_length: int,
        exc: BaseException,
    ) -> None:
        await self.publish(
            "audition.transcription",
            {
                "text": "",
                "source_label": source_label,
                "model": self._stt_model,
                "sample_rate": int(sample_rate),
                "audio_bytes_length": int(audio_bytes_length),
                "latency_ms": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
            },
            salience=self._alert_salience,
        )

    async def _publish_emotion(
        self,
        result: EmotionResult,
        source_label: str,
        *,
        prediction_error: float = 0.0,
        error_window: Optional[list[float]] = None,
    ) -> None:
        # Base salience: alert for non-neutral emotions (existing behaviour).
        base_salience = (
            self._baseline_salience
            if result.category == "neutral"
            else self._alert_salience
        )
        salience = self._error_weighted_salience(
            base_salience,
            prediction_error,
            error_window or [],
        )
        payload: dict = {
            "category": result.category,
            "confidence": result.confidence,
            "scores": result.scores,
            "model": result.model,
            "source_label": source_label,
            "latency_ms": result.latency_ms,
            "prediction_error": prediction_error,
        }
        # Surface degraded flag so downstream consumers (e.g. Empatheia) can
        # tell that the emotion model did not actually run — the category/
        # confidence values are placeholders, not a real classification.
        if result.raw and result.raw.get("degraded"):
            payload["degraded"] = True
        await self.publish(
            "audition.emotion",
            payload,
            salience=salience,
        )

    async def _publish_emotion_error(
        self, *, source_label: str, exc: BaseException
    ) -> None:
        await self.publish(
            "audition.emotion",
            {
                "category": "neutral",
                "confidence": 0.0,
                "scores": {c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
                "model": self._emotion_classifier.model_id,
                "source_label": source_label,
                "latency_ms": 0.0,
                "error": f"{type(exc).__name__}: {exc}",
            },
            salience=self._alert_salience,
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "stt_model": self._stt_model,
            "emotion_model_id": self._emotion_classifier.model_id,
            "forward_model": self._forward_model.state_dict(),
            "auditory_buffer_summary": self._forward_model.buffer_summary(),
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        if "forward_model" in state:
            try:
                self._forward_model.load_state_dict(state["forward_model"])
            except Exception:
                log.warning(
                    "audition: failed to restore forward model weights", exc_info=True
                )


def _estimate_energy(audio_bytes: bytes) -> float:
    """Estimate mean RMS energy from raw bytes — purely in memory.

    Interprets the bytes as raw int16 PCM after skipping any WAV header.
    Returns a float in [0, 1].  Zero-persistence: no disk I/O.
    """
    import io
    import wave

    try:
        import numpy as np

        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                pcm = wf.readframes(wf.getnframes())
        except Exception:
            pcm = audio_bytes

        if len(pcm) < 2:
            return 0.0
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples**2)))
        return min(rms, 1.0)
    except Exception:
        return 0.0
