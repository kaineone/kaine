# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""vox — the entity's voice.

Consumes `lingua.external` text, synthesizes it via Chatterbox (voice params
modulated by Thymos affect), plays it through an output device, and releases it.

Playback (`playback_enabled`, default true) is the primary action: the clip is
played on the configured/default device and discarded. Synthesized speech is a
transient utterance, not a recording — so the file sink is OFF by default
(`sink_enabled=false`). When the sink is enabled it is bounded: only the newest
`retain_count` clips are kept, so it never grows without limit.

Self-hearing suppression (`suppress_self_hearing`, default true) opens a shared
SpeakingGate while a clip plays so an open mic does not transcribe the entity's
own voice. Operators with an acoustically isolated input (a headset mic) set it
false to stay full-duplex. See `coordination.py` and `playback.py`.

Prosodic mirroring (`[vox.mirroring].enabled`, default false) blends a bounded
residual of the latest `audition.prosody` features into the affect-driven
ChatterboxParams. The entity's base voice identity (predefined_voice_id) is
never altered; only expressive dynamics are nudged. When disabled or when no
prosody has been seen, synthesis falls back to affect-only parameters.
See `mirroring.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.modules.vox.client import (
    ChatterboxClient,
    SynthesisResult,
    TTSClient,
    TTSRequest,
)
from kaine.modules.vox.coordination import SpeakingGate
from kaine.modules.vox.mapping import (
    ChatterboxParams,
    affect_to_chatterbox,
)
from kaine.modules.vox.mirroring import blend_prosody, decayed_strength
from kaine.modules.vox.playback import (
    Player,
    TeePlayer,
    build_player,
    wav_duration_s,
)
from kaine.modules.base import BaseModule
from kaine.modules.thymos.state import DimensionalState

log = logging.getLogger(__name__)


class Vox(BaseModule):
    name: ClassVar[str] = "vox"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        tts_client: Optional[TTSClient] = None,
        player: Optional[Player] = None,
        chatterbox_url: str = "http://127.0.0.1:8883",
        voice_mode: str = "predefined",
        predefined_voice_id: Optional[str] = None,
        output_format: str = "wav",
        sink_path: Path | str = "state/vox",
        playback_enabled: bool = True,
        output_device: str = "",
        sink_enabled: bool = False,
        retain_count: int = 0,
        suppress_self_hearing: bool = True,
        mic_mute_hangover_ms: int = 600,
        speaking_gate: Optional[SpeakingGate] = None,
        baseline_temperature: float = 0.7,
        baseline_exaggeration: float = 0.5,
        baseline_cfg_weight: float = 0.5,
        request_timeout_s: float = 120.0,
        baseline_salience: float = 0.3,
        alert_salience: float = 0.7,
        lingua_external_stream: str = "lingua.external",
        thymos_state_stream: str = "thymos.out",
        # Prosodic mirroring (disabled by default).
        mirroring_enabled: bool = False,
        mirror_strength: float = 0.3,
        mirror_ceiling: float = 0.5,
        mirror_decay_s: float = 10.0,
        audition_prosody_stream: str = "audition.out",
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if retain_count < 0:
            raise ValueError("retain_count must be >= 0")
        self._tts_client: TTSClient = tts_client or ChatterboxClient(
            base_url=chatterbox_url, timeout_s=request_timeout_s
        )
        self._player: Player = player or build_player(
            playback_enabled=playback_enabled, output_device=output_device
        )
        self._voice_mode = voice_mode
        self._voice_id = predefined_voice_id
        self._output_format = output_format
        self._sink_path = Path(sink_path)
        self._sink_enabled = bool(sink_enabled)
        self._retain_count = int(retain_count)
        self._suppress_self_hearing = bool(suppress_self_hearing)
        self._mic_mute_hangover_s = max(0.0, float(mic_mute_hangover_ms) / 1000.0)
        self._speaking_gate = speaking_gate
        self._baseline_temperature = float(baseline_temperature)
        self._baseline_exaggeration = float(baseline_exaggeration)
        self._baseline_cfg_weight = float(baseline_cfg_weight)
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._lingua_stream = lingua_external_stream
        self._thymos_stream = thymos_state_stream
        self._cursors: dict[str, str] = {}
        self._current_state: DimensionalState = DimensionalState()
        # Prosodic mirroring state.
        self._mirroring_enabled = bool(mirroring_enabled)
        # Clamp mirror_strength to [0, mirror_ceiling] at init time.
        self._mirror_ceiling = float(mirror_ceiling)
        self._mirror_strength = min(float(mirror_strength), self._mirror_ceiling)
        self._mirror_decay_s = float(mirror_decay_s)
        self._audition_prosody_stream = audition_prosody_stream
        # Latest cached prosody features (numeric) and arrival timestamp.
        self._latest_prosody: Optional[dict[str, Any]] = None
        self._latest_prosody_ts: float = 0.0

    def set_speaking_gate(self, gate: SpeakingGate) -> None:
        """Inject the shared self-hearing gate (wired in build_registry)."""
        self._speaking_gate = gate

    @property
    def current_affect(self) -> DimensionalState:
        return self._current_state

    @property
    def tts_client(self) -> TTSClient:
        return self._tts_client

    async def initialize(self) -> None:
        if self._sink_enabled:
            self._sink_path.mkdir(parents=True, exist_ok=True)
        # Surface (but never auto-delete) any clips left by prior runs of the
        # old unbounded-persistence behavior, so the operator knows they exist.
        try:
            existing = list(self._sink_path.glob(f"*.{self._output_format}"))
        except OSError:
            existing = []
        if existing:
            total = sum(p.stat().st_size for p in existing if p.exists())
            log.info(
                "vox sink holds %d pre-existing clip(s) (%.1f MB) at %s; "
                "not auto-deleted",
                len(existing),
                total / 1_000_000.0,
                self._sink_path,
            )
        # Determine which streams to subscribe to.
        streams_to_subscribe = [self._lingua_stream, self._thymos_stream]
        if self._mirroring_enabled:
            streams_to_subscribe.append(self._audition_prosody_stream)
        for stream in streams_to_subscribe:
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
                self._consumer_loop(), name=f"{self.name}-consumer"
            )
        )

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._tts_client.aclose()
        except Exception:
            log.warning("vox tts client close failed", exc_info=True)

    async def synthesize_text(
        self,
        text: str,
        *,
        state: Optional[DimensionalState] = None,
    ) -> SynthesisResult:
        """Direct synthesis API for tests and callers without a bus loop."""
        params = self._params_for(state or self._current_state)
        request = self._build_request(text, params)
        result = await self._tts_client.synthesize(request)
        if self._sink_enabled:
            await self._sink_audio(text, result)
        await self._play(result)
        await self._publish_event(text, params, result, success=True)
        return result

    def add_playback_tap(self, tap: Player) -> None:
        """Compose an additional Player that receives every clip the primary
        player plays (e.g. the remote bridge streaming speech to operator
        clients). The primary player and self-hearing gating are unchanged;
        a failing tap never breaks local playback."""
        self._player = TeePlayer(self._player, tap)

    async def _play(self, result: SynthesisResult) -> None:
        """Play the clip aloud and, when self-hearing suppression is on, open
        the speaking window so audition drops the entity's own voice."""
        if self._suppress_self_hearing and self._speaking_gate is not None:
            window = wav_duration_s(result.audio) + self._mic_mute_hangover_s
            self._speaking_gate.mark_speaking(window)
        try:
            await self._player.play(result.audio, output_format=result.output_format)
        except Exception:
            # Playback must never break the synthesis/eventing path.
            log.warning("vox playback raised", exc_info=True)

    def _params_for(self, state: DimensionalState) -> ChatterboxParams:
        params = affect_to_chatterbox(
            state,
            baseline_temperature=self._baseline_temperature,
            baseline_exaggeration=self._baseline_exaggeration,
            baseline_cfg_weight=self._baseline_cfg_weight,
        )
        if (
            self._mirroring_enabled
            and self._latest_prosody is not None
        ):
            effective_strength = decayed_strength(
                self._mirror_strength,
                self._latest_prosody_ts,
                time.monotonic(),
                self._mirror_decay_s,
            )
            if effective_strength > 0.0:
                params = blend_prosody(
                    params,
                    self._latest_prosody,
                    effective_strength,
                )
        return params

    def _build_request(self, text: str, params: ChatterboxParams) -> TTSRequest:
        return TTSRequest(
            text=text,
            voice_mode=self._voice_mode,
            predefined_voice_id=self._voice_id,
            output_format=self._output_format,
            temperature=params.temperature,
            exaggeration=params.exaggeration,
            cfg_weight=params.cfg_weight,
            speed_factor=params.speed_factor,
        )

    async def _sink_audio(self, text: str, result: SynthesisResult) -> None:
        # Filename: timestamp + uuid + format. Keeps writes serializable
        # across concurrent syntheses.
        name = f"{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}.{result.output_format}"
        path = self._sink_path / name
        try:
            path.write_bytes(result.audio)
        except Exception:
            log.exception("vox sink write failed for %s", path)
            return
        self._prune_sink()

    def _prune_sink(self) -> None:
        """Keep at most `retain_count` newest clips; delete older ones.

        `retain_count == 0` means the sink is transient — a written clip is
        removed immediately after playback's reference is gone.
        """
        try:
            clips = sorted(
                self._sink_path.glob(f"*.{self._output_format}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for stale in clips[self._retain_count:]:
            try:
                stale.unlink()
            except OSError:
                log.debug("vox sink prune could not remove %s", stale)

    async def _publish_event(
        self,
        text: str,
        params: ChatterboxParams,
        result: SynthesisResult,
        *,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        payload: dict[str, Any] = {
            "text_length": len(text),
            "bytes_produced": result.bytes_produced if success else 0,
            "output_format": result.output_format if success else self._output_format,
            "voice": self._voice_id or "(default)",
            "exaggeration": params.exaggeration,
            "cfg_weight": params.cfg_weight,
            "temperature": params.temperature,
            "speed_factor": params.speed_factor,
            "latency_ms": result.latency_ms if success else 0.0,
            "success": success,
        }
        if error is not None:
            payload["error"] = error
        salience = self._baseline_salience if success else self._alert_salience
        await self.publish("vox.synthesized", payload, salience=salience)

    async def _consumer_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                progressed = False
                active_streams = [self._lingua_stream, self._thymos_stream]
                if self._mirroring_enabled:
                    active_streams.append(self._audition_prosody_stream)
                for stream in active_streams:
                    try:
                        entries = await self._bus.read(
                            stream,
                            last_id=self._cursors.get(stream, "0"),
                            count=32,
                            block_ms=0,
                        )
                    except Exception:
                        continue
                    if entries:
                        progressed = True
                        self._cursors[stream] = entries[-1][0]
                        for _, event in entries:
                            await self._handle(stream, event)
                if not progressed:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _handle(self, stream: str, event: Event) -> None:
        if stream == self._thymos_stream and event.type == "thymos.state":
            state_dict = event.payload.get("state") or {}
            try:
                self._current_state = DimensionalState(
                    valence=float(state_dict.get("valence", 0.0)),
                    arousal=float(state_dict.get("arousal", 0.3)),
                    dominance=float(state_dict.get("dominance", 0.0)),
                ).clamped()
            except Exception:
                log.warning("failed to parse thymos.state payload", exc_info=True)
        elif stream == self._audition_prosody_stream and event.type == "audition.prosody":
            # Cache the latest numeric prosody features; discard raw audio.
            # Only the numeric payload fields are kept — zero raw-sense-data.
            payload = event.payload
            try:
                self._latest_prosody = {
                    "f0_mean_hz": float(payload.get("f0_mean_hz", 0.0)),
                    "f0_std_hz": float(payload.get("f0_std_hz", 0.0)),
                    "f0_voiced_frac": float(payload.get("f0_voiced_frac", 0.0)),
                    "rms_mean": float(payload.get("rms_mean", 0.0)),
                    "rms_std": float(payload.get("rms_std", 0.0)),
                    "tempo_bpm": float(payload.get("tempo_bpm", 0.0)),
                }
                self._latest_prosody_ts = time.monotonic()
            except Exception:
                log.warning("failed to parse audition.prosody payload", exc_info=True)
        elif stream == self._lingua_stream:
            text = event.payload.get("text") or ""
            if not text:
                return
            try:
                await self.synthesize_text(text)
            except Exception as exc:
                log.exception("vox synthesis failed")
                await self._publish_event(
                    text,
                    self._params_for(self._current_state),
                    SynthesisResult(
                        audio=b"", content_type="", latency_ms=0.0,
                        output_format=self._output_format, bytes_produced=0,
                    ),
                    success=False,
                    error=f"{type(exc).__name__}: {exc}",
                )

    def serialize(self) -> dict[str, Any]:
        return {
            "current_state": {
                "valence": self._current_state.valence,
                "arousal": self._current_state.arousal,
                "dominance": self._current_state.dominance,
            },
            "voice_mode": self._voice_mode,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        if "current_state" in state:
            s = state["current_state"]
            self._current_state = DimensionalState(
                valence=float(s.get("valence", 0.0)),
                arousal=float(s.get("arousal", 0.3)),
                dominance=float(s.get("dominance", 0.0)),
            ).clamped()
