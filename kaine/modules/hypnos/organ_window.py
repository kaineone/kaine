# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""On-device voice-alignment GPU window: unload the organ → train → reload.

The Stage-2 sleep-cycle voice-alignment trainer (bf16 LoRA / DPO) and the
resident language organ both want the single usable GPU, and a 4B training step
plus the served organ do not fit at once. So during sleep — when the entity is
not expected to speak — this brackets the trainer call:

    quiesce consumers → unload organ → train → gpu-preflight → reload → resume

Every step is REAL (no pretend swap): the unload actually stops the served
``llama-server`` (reusing :mod:`kaine.setup.model_server` — the same lifecycle
the bootstrap owns), the gpu-preflight (:mod:`kaine.cycle.preflight`) really runs
before the reload, and the reload actually starts the server (with the accepted
adapter applied via ``--lora`` when training produced one). A failure at ANY step
reloads the *pre-training* organ so the entity is never left voiceless on wake
("a failed training window leaves a working organ").

On a multi-GPU host with a second device that has room to both serve and train,
the bracket is unnecessary (serve on one device, train on the other) and is
SKIPPED — the bracket is a single-GPU accommodation, not a universal requirement.

The window publishes its state through a small boundary-neutral STATE FILE
(``state/hypnos/organ_window.json``) that organ-dependent consumers (Lingua's
chat client, the A/B-divergence eval arm) read to learn the organ is "resting"
and degrade gracefully — deferred/skipped, not crashed. This mirrors the written-
record seam Hypnos already uses for the consolidation-divergence metric, so no
consumer needs to import Hypnos.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

# Boundary-neutral window-state seam (depends on neither core-runtime nor the
# evaluation sidecar) so Lingua + the A/B eval arm read the same signal without
# importing Hypnos. Re-exported here for the bracket's own use.
from kaine.organ_window_state import (
    ORGAN_WINDOW_STATE,
    PHASE_IDLE,
    PHASE_RELOADING,
    PHASE_RESTING,
    PHASE_TRAINING,
    organ_unloaded,
    read_window_state,
    write_window_state,
)

log = logging.getLogger(__name__)

__all__ = [
    "ORGAN_WINDOW_STATE",
    "PHASE_IDLE",
    "PHASE_RESTING",
    "PHASE_TRAINING",
    "PHASE_RELOADING",
    "MULTI_GPU_CONCURRENT_HEADROOM_GB",
    "organ_unloaded",
    "read_window_state",
    "write_window_state",
    "second_gpu_has_room",
    "OrganServerController",
    "OrganWindowResult",
    "run_with_organ_window",
]

#: A served-organ + 4B bf16-LoRA training step need ~3 GB + ~9.8 GB resident. A
#: second device must clear this to serve AND train concurrently (skip bracket).
MULTI_GPU_CONCURRENT_HEADROOM_GB = 13.0


@dataclass(frozen=True)
class OrganWindowResult:
    """Outcome of a bracketed training window."""

    bracketed: bool  # True iff the unload/reload bracket was actually run
    organ_restored: bool  # True iff the organ is confirmed serving at exit
    skipped_reason: Optional[str] = None  # set when bracketed is False
    error: Optional[str] = None  # set on a bracket-step failure (organ still restored)


# --------------------------------------------------------------------------
# Multi-GPU detection
# --------------------------------------------------------------------------


def second_gpu_has_room(
    *,
    serve_device: str,
    headroom_gb: float = MULTI_GPU_CONCURRENT_HEADROOM_GB,
    host_describer: Optional[Callable[[], dict[str, Any]]] = None,
) -> bool:
    """True iff a GPU OTHER than the serve device has room to serve + train.

    Reuses :func:`kaine.hardware.describe_host` (injectable for tests). The
    bracket is a single-GPU accommodation; when a second CUDA device reports at
    least ``headroom_gb`` free VRAM the trainer can run on it while the organ
    keeps serving on ``serve_device``, so the unload bracket is skipped. Any
    error → False (fall back to the safe single-GPU bracket).
    """
    try:
        describe = host_describer or _default_host_describer
        host = describe() or {}
        devices = list(host.get("cuda_devices") or [])
    except Exception:
        log.debug("organ window: host describe failed; assuming single GPU", exc_info=True)
        return False
    serve = (serve_device or "").strip().lower()
    for dev in devices:
        device_id = str(dev.get("device", "")).strip().lower()
        if device_id == serve:
            continue  # the serve device is busy holding the organ
        try:
            free = float(dev.get("free_vram_gb", 0.0))
        except (TypeError, ValueError):
            free = 0.0
        if free >= headroom_gb:
            return True
    return False


def _default_host_describer() -> dict[str, Any]:
    from kaine.hardware import describe_host

    return describe_host()


# --------------------------------------------------------------------------
# The bracket
# --------------------------------------------------------------------------


class OrganServerController:
    """Real unload/reload of the served organ, reusing the model-server lifecycle.

    Thin adapter over :mod:`kaine.setup.model_server` (``cmd_stop`` /
    ``cmd_start``) so the bracket does not invent a parallel mechanism. The
    reload applies an accepted adapter via the server's ``--lora`` flag (a real
    serving flag) by exporting it as an env override the launch-cmd builder
    honors; when no adapter was accepted the organ reloads unchanged.

    ``stop``/``start``/``preflight``/``probe`` are injectable so the bracket is
    unit-testable without standing up a real GPU server.
    """

    def __init__(
        self,
        *,
        config: dict[str, Any],
        stop_fn: Optional[Callable[..., int]] = None,
        start_fn: Optional[Callable[..., int]] = None,
        preflight_fn: Optional[Callable[..., Any]] = None,
        probe_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._config = config
        self._stop_fn = stop_fn
        self._start_fn = start_fn
        self._preflight_fn = preflight_fn
        self._probe_fn = probe_fn

    # -- real backends (lazy imports keep this module import-light) ----------
    def _stop(self) -> int:
        if self._stop_fn is not None:
            return int(self._stop_fn(self._config))
        from kaine.setup.model_server import cmd_stop

        return int(cmd_stop(self._config, out=lambda s: log.info("model-server stop: %s", s.rstrip())))

    def _start(self, *, adapter_path: Optional[Path]) -> int:
        if self._start_fn is not None:
            return int(self._start_fn(self._config, adapter_path=adapter_path))
        import os

        from kaine.setup.model_server import LORA_ADAPTER_ENV, cmd_start

        # Apply the accepted adapter via the server's --lora flag (real serving
        # flag) by exporting the env override the launch-cmd builder honors;
        # clear it when reloading unchanged so a prior adapter never lingers.
        prev = os.environ.get(LORA_ADAPTER_ENV)
        try:
            if adapter_path is not None:
                os.environ[LORA_ADAPTER_ENV] = str(adapter_path)
            else:
                os.environ.pop(LORA_ADAPTER_ENV, None)
            return int(
                cmd_start(
                    self._config,
                    out=lambda s: log.info("model-server start: %s", s.rstrip()),
                )
            )
        finally:
            if prev is None:
                os.environ.pop(LORA_ADAPTER_ENV, None)
            else:
                os.environ[LORA_ADAPTER_ENV] = prev

    def _preflight_ok(self) -> bool:
        """Run gpu-preflight before reload; True iff there is headroom.

        The cooperative preflight (report-only, never kills a foreign process)
        lives in ``kaine.cycle.preflight`` — a cycle-RUNTIME module a domain
        organ may NOT import (the modules→cycle boundary). So it is INJECTED as
        ``preflight_fn`` by the cycle entrypoint that wires Hypnos; when absent
        (e.g. a unit test or a host where preflight is off) we proceed. A short
        device → reported by the injected preflight (it writes the Nexus
        snapshot) and we return False so the caller does not thrash; the organ
        reload is still attempted (a working organ on wake is welfare-critical),
        but the operator has been told the device is tight.
        """
        if self._preflight_fn is None:
            return True
        try:
            return bool(self._preflight_fn(self._config))
        except Exception:
            log.warning("organ window: injected preflight raised", exc_info=True)
            return False

    def _organ_answers(self) -> bool:
        """Confirm the reloaded organ lists its alias (a real /v1/models probe)."""
        if self._probe_fn is not None:
            try:
                return bool(self._probe_fn())
            except Exception:
                return False
        try:
            from kaine.setup.model_server import cmd_status

            return cmd_status(self._config, out=lambda s: None) == 0
        except Exception:
            log.debug("organ window: status probe raised", exc_info=True)
            return False

    # -- public bracket steps ------------------------------------------------
    def unload(self) -> bool:
        """Stop the served organ; True iff stop succeeded."""
        rc = self._stop()
        return rc == 0

    def reload(self, *, adapter_path: Optional[Path]) -> bool:
        """Preflight then start the organ with the adapter; confirm it answers."""
        self._preflight_ok()  # report-only; never blocks the reload
        rc = self._start(adapter_path=adapter_path)
        if rc != 0:
            return False
        return self._organ_answers()


async def run_with_organ_window(
    *,
    train: Callable[[], Any],
    config: dict[str, Any],
    serve_device: str,
    hot_swap_mode: str,
    controller: Optional[OrganServerController] = None,
    host_describer: Optional[Callable[[], dict[str, Any]]] = None,
    state_path: Path = ORGAN_WINDOW_STATE,
) -> tuple[Any, OrganWindowResult]:
    """Run ``train`` inside the on-device GPU window and return its result.

    ``train`` is the awaitable producing a
    :class:`~kaine.modules.hypnos.voice_alignment.TrainingResult` (Hypnos passes
    a thunk around ``self._trainer.train(pairs, config)``). The bracket:

    1. SKIPS entirely when a second GPU has room to serve + train concurrently,
       or when ``hot_swap_mode == "manual"`` (the operator owns the reload, so
       the system must NOT stop the server out from under them) — train runs
       with the organ still resident.
    2. Otherwise: mark RESTING + unload organ → mark TRAINING + run train →
       mark RELOADING + reload organ (with the accepted adapter if any) → mark
       IDLE.

    Failure handling is welfare-critical: the reload runs in a ``finally`` so a
    training crash/timeout still restores a working organ before wake. If the
    organ does not answer after reload, that is surfaced (error) but the cycle
    continues — the caller logs and completes the remaining sleep phases.
    """
    # Multi-GPU: serve on one device, train on the other → no unload needed.
    if second_gpu_has_room(serve_device=serve_device, host_describer=host_describer):
        result = await train()
        return result, OrganWindowResult(
            bracketed=False,
            organ_restored=True,
            skipped_reason="multi-GPU host: second device serves the train step",
        )

    # Manual mode: the operator performs the reload, so the system must not stop
    # the server out from under them. Train with the organ resident (single-GPU
    # manual is the operator's explicit call; the marker path still applies).
    if (hot_swap_mode or "manual").strip() == "manual":
        result = await train()
        return result, OrganWindowResult(
            bracketed=False,
            organ_restored=True,
            skipped_reason="hot_swap_mode=manual: operator owns the reload bracket",
        )

    ctrl = controller or OrganServerController(config=config)

    result: Any = None
    train_error: Optional[str] = None
    adapter_path: Optional[Path] = None

    write_window_state(PHASE_RESTING, detail="unloading organ for training", path=state_path)
    unloaded = ctrl.unload()
    if not unloaded:
        log.warning("organ window: organ unload reported failure; proceeding cautiously")

    try:
        write_window_state(PHASE_TRAINING, detail="trainer running", path=state_path)
        result = await train()
        adapter_path = getattr(result, "adapter_path", None) if getattr(result, "accepted", False) else None
    except Exception as exc:
        train_error = f"{type(exc).__name__}: {exc}"
        log.exception("organ window: training raised; will reload the pre-training organ")
    finally:
        # Welfare-critical: ALWAYS reload a working organ before wake, whether
        # training succeeded, was vetoed, crashed, or timed out.
        write_window_state(
            PHASE_RELOADING,
            detail=("reloading with accepted adapter" if adapter_path else "reloading organ"),
            path=state_path,
        )
        try:
            restored = ctrl.reload(adapter_path=adapter_path)
        except Exception:
            log.exception("organ window: reload raised")
            restored = False
        if not restored and adapter_path is not None:
            # Adapter reload failed → roll back to the pre-training organ so the
            # entity is not left voiceless. The prior artifact is the base.
            log.warning(
                "organ window: reload with adapter failed; rolling back to pre-training organ"
            )
            try:
                restored = ctrl.reload(adapter_path=None)
            except Exception:
                log.exception("organ window: rollback reload raised")
                restored = False
        accepted = bool(getattr(result, "accepted", False)) if result is not None else None
        reason = getattr(result, "reason", None) if result is not None else None
        write_window_state(
            PHASE_IDLE,
            detail="organ restored" if restored else "organ reload FAILED — operator attention needed",
            last_adapter_accepted=accepted,
            last_adapter_reason=reason if accepted is not None else train_error,
            path=state_path,
        )

    error = train_error
    if not restored:
        error = (error + "; " if error else "") + "organ did not answer after reload"
    return result, OrganWindowResult(
        bracketed=True,
        organ_restored=bool(restored),
        error=error,
    )
