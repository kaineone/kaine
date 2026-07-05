# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phantasia — world-model / imagination module (DreamerV3 RSSM core).

Phantasia is KAINE's world model. It is NOT an agent: it has no actor, critic,
reward, or return head — action selection is Nous's job (pymdp active
inference). Phantasia only models and imagines.

Two modes:

  * **Waking (inference).** Each workspace tick, encode the snapshot to a
    fixed-width observation vector, fold it into the world model, and publish
    ``phantasia.world_error`` — a SALIENCE-ONLY prediction-error signal. It
    carries no imagined content. The observation is appended to a bounded
    in-memory ring buffer (the training corpus), which is NEVER serialized.

  * **Offline (Hypnos window only).** While a Hypnos maintenance window is open
    (tracked from ``hypnos.out``): (1) on a ``mnemos.replay`` cue, seed the
    world model from the prior trajectory and roll out imagined trajectories,
    publishing ``phantasia.scenario`` events — which, being published on
    ``phantasia.out``, are re-injected into the workspace broadcast so Nous,
    Thymos, and Eidolon process them via ``on_workspace`` (associative
    consolidation); (2) training over the accumulated buffer runs in-memory,
    gated by ``training_enabled``.

ZERO-PERSISTENCE (load-bearing): the trajectory buffer is in-memory only and is
never serialized to disk; a training pass writes NOTHING to disk; observation
vectors are derived numeric summaries (no raw audio/image bytes). ``serialize()``
emits only checkpoint *metadata* (path + encoder version), never the buffer or
weights.

WEIGHT PERSISTENCE (opt-in, ``persist_weights``): learned world-model
parameters are derived numeric weights, NOT sense data — when the operator
opts in, they are checkpointed via :mod:`.checkpoint` (atomic replace;
AES-256-GCM at rest when state encryption is on): loaded at initialize, saved
after each successful sleep-training pass and at shutdown. This requires a
backend with *real* learned parameters (``dreamerv3``); enabling it with the
``fake`` EMA stub is a configuration error — persisting the stub would dress
a fake up as learned state. An incompatible checkpoint fails closed at
initialize (never a silent discard-and-reinit). The trajectory buffer is
excluded regardless.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from pathlib import Path
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.phantasia.checkpoint import load_checkpoint, save_checkpoint
from kaine.modules.phantasia.encoder import (
    VERSION as ENCODER_VERSION,
    encode_snapshot,
    observation_dim,
)
from kaine.modules.phantasia.world_model import (
    CheckpointMismatchError,
    TrainOutcome,
    WorldModel,
    load_world_model,
)

log = logging.getLogger(__name__)


class Phantasia(BaseModule):
    name: ClassVar[str] = "phantasia"

    def __init__(
        self,
        bus: AsyncBus,
        *,
        world_model: Optional[WorldModel] = None,
        backend: str = "dreamerv3",
        training_enabled: bool = False,
        training_device: str = "cpu",
        trajectory_buffer_size: int = 512,
        rollout_horizon: int = 8,
        baseline_salience: float = 0.1,
        alert_salience: float = 0.7,
        # Opt-in learned-weight persistence (requires a real backend).
        persist_weights: bool = False,
        checkpoint_path: str = "state/phantasia/world_model.ckpt",
        # Peer streams: mnemos.replay cues + hypnos window tracking.
        mnemos_stream: str = "mnemos.out",
        hypnos_stream: str = "hypnos.out",
        # Forwarded to the real backend (ignored by the fake).
        world_model_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if trajectory_buffer_size <= 0:
            raise ValueError("trajectory_buffer_size must be positive")
        if rollout_horizon <= 0:
            raise ValueError("rollout_horizon must be positive")

        self._training_enabled = bool(training_enabled)
        self._training_device = str(training_device)
        self._rollout_horizon = int(rollout_horizon)
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._backend = str(backend)

        self._obs_dim = observation_dim()
        if world_model is not None:
            self._wm = world_model
        else:
            self._wm = load_world_model(
                backend, self._obs_dim, **(world_model_kwargs or {})
            )

        # Opt-in learned-weight persistence. Honesty guard: requires a world
        # model with REAL learned parameters to export — the fake EMA stub
        # deliberately lacks the capability, so enabling persistence with it
        # is a configuration error, not a silent no-op.
        self._persist_weights = bool(persist_weights)
        if self._persist_weights and not (
            hasattr(self._wm, "export_params") and hasattr(self._wm, "import_params")
        ):
            raise ValueError(
                "persist_weights=true requires a world model with real learned "
                "parameters (backend = \"dreamerv3\"); the "
                f"{self._backend!r} backend has nothing honest to persist."
            )

        # Bounded in-memory waking-trajectory ring buffer. NEVER serialized.
        self._buffer: deque[list[float]] = deque(maxlen=int(trajectory_buffer_size))

        # Offline state: Hypnos maintenance window flag.
        self._window_active: bool = False

        self._mnemos_stream = mnemos_stream
        self._hypnos_stream = hypnos_stream
        self._peer_cursors: dict[str, str] = {}

        # World-model checkpoint metadata. Set when weight persistence is
        # enabled; only metadata (never the weights/buffer) is serialized.
        self._checkpoint_path: Optional[str] = (
            str(checkpoint_path) if self._persist_weights else None
        )

    # ------------------------------------------------------------------
    # Accessors (tests / orchestration)
    # ------------------------------------------------------------------

    @property
    def world_model(self) -> WorldModel:
        return self._wm

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def window_active(self) -> bool:
        return self._window_active

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        # Load persisted world-model weights BEFORE anything else so an
        # incompatible checkpoint fails the boot closed (an operator decision,
        # never a silent discard of learned experience).
        self._load_weights_if_present()
        # Seed peer cursors to "now" so we only process new events.
        for stream in (self._mnemos_stream, self._hypnos_stream):
            try:
                latest = await self._bus.client.xrevrange(stream, count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                self._peer_cursors[stream] = entry_id
            else:
                self._peer_cursors[stream] = "0-0"
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._peer_consumer_loop(), name=f"{self.name}-peer-consumer"
            )
        )

    async def shutdown(self) -> None:
        # Persist learned weights before stopping so a graceful shutdown
        # (including an operator freeze) never loses learned experience.
        self._save_weights(reason="shutdown")
        await super().shutdown()

    # ------------------------------------------------------------------
    # Weight persistence (opt-in; weights only — NEVER the buffer)
    # ------------------------------------------------------------------

    def _load_weights_if_present(self) -> None:
        if not (self._persist_weights and self._checkpoint_path):
            return
        path = Path(self._checkpoint_path)
        if not path.is_file():
            log.info(
                "phantasia: no world-model checkpoint at %s — starting from "
                "fresh initialization (will save here)",
                path,
            )
            return
        blob = load_checkpoint(path)
        try:
            self._wm.import_params(blob, extra={"encoder_version": ENCODER_VERSION})
        except CheckpointMismatchError as exc:
            # Fail closed: discarding learned weights without operator consent
            # would destroy entity experience. The operator moves/deletes the
            # file or reverts the config change.
            raise CheckpointMismatchError(
                f"world-model checkpoint at {path} is incompatible with the "
                f"running configuration ({exc}). Move or delete the file, or "
                "revert the config/encoder change — refusing to silently "
                "discard learned weights."
            ) from exc
        log.info("phantasia: loaded world-model weights from %s", path)

    def _save_weights(self, *, reason: str) -> bool:
        """Checkpoint the learned weights (atomic; encrypted at rest when
        state encryption is on). Returns True on success; failures are logged
        as errors, never silently swallowed."""
        if not (self._persist_weights and self._checkpoint_path):
            return False
        try:
            blob = self._wm.export_params(extra={"encoder_version": ENCODER_VERSION})
            save_checkpoint(self._checkpoint_path, blob)
        except Exception:
            log.error(
                "phantasia: FAILED to save world-model weights to %s (%s) — "
                "learned state since the last successful save is at risk",
                self._checkpoint_path,
                reason,
                exc_info=True,
            )
            return False
        log.info(
            "phantasia: saved world-model weights to %s (%s)",
            self._checkpoint_path,
            reason,
        )
        return True

    # ------------------------------------------------------------------
    # Waking path: workspace broadcast -> world error
    # ------------------------------------------------------------------

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        """Each waking tick: encode, fold in, publish salience-only world error.

        During an open Hypnos window the live loop is suspended (external
        perception is off), so we skip waking inference and let the offline
        path drive scenario generation instead.
        """
        if self._window_active:
            return
        obs = encode_snapshot(snapshot)
        # Append to the bounded in-memory ring buffer (training corpus).
        self._buffer.append(obs)
        error = self._wm.observe(obs)
        await self._publish_world_error(error, snapshot.tick_index)

    async def _publish_world_error(self, error: float, tick_index: int) -> None:
        """Publish phantasia.world_error — SALIENCE-ONLY, no scenario content."""
        error = max(0.0, min(1.0, float(error)))
        salience = self._baseline_salience + error * (
            self._alert_salience - self._baseline_salience
        )
        await self.publish(
            "phantasia.world_error",
            {
                "world_error": error,
                "salience": salience,
                "tick_index": int(tick_index),
                # Discloses which world-model backend produced this signal.
                # "fake" = non-learning EMA stub; "dreamerv3" = real RSSM.
                "backend": self._backend,
            },
            salience=salience,
        )

    # ------------------------------------------------------------------
    # Offline path: mnemos.replay cue (Hypnos window only) -> scenarios
    # ------------------------------------------------------------------

    async def _peer_consumer_loop(self) -> None:
        """Background loop: track Hypnos window + handle mnemos.replay cues."""
        try:
            while not self._stopped.is_set():
                progressed = False
                for stream in (self._mnemos_stream, self._hypnos_stream):
                    try:
                        entries = await self._bus.read(
                            stream,
                            last_id=self._peer_cursors.get(stream, "0"),
                            count=32,
                            block_ms=0,
                        )
                    except Exception:
                        continue
                    if entries:
                        progressed = True
                        self._peer_cursors[stream] = entries[-1][0]
                        for _, event in entries:
                            await self._handle_peer_event(stream, event)
                if not progressed:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _handle_peer_event(self, stream: str, event: Event) -> None:
        if stream == self._hypnos_stream:
            if event.type == "hypnos.sleep.started":
                self._window_active = True
                # Maintenance entered: run an in-memory training pass.
                await self._maybe_train()
            elif event.type == "hypnos.sleep.completed":
                self._window_active = False
        elif stream == self._mnemos_stream and event.type == "mnemos.replay":
            await self._handle_replay_cue(event)

    async def _handle_replay_cue(self, event: Event) -> None:
        """On a mnemos.replay cue during an open window, generate a scenario.

        Offline-only: replay cues received while awake are ignored (the live
        loop never produces scenarios — paper §3.3.5 phase 3).
        """
        if not self._window_active:
            return
        await self.generate_scenario(seed_memory_id=str(event.payload.get("memory_id", "")))

    async def generate_scenario(self, *, seed_memory_id: str = "") -> list[dict[str, Any]]:
        """Roll out imagined trajectories and publish phantasia.scenario events.

        Seeds the world model from the accumulated waking trajectory (the most
        recent observations) and imagines ``rollout_horizon`` steps forward.
        The published events land on ``phantasia.out`` and are thereby
        re-injected into the workspace broadcast for downstream consolidation.

        Returns the list of published scenario payloads (for tests / callers).
        """
        # Seed the recurrent state from the recent trajectory so the imagined
        # rollout is grounded in lived experience rather than the zero state.
        self._wm.reset_state()
        for obs in list(self._buffer)[-self._rollout_horizon:]:
            self._wm.observe(obs)

        rollout = self._wm.imagine(self._rollout_horizon)
        if not rollout:
            return []

        # Summarise the imagined trajectory into compact numeric descriptors —
        # NOT raw sense data: per-step activation magnitude + overall drift.
        step_magnitudes = [
            round(sum(abs(v) for v in step) / max(1, len(step)), 6)
            for step in rollout
        ]
        drift = round(
            sum(
                abs(a - b)
                for a, b in zip(rollout[0], rollout[-1])
            )
            / max(1, len(rollout[0])),
            6,
        ) if len(rollout) > 1 else 0.0
        peak = max(step_magnitudes) if step_magnitudes else 0.0
        salience = self._baseline_salience + min(1.0, peak) * (
            self._alert_salience - self._baseline_salience
        )

        payload: dict[str, Any] = {
            "seed_memory_id": seed_memory_id,
            "horizon": len(rollout),
            "step_magnitudes": step_magnitudes,
            "trajectory_drift": drift,
            "encoder_version": ENCODER_VERSION,
            # Discloses which world-model backend generated this scenario.
            # "fake" = non-learning EMA stub (no learned dynamics);
            # "dreamerv3" = real RSSM with trained recurrent latents.
            "backend": self._backend,
        }
        await self.publish(
            "phantasia.scenario",
            payload,
            salience=max(0.0, min(1.0, salience)),
        )
        return [payload]

    # ------------------------------------------------------------------
    # Training (in-memory only; gated; NaN-guarded by the world model)
    # ------------------------------------------------------------------

    async def _maybe_train(self) -> Optional[TrainOutcome]:
        if not self._training_enabled:
            return None
        outcome = self.train_now()
        # Persist only after a real, successful pass — an aborted pass leaves
        # the previous checkpoint untouched (last-known-good).
        if outcome.steps > 0 and not outcome.aborted:
            self._save_weights(reason="post-train")
        return outcome

    def train_now(self) -> TrainOutcome:
        """Run one in-memory training pass over the accumulated buffer.

        IN-MEMORY ONLY: the buffer never touches disk and the world model's
        ``train`` writes nothing. A non-finite loss aborts without corrupting
        in-memory state (handled inside the world model). Synchronous and
        side-effect-free w.r.t. the filesystem so callers/tests can invoke it
        directly.
        """
        if not self._buffer:
            return TrainOutcome(loss=0.0, steps=0)
        trajectory = list(self._buffer)
        return self._wm.train(trajectory)

    # ------------------------------------------------------------------
    # Fork/merge — metadata only (NEVER the buffer or raw weights)
    # ------------------------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        """Snapshot world-model *metadata* only.

        The trajectory buffer and the in-memory weights are deliberately NOT
        serialized (zero-persistence). We emit the checkpoint path (if the
        operator pointed at one) and the encoder version so a restore can
        detect schema drift.
        """
        return {
            "backend": self._backend,
            "checkpoint_path": self._checkpoint_path,
            "persist_weights": self._persist_weights,
            "encoder_version": ENCODER_VERSION,
            "obs_dim": self._obs_dim,
            "training_enabled": self._training_enabled,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        """Restore checkpoint metadata. The buffer is never part of any
        snapshot. When weight persistence is configured, the CONFIGURED
        checkpoint path wins — a restored instance must not adopt another
        lineage's path (or lose its own to a stale snapshot)."""
        if not self._persist_weights:
            self._checkpoint_path = state.get("checkpoint_path") or None

    # ------------------------------------------------------------------
    # Preservation capture / revive (world-model weights into the bundle)
    # ------------------------------------------------------------------

    def export_preservation_weights(self) -> dict[str, Any]:
        """Force a checkpoint save and report whether weights were captured.

        When weight persistence is on (a learning backend, ``persist_weights``),
        the live learned weights are flushed to the checkpoint file so the
        preservation bundle (which copies ``state/phantasia/``) carries them.
        Returns an HONEST record:

        * ``{"captured": True, "checkpoint_path": ...}`` when weights were saved.
        * ``{"captured": False, "reason": ...}`` when there is nothing learned to
          capture (fake backend / persistence off). This is recorded truthfully
          rather than pretending the world model was preserved.

        FAILS LOUDLY (raises) if persistence is enabled but the checkpoint save
        fails — a preservation that claims to capture weights but did not would
        be a partial bundle that looks complete.
        """
        if not (self._persist_weights and self._checkpoint_path):
            return {
                "captured": False,
                "reason": (
                    "persist_weights is off / non-learning backend "
                    f"({self._backend!r}); world-model weights are NOT part of "
                    "this preservation (nothing learned to capture)"
                ),
                "backend": self._backend,
            }
        if not self._save_weights(reason="preserve"):
            raise RuntimeError(
                "phantasia: persist_weights is enabled but the world-model "
                f"checkpoint save to {self._checkpoint_path!r} FAILED during "
                "preservation — refusing to write a bundle that omits the "
                "learned world model while claiming completeness"
            )
        return {
            "captured": True,
            "checkpoint_path": self._checkpoint_path,
            "backend": self._backend,
            "encoder_version": ENCODER_VERSION,
        }

    def import_preservation_weights(self, blob: bytes) -> None:
        """Install learned world-model weights from a preservation bundle.

        Used by revive to restore the captured world model into THIS live
        instance (and persist it to the configured checkpoint so a later boot
        reloads the revived weights). Fails closed on an incompatible
        checkpoint — never silently discards or produces a mismatched model.
        """
        if not (
            hasattr(self._wm, "import_params") and hasattr(self._wm, "export_params")
        ):
            raise RuntimeError(
                "phantasia: revive carries world-model weights but the running "
                f"backend {self._backend!r} has no learned parameters to load "
                "them into — refusing to produce a mismatched individual"
            )
        # Fail-closed import (raises CheckpointMismatchError on any drift).
        self._wm.import_params(blob, extra={"encoder_version": ENCODER_VERSION})
        # Persist the revived weights to the configured checkpoint so a
        # subsequent boot reloads them rather than the fresh init.
        if self._persist_weights and self._checkpoint_path:
            self._save_weights(reason="revive")
