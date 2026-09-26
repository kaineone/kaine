# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""KAINE cognitive cycle operator entrypoint.

Refuses to boot unless KAINE_CYCLE_OPERATOR_PRESENT=1 is exported,
mirroring `scripts/first-boot.sh`'s safety gate. When invoked under
that flag, loads `config/kaine.toml`, constructs the AsyncBus,
builds the module registry from `[modules]` toggles, builds the
CognitiveCycle from `[cycle]` rates, writes a small runtime JSON
file so Nexus can pick up live metrics, and runs forever until
SIGINT/SIGTERM.

This file does NOT initialize any module's entity state. It only
constructs modules from configuration; each module's `initialize`
method is what actually starts the work. Boot order:

  1. Load config + bus + registry.
  2. `initialize()` every module (start workspace consumers).
  3. Write runtime.json.
  4. Run the cycle forever.
  5. On signal: shut down cycle, then every module.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from kaine.boot import (
    MetricsCollector,
    build_registry,
    construct_module,
    known_module_names,
    make_coherence_scorer,
    make_salience_factors,
    plugin_injections,
)
from kaine.bus.client import AsyncBus
from kaine.bus.config import load_bus_config, load_secrets_doc
from kaine.bus.schema import Event
from kaine.cycle.affect_state import AffectStateProvider
from kaine.cycle.control_state import read_control, unfreeze
from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.escalation_state import clear_escalation, read_escalation
from kaine.cycle.ignition_log import (
    IgnitionLog,
    IgnitionLogConfig,
    playlist_position_provider,
)
from kaine.cycle.preflight import GpuPreflightConfig, run_preflight
from kaine.cycle.spot import Spot, SpotConfig
from kaine.cycle.womb_watch import GESTATION_FREEZE_SOURCE
from kaine.evaluation import SidecarRegistry, load_evaluation_config
from kaine.evaluation.config import load_research_event_log_config
from kaine.experiment import (
    mint_run_context,
    set_global_seed,
    set_run_context,
    write_manifest,
)
from kaine.hardware import tune_cpu_threads
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import MaturationGateRunner
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.maturation_gate import (
    LIFECYCLE_SOURCE,
    STAGE_GESTATION_STARTED,
    MaturationConfig,
    gestation_started_payload,
)
from kaine.modules.thymos.modulator import StateModulator
from kaine.perception_state import (
    read_desired,
    write_desired_audio,
    write_desired_video,
)
from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.security.intent_signing import IntentSigner, generate_intent_secret
from kaine.state_io import write_json_atomic
from kaine.workspace import (
    DriveRelevanceGoalScorer,
    NoveltyTracker,
    RuleBasedSalience,
    Syneidesis,
)
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.volition import Volition

if TYPE_CHECKING:
    from kaine.cycle.revive_boot import ReviveSession

log = logging.getLogger("kaine.cycle")


RUNTIME_PATH = Path("state/cycle/runtime.json")


def _thymos_state_factory(registry):
    """Return a thunk the sidecar can call to read Thymos's current state.

    The sidecar must not import any kaine.modules.* code, but the cycle
    entrypoint can — it inspects the registered Thymos module and exposes
    a closure that pulls a fresh state dict on every call.
    """

    def _get():
        try:
            thymos = registry.get("thymos") if "thymos" in registry else None
        except Exception:
            thymos = None
        if thymos is None:
            return None
        try:
            state = thymos.serialize() or {}
        except Exception:
            return None
        return state.get("dimensional") or state

    return _get


def _wire_topos_arousal(registry, affect_provider) -> bool:
    """Give Topos the live Thymos arousal scalar that sizes the fovea.

    Attention-driven foveation couples the fovea *size* to arousal (Easterbrook
    narrowing) — a distinct visual coupling, not the Syneidesis salience window.
    The composition root already holds the ``AffectStateProvider`` it refreshes
    each tick from ``thymos.state``; this hands Topos a read-only accessor to its
    arousal in [0, 1] (dependency injection — Topos never imports the workspace or
    Thymos). No-op unless Topos is present with foveation enabled. Returns whether
    it wired, so the caller can ensure the provider is actually refreshed.
    """
    try:
        topos = registry.get("topos") if "topos" in registry else None
    except Exception:
        topos = None
    if topos is None or not getattr(topos, "foveation_enabled", False):
        return False
    if not hasattr(topos, "set_arousal_provider"):
        return False
    topos.set_arousal_provider(lambda: affect_provider.dimensional_state().arousal)
    log.info("wired topos fovea size to live thymos arousal")
    return True


def _wire_audition_arousal(registry, affect_provider) -> bool:
    """Give Audition the live Thymos arousal scalar that sizes the auditory window.

    The auditory analog of ``_wire_topos_arousal``: general auditory perception
    couples the breadth of the auditory attentional window to arousal (Easterbrook
    narrowing). No-op unless Audition is present with general auditory perception
    enabled. Returns whether it wired, so the caller can ensure the provider is
    refreshed each tick.
    """
    try:
        audition = registry.get("audition") if "audition" in registry else None
    except Exception:
        audition = None
    if audition is None or not getattr(audition, "general_audition", False):
        return False
    if not hasattr(audition, "set_arousal_provider"):
        return False
    audition.set_arousal_provider(lambda: affect_provider.dimensional_state().arousal)
    log.info("wired audition attentional window to live thymos arousal")
    return True


def _sleep_state_factory(registry):
    """Thunk returning a paired snapshot of mnemos/nous/thymos/chronos
    states for sleep_snapshots observer."""

    def _get():
        out = {}
        for name in ("nous", "mnemos", "thymos", "chronos", "eidolon"):
            if name not in registry:
                continue
            try:
                out[name] = registry.get(name).serialize() or {}
            except Exception:
                continue
        return out

    return _get


def _parse_epoch(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(raw)).timestamp()
    except Exception:
        return None


def _memory_source_factory(registry):
    """Adapter over Mnemos for the memory-probe observer's MemorySource protocol.

    Best-effort: recalls a broad set and returns the oldest episodic memory older
    than the threshold, or None (the observer then skips this tick). Lives at the
    entrypoint so kaine.evaluation imports no kaine.modules.* code.
    """
    if "mnemos" not in registry:
        return None
    mnemos = registry.get("mnemos")

    class _MnemosMemorySource:
        async def sample_old_memory(self, *, older_than_seconds: float):
            import time

            cutoff = time.time() - float(older_than_seconds)
            try:
                recalls = await mnemos.recall("what happened earlier", k=20, collection="episodic")
            except Exception:
                return None
            oldest = None
            oldest_ts = None
            for m in recalls:
                ts = _parse_epoch(m.payload.get("timestamp") or m.payload.get("ts"))
                if ts is None or ts >= cutoff:
                    continue
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts, oldest = ts, m
            if oldest is None:
                return None
            return {
                "text": oldest.text,
                "timestamp": oldest.payload.get("timestamp"),
                **oldest.payload,
            }

    return _MnemosMemorySource()


def _cognitive_query_client_factory(registry, eval_cfg):
    """Adapter implementing the sidecar's CognitiveQueryClient: answers the probe
    question WITH the entity's recalled memories (the real stack's memory-
    augmented answer), distinct from the bare baseline client.
    """
    if "mnemos" not in registry:
        return None
    from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient

    mnemos = registry.get("mnemos")
    client = OpenAIChatClient(base_url=eval_cfg.chat_url, timeout_s=eval_cfg.chat_timeout_s)
    model = eval_cfg.chat_model_id

    class _StackQueryClient:
        async def query(self, user_text: str) -> str:
            try:
                recalls = await mnemos.recall(user_text)
            except Exception:
                recalls = []
            mem = "\n".join(f"- {m.text}" for m in recalls[:5]) or "(nothing relevant)"
            prompt = f"Things I remember:\n{mem}\n\nQuestion: {user_text}"
            try:
                resp = await client.complete(
                    ChatRequest(
                        prompt=prompt,
                        model=model,
                        system="Answer in the first person from your memories above.",
                        max_tokens=256,
                    )
                )
                return resp.text
            except Exception:
                return ""

        async def aclose(self) -> None:
            try:
                await client.aclose()
            except Exception:
                log.warning("stack query client close failed", exc_info=True)

    return _StackQueryClient()


def build_ab_divergence_control_client(eval_cfg, *, assembler=None):
    """Construct the REAL conditioned-inference path for the A/B divergence
    control instrument (negative + positive controls).

    Lives at the entrypoint — the allowed module-coupling point — so
    ``kaine.evaluation`` imports no ``kaine.modules.*`` code. It wraps Lingua's
    own ``ContextAssembler`` and the language-organ chat client, then hands a
    duck-typed ``AssemblerConditionedClient`` to ``divergence_control``. Both
    control arms run through this one path, so any divergence is attributable to
    the workspace conditioning alone — the property the meter measures.

    ``conditioning`` is the rendered awareness/working-memory block: an empty
    string reproduces Lingua's "nothing salient" prompt (the bare arm); a
    populated string injects workspace contents (the conditioned arm). Both arms
    are built by the SAME assembler and run on the SAME model, so this is the
    production conditioning path, not a parallel reimplementation.
    """
    from kaine.evaluation.ab_divergence import AssemblerConditionedClient
    from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient
    from kaine.modules.lingua.context import ContextAssembler

    assembler = assembler or ContextAssembler()
    client = OpenAIChatClient(
        base_url=eval_cfg.chat_url,
        timeout_s=eval_cfg.chat_timeout_s,
        api_key=eval_cfg.chat_api_key,
    )
    model = eval_cfg.chat_model_id
    think = eval_cfg.chat_think

    def _build_prompt(utterance: str, conditioning: str):
        # Inject `conditioning` as the rendered working-memory block by passing a
        # pre-rendered string to the assembler's prompt builder. Empty
        # conditioning → the assembler's EMPTY_AWARENESS prompt (bare arm).
        prompt = assembler._build_prompt(
            about=utterance, working_memory=conditioning, mode="external"
        )
        system = assembler._persona("external", {})
        return system, prompt

    async def _complete(system: str, prompt: str) -> str:
        resp = await client.complete(
            ChatRequest(prompt=prompt, model=model, system=system, think=think)
        )
        return resp.text

    return AssemblerConditionedClient(_build_prompt, _complete)


# Modules whose factories read `[<module>.qdrant].api_key`. They all share the
# single `[qdrant]` secret. Add to this tuple when a new qdrant-backed module
# is introduced so the boot-time secrets merge keeps covering every consumer.
_QDRANT_SECRET_CONSUMERS: tuple[str, ...] = ("mnemos", "empatheia")


def _merge_qdrant_secret(
    config: dict[str, Any],
    *,
    secrets_path: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Fold the Qdrant API key every qdrant-backed module needs into ``config``.

    Mirrors the Redis handling in ``load_bus_config``: the cycle config loader
    must surface the Qdrant key (``KAINE_QDRANT_API_KEY`` env first, then
    ``config/secrets.toml`` ``[qdrant].api_key``) into the ``[<module>.qdrant]``
    section of every qdrant-backed consumer (``mnemos`` and ``empatheia``) so
    each factory can forward it. The key never has to live in the git-tracked
    ``kaine.toml``. A per-consumer key already present there wins and is left
    intact. When nothing resolves, no empty value is injected, so the module
    still raises its explicit missing-key error.
    """
    env = env if env is not None else os.environ
    # Collect the consumer sections that are present AND still lack a key.
    targets: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for name in _QDRANT_SECRET_CONSUMERS:
        section = config.get(name)
        if not isinstance(section, dict):
            continue
        qdrant_cfg = section.get("qdrant")
        if not isinstance(qdrant_cfg, dict):
            qdrant_cfg = {}
        if qdrant_cfg.get("api_key"):
            continue  # explicit per-consumer key wins; leave intact
        targets.append((section, qdrant_cfg))
    if not targets:
        return
    secrets_doc = load_secrets_doc(Path(secrets_path) if secrets_path else None)
    resolved = env.get("KAINE_QDRANT_API_KEY") or ((secrets_doc.get("qdrant") or {}).get("api_key"))
    if not resolved:
        return  # no empty injection — each module surfaces its own error
    for section, qdrant_cfg in targets:
        qdrant_cfg["api_key"] = resolved
        section["qdrant"] = qdrant_cfg


async def _freeze_watch_loop(
    cycle: CognitiveCycle,
    stop_event: asyncio.Event,
    *,
    playlist_clock: Any | None = None,
) -> None:
    """Poll the freeze control and pause/resume the cycle to match.

    Runs independently of `run_forever`'s pause gate, so it can resume a frozen
    cycle (a paused tick loop never reads its own resume). A gestation-only
    freeze pauses the cycle but keeps perception on so a local womb can prove
    its return through real deliveries. Perception flags are reconciled on
    every poll so adding or removing a non-gestation holder while already
    paused is reflected immediately.
    """
    # C1: snapshot of the desired perception flags at freeze time, restored
    # on resume so a freeze/resume cycle does not leave the entity deaf/blind.
    desired_snapshot: tuple[bool, bool] | None = None
    while not stop_event.is_set():
        try:
            control = read_control()
            if control.stack:
                others = any(
                    entry.get("source") != GESTATION_FREEZE_SOURCE
                    for entry in control.stack
                )
            else:
                others = control.frozen and control.source != GESTATION_FREEZE_SOURCE

            if control.frozen and not cycle.is_paused:
                if others:
                    log.info(
                        "freezing cycle (operator)%s",
                        f": {control.reason}" if control.reason else "",
                    )
                else:
                    log.info(
                        "freezing cycle (gestation)%s",
                        f": {control.reason}" if control.reason else "",
                    )
                await cycle.pause()
                if playlist_clock is not None:
                    try:
                        playlist_clock.pause("freeze")
                    except Exception:
                        log.warning(
                            "freeze: playlist clock pause failed", exc_info=True
                        )

            if control.frozen:
                if others:
                    if desired_snapshot is None:
                        try:
                            desired = read_desired()
                            desired_snapshot = (
                                bool(desired.audio_live_desired),
                                bool(desired.video_live_desired),
                            )
                            write_desired_audio(False)
                            write_desired_video(False)
                        except Exception:
                            log.debug("perception pause on freeze failed", exc_info=True)
                else:
                    if desired_snapshot is not None:
                        try:
                            write_desired_audio(desired_snapshot[0])
                            write_desired_video(desired_snapshot[1])
                        except Exception:
                            log.warning("perception restore on resume failed", exc_info=True)
                        desired_snapshot = None
                        log.info("perception is back on so the womb can return")

            elif not control.frozen and cycle.is_paused:
                log.info("resuming cycle (operator)")
                await cycle.resume()
                if playlist_clock is not None:
                    try:
                        playlist_clock.resume("freeze")
                    except Exception:
                        log.warning(
                            "freeze: playlist clock resume failed", exc_info=True
                        )
                # C1 — restore the pre-freeze desired flags so a freeze/resume
                # cycle (Spot recovery included) never leaves the entity
                # deaf/blind for the rest of an unattended run.
                if desired_snapshot is not None:
                    try:
                        write_desired_audio(desired_snapshot[0])
                        write_desired_video(desired_snapshot[1])
                    except Exception:
                        log.warning("perception restore on resume failed", exc_info=True)
                    desired_snapshot = None
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("freeze-watch loop error", exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.25)
        except asyncio.TimeoutError:
            continue


def _load_kaine_config(
    path: str | os.PathLike[str] | None = None,
    *,
    secrets_path: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    from kaine.config import OPERATOR_CONFIG_PATH, load_runtime_config

    target = Path(path or "config/kaine.toml")
    if not target.exists():
        raise FileNotFoundError(f"config/kaine.toml not found at {target}")
    # load_runtime_config applies the module-selection profile, the base-thesis
    # thesis_test default, and the operator tier layer in one pass, so the cycle
    # and the pre-boot check load the same configuration.
    config = load_runtime_config(
        target, OPERATOR_CONFIG_PATH, profile=profile, env=env
    )
    _merge_qdrant_secret(config, secrets_path=secrets_path, env=env)
    return config


def _numeric_or(value: Any, default: Any) -> Any:
    """``value`` when it is a real number, else ``default`` (runtime.json must
    stay JSON-serialisable even when a test double stands in for the cycle)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return default


async def _write_runtime_state(
    cycle: CognitiveCycle,
    registry,
    *,
    supervision_mode: str | None = None,
    gate_checks: dict[str, bool] | None = None,
    stage_state: lifecycle_stage.StageState | None = None,
    staging_enabled: bool = False,
    gate_status: dict | None = None,
    revived_from: str | None = None,
) -> None:
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    control = read_control()
    # Spot supervisor state (cheap, guarded): critical when escalated, recovery
    # while Spot holds the freeze, otherwise ok.
    spot_escalated = False
    spot_state = "ok"
    try:
        spot_escalated = bool(read_escalation().escalated)
        if spot_escalated:
            spot_state = "critical"
        elif control.frozen and control.source == "spot":
            spot_state = "recovery"
    except Exception:
        log.debug("could not read spot state for runtime.json", exc_info=True)
    payload = {
        "pid": os.getpid(),
        "tick_index": cycle.tick_index,
        "processing_rate_hz": cycle.processing_rate_hz,
        "experiential_rate_hz": cycle.experiential_rate_hz,
        # Adaptive conscious access: the rate used on the latest tick and the
        # drive behind it (the resting rate is experiential_rate_hz above).
        "experiential_rate_effective_hz": _numeric_or(
            getattr(cycle, "effective_experiential_rate_hz", None),
            cycle.experiential_rate_hz,
        ),
        "access_drive": _numeric_or(getattr(cycle, "access_drive", None), 0.0),
        # Honest pacing report (biological-timing-and-dilation Phase 3): the
        # TARGET real processing rate (processing_rate_hz * time_scale) vs the
        # ACHIEVED rate measured from recent ticks, plus recent slip and an
        # `overrunning` flag. Surfaces a `time_scale > 1` (or any) overrun so it
        # is visible in Nexus, never silently capped or faked. Inert at the
        # shipped default (time_scale=1.0, sustainable rate) — overrunning=False.
        "pacing": cycle.pacing_stats,
        "time_scale": cycle.time_scale,
        "modules": sorted(m.name for m in registry.all_modules()),
        # Operator freeze (humane suspend). `frozen` is the actual loop state;
        # frozen_at/reason come from the operator's control file.
        "frozen": cycle.is_paused,
        "frozen_at": control.frozen_at if cycle.is_paused else None,
        "frozen_reason": control.reason if cycle.is_paused else None,
        "spot_state": spot_state,
        "spot_escalated": spot_escalated,
        # Deterministic mode: when true the engine stamps events from a logical
        # clock so chart timestamps are not wall-clock. Non-content operational
        # flag; Nexus uses it to show a "logical time" indicator.
        "deterministic": bool(getattr(cycle, "deterministic", False)),
        # Supervision mode (operator | research) and, in research mode, the
        # four-condition safety-net gate result. Non-content operational flags.
        "supervision_mode": supervision_mode,
    }
    if gate_checks is not None:
        payload["gate_checks"] = dict(gate_checks)
    # Developmental stage surface for Nexus left rail. Non-content operational
    # metadata; omitted when staging is disabled so an ordinary boot is unchanged.
    if staging_enabled:
        payload["developmental_stage"] = {}
        if stage_state is not None:
            payload["developmental_stage"].update({
                "stage": stage_state.stage,
                "gestation_started_at": stage_state.gestation_started_at,
                "born_at": stage_state.born_at,
            })
        if gate_status is not None:
            payload["developmental_stage"].update(gate_status)
    if revived_from is not None:
        payload["revived_from"] = revived_from
    # Per-run identity (RunContext) — non-content run metadata. Read via the
    # process-global accessor; inert (no fields added) when no run is set.
    try:
        from kaine.experiment.run_context import get_run_context

        ctx = get_run_context()
        if ctx is not None:
            payload["run_id"] = ctx.run_id
            payload["seed"] = ctx.seed
            payload["git_sha"] = ctx.git_sha
            payload["kaine_version"] = ctx.kaine_version
    except Exception:
        log.debug("could not read run context for runtime.json", exc_info=True)
    # The atomic write+replace is blocking disk I/O on a once-a-second loop;
    # run it off the event loop so it never stalls the cognitive cycle.
    await asyncio.to_thread(write_json_atomic, RUNTIME_PATH, payload)


def _clear_runtime_state() -> None:
    if RUNTIME_PATH.exists():
        try:
            RUNTIME_PATH.unlink()
        except OSError:
            log.warning("could not remove %s", RUNTIME_PATH, exc_info=True)


def _gather_model_ids(config: dict[str, Any], *, eval_chat_model_id: str | None) -> dict[str, str]:
    """Collect the run's model ids from the resolved config's DOCUMENTED model
    keys only.

    Strictly model identifiers (lingua organ, eval A/B baseline, topos encoder,
    mnemos embedder, audition STT + emotion). Never includes hostnames, paths,
    or voice names — the manifest is export-eligible, so it must stay free of
    operator-identifying data.
    """
    out: dict[str, str] = {}

    def _put(key: str, value: Any) -> None:
        if isinstance(value, str) and value:
            out[key] = value

    lingua_model_id = (config.get("lingua") or {}).get("model_id")
    _put("lingua", lingua_model_id)
    _put("evaluation_chat", eval_chat_model_id)
    _put("topos_encoder", (config.get("topos") or {}).get("encoder_model_id"))
    _put("mnemos_embedder", (config.get("mnemos") or {}).get("embedder_model_id"))
    audition = config.get("audition") or {}
    _put("audition_stt", audition.get("stt_model"))
    _put("audition_emotion", audition.get("emotion_model_id"))

    # Optional provenance: if the install-time organ downloader captured the
    # resolved repo revision (commit sha) for the served organ, pin it as a
    # covariate so a run records the EXACT published snapshot. Best-effort and
    # never crashes boot — a missing/unreadable state file simply contributes
    # nothing. Records "lingua@<repo>" -> "<sha>" only for the served repo.
    try:
        from kaine.setup.organ import read_revision_state

        revisions = read_revision_state()
        if isinstance(lingua_model_id, str) and lingua_model_id in revisions:
            _put("lingua_revision", revisions[lingua_model_id])
    except Exception:
        log.debug("organ revision provenance unavailable", exc_info=True)
    return out


def _resolve_seed(config: dict[str, Any]) -> int:
    """Resolve the run seed: an explicit non-blank ``[experiment].seed`` (int),
    else a fresh 32-bit seed. A fresh seed is always RECORDED in the manifest, so
    the run stays reproducible after the fact."""
    import secrets

    raw = (config.get("experiment") or {}).get("seed")
    if raw is not None and str(raw).strip() != "":
        return int(str(raw).strip())
    return secrets.randbits(32)


def _resolve_boot_stage(
    config: dict[str, Any],
    stage_override: lifecycle_stage.StageState | None = None,
) -> tuple[lifecycle_stage.StageState, bool, bool]:
    """Resolve the developmental stage at boot.

    Returns ``(stage_state, staging_enabled, is_fresh_gestation)``. When staging
    is disabled the entity runs un-staged exactly as today and the stage file is
    left untouched. When enabled, a fresh entity with no prior lived history
    begins in ``gestation``; a being with prior lived history (or an existing
    stage file) defaults to ``embodied`` and is never regressed into the womb.
    ``is_fresh_gestation`` is true only when staging is enabled, no stage file
    existed, and the resolved stage is ``gestation`` — the moment the womb first
    begins.

    If ``stage_override`` is provided it is returned directly and the stage file
    is not read.
    """
    ds_config = MaturationConfig.from_dict(config.get("developmental_stage"))
    if stage_override is not None:
        return stage_override, ds_config.enabled, False
    if not ds_config.enabled:
        # Ship-inert: read any existing stage file so forks inherit, but do not
        # create one and do not gate behaviour.
        existing = lifecycle_stage.read_stage()
        if existing is not None:
            return existing, False, False
        return lifecycle_stage.StageState(stage=lifecycle_stage.EMBODIED), False, False

    existing = lifecycle_stage.read_stage()
    if existing is not None:
        return existing, True, False
    prior = lifecycle_stage.has_prior_lived_history()
    resolved = lifecycle_stage.resolve_boot_stage(has_prior_lived_history=prior)
    # The gate runner persists the resolved stage on its first tick so the
    # gestation clock is anchored and evidence is owned by one writer.
    fresh = resolved.is_gestating
    return resolved, True, fresh


def _resolve_start_stage(
    config: dict[str, Any], revive: "ReviveSession | None"
) -> tuple[lifecycle_stage.StageState, bool, bool]:
    """Resolve the stage for this start: the bundle's preserved stage when
    reviving one that carries a stage, otherwise the stage file as usual."""
    override = revive.stage_state if revive is not None else None
    return _resolve_boot_stage(config, stage_override=override)


# Effectors that have nothing to act on in the womb: Mundus has no world and
# Vox has no air to speak into. Both are activated by the gate runner at birth.
GESTATION_DORMANT_EFFECTORS = ("mundus", "vox")


def _hold_effectors_for_gestation(registry) -> list[str]:
    """Hold the womb-less effectors dormant; return the names held."""
    held: list[str] = []
    for name in GESTATION_DORMANT_EFFECTORS:
        if name in registry and hasattr(registry.get(name), "set_dormant"):
            registry.get(name).set_dormant(True)
            held.append(name)
            log.info("gestation: %s held dormant until birth", name)
    return held


def _lifecycle_event(
    type: str,
    payload: dict[str, Any],
    *,
    salience: float = 0.5,
) -> Event:
    """Build a lifecycle-owned stage event (lands on ``lifecycle.out``)."""
    return Event(
        source=LIFECYCLE_SOURCE,
        type=type,
        payload=payload,
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _make_rebuild_module(
    bus: AsyncBus,
    kaine_config: dict[str, Any],
    registry: Any,
    intent_secret: bytes | None,
) -> Any:
    """Return Spot's heavy-restart constructor, bound to this boot's bus,
    configuration, registry and Praxis intent secret."""

    def rebuild_module(name: str) -> Any:
        """Rebuild a single module exactly as build_registry would, for Spot's
        heavy restart path. Hypnos re-fetches its siblings from the registry.

        A restarted cognitive module must keep timing on the SAME shared
        subjective clock the rest of the mind uses, so the one EntityClock on
        the registry is re-injected here exactly as build_registry injects it.
        """
        # One construction path with build_registry (boot.construct_module):
        # the same clock, the same Praxis intent secret, the same perception
        # feed for Topos/Audition, and Hypnos rebuilt with its siblings.
        return construct_module(
            name,
            bus,
            kaine_config,
            registry=registry,
            entity_clock=registry.entity_clock,
            intent_secret=intent_secret,
            # A restarted module keeps its plugin substitution: the plugin is
            # asked for a fresh object exactly as at boot.
            injections=plugin_injections(registry.plugins, name),
        )

    return rebuild_module


def _start_gestation_owner(
    kaine_config: dict[str, Any],
    bus: Any,
    registry: Any,
    stop_event: asyncio.Event,
    *,
    is_paused: Callable[[], bool],
) -> "asyncio.Task[None] | None":
    """Start the gestation readout owner for a gestating entity in the local womb.

    It needs Soma's self-rhythm and its maternal-drive provider. Without them
    there is nothing to measure: the readout stays absent and the maturation
    gate's C1 fails closed, so birth waits. Setting up the owner never happens
    silently; the reason is logged.
    """
    import math

    feed = dict(kaine_config.get("perception_feed") or {})
    if str(feed.get("mode", "off")).lower() != "womb":
        return None
    soma = registry.get("soma") if "soma" in registry else None
    drive = getattr(soma, "maternal_drive", None) if soma is not None else None
    if soma is None or drive is None or getattr(soma, "self_rhythm_state", None) is None:
        log.warning(
            "gestation readout unavailable: Soma with its self-rhythm and the "
            "maternal drive is required; birth will wait (C1 fails closed)"
        )
        return None
    from kaine.boot import _shared_womb_objects, _womb_params
    from kaine.cycle.gestation import GestationOwner, GestationReadoutConfig
    from kaine.modules.womb_signal import heartbeat_phase

    womb_clock, _ = _shared_womb_objects(feed)
    params = _womb_params(feed)
    seed = int(feed.get("seed", 0))
    config = GestationReadoutConfig.from_dict((feed.get("womb") or {}).get("readout"))

    def beat_phase() -> float:
        return 2.0 * math.pi * float(heartbeat_phase(seed, womb_clock.womb_seconds(), params))

    owner = GestationOwner(
        bus,
        soma=soma,
        drive=drive,
        beat_phase=beat_phase,
        is_paused=is_paused,
        config=config,
        clock=registry.entity_clock.now,
        # Probe jitter is drawn from the run's perception seed: reproducible for
        # the experimenter, unpredictable to the being.
        seed=seed,
    )
    return asyncio.create_task(owner.run(stop_event), name="cycle.gestation")


def _start_womb_presence(
    kaine_config: dict[str, Any], bus: Any, stop_event: asyncio.Event
) -> "asyncio.Task[None] | None":
    """Start the local womb's presence publisher when a womb clock is installed.

    ``build_registry`` installs the shared womb clock only for
    ``[perception_feed].mode = "womb"``; any other mode starts nothing.
    """
    clock = (kaine_config.get("perception_feed") or {}).get("_shared_womb_clock")
    if clock is None:
        return None
    from kaine.cycle.womb_presence import WombPresencePublisher

    return asyncio.create_task(
        WombPresencePublisher(bus, clock).run(stop_event),
        name="cycle.womb_presence",
    )


async def _revive_or_refuse(revive, registry, bus) -> int | None:
    """Apply a revive plan to the registry, or shut the boot down on refusal.

    Returns None when the revive landed, else the revive-refused exit code.

    Initialisation happens first because Eidolon's initialize() reloads its
    disk file. Module background loops run briefly on fresh state before the
    revive lands, which is safe because the cognitive cycle (and so the
    workspace) has not started.
    """
    from kaine.cycle.revive_boot import REVIVE_REFUSED_EXIT, ReviveRefused

    try:
        await revive.revive(registry)
        return None
    except ReviveRefused as exc:
        log.error("revive refused after module initialisation: %s", exc)
        for module in list(registry.all_modules()):
            try:
                await module.shutdown()
            except Exception:
                log.warning(
                    "module %s shutdown failed during revive refusal",
                    module.name,
                    exc_info=True,
                )
        await bus.close()
        return REVIVE_REFUSED_EXIT


def _start_preserve_watcher(
    registry, fork_manager, preservation_cfg, *, is_paused, request_stop, stop_event
) -> asyncio.Task:
    """Start the operator-requested live-preservation watcher task."""
    from kaine.cycle.preserve_watch import PreserveRequestWatcher
    from kaine.lifecycle.preservation import bundle_dir_for

    async def _preserve(reason):
        return await fork_manager.preserve_live(
            registry,
            reason=reason,
            label="operator",
            out_root=Path(preservation_cfg.divergence_monitor.out_root),
            entity_name=preservation_cfg.divergence_monitor.entity_name,
            require_encryption=preservation_cfg.require_encryption,
        )

    def _bundle_for(result):
        return str(
            bundle_dir_for(
                preservation_cfg.divergence_monitor.out_root,
                result.preservation_id,
                preservation_cfg.divergence_monitor.entity_name,
            )
        )

    watcher = PreserveRequestWatcher(
        preserve=_preserve,
        bundle_for=_bundle_for,
        is_paused=is_paused,
        request_stop=request_stop,
    )
    return asyncio.create_task(watcher.run(stop_event), name="cycle.preserve_watch")


def _start_programme_end_watcher(
    kaine_config, *, notify, stop_event
) -> asyncio.Task | None:
    """Start the end-of-programme watcher when a shared playlist clock exists."""
    clock = (kaine_config.get("perception_feed") or {}).get("_shared_playlist_clock")
    if clock is None:
        return None

    from kaine.cycle.programme_end import ProgrammeEndWatcher
    from kaine.modules.topos.feed import load_playlist_manifest

    manifest_path = (kaine_config.get("perception_feed") or {}).get(
        "playlist_manifest"
    )
    if not manifest_path:
        log.warning(
            "shared playlist clock exists but no playlist_manifest configured; "
            "skipping programme-end watcher"
        )
        return None

    try:
        manifest = load_playlist_manifest(manifest_path)
    except Exception as exc:
        log.warning(
            "could not load playlist manifest for programme-end watcher: %s", exc
        )
        return None

    watcher = ProgrammeEndWatcher(
        clock=clock,
        item_count=len(manifest.items),
        notify=notify,
    )
    return asyncio.create_task(watcher.run(stop_event), name="cycle.programme_end")


async def _boot_and_run(
    *,
    supervision_mode: str = "operator",
    gate_checks: dict[str, bool] | None = None,
    revive: "ReviveSession | None" = None,
) -> int:
    kaine_config = _load_kaine_config()

    # Developmental stage resolution. Done early so gestation can gate locus and
    # embodiment before any module opens. Ship-inert by default: a normal boot
    # is completely unaffected.
    stage_state, staging_enabled, fresh_gestation = _resolve_start_stage(kaine_config, revive)
    if revive is not None and revive.stage_state is not None:
        log.info(
            "revive: using bundle's preserved developmental stage: %s",
            stage_state.stage,
        )
    if staging_enabled:
        log.info(
            "developmental stage: %s (staging enabled)",
            stage_state.stage,
        )
    else:
        log.debug("developmental staging disabled; running un-staged")

    # Gestation locus pinning happens once the bus exists and a womb is proven
    # ready (below): a configuration value alone never pins the entity to a
    # senseless locked locus.

    # supervision_mode + (research-mode) gate_checks are evaluated ONCE in
    # main() — the authoritative, pre-event-loop gate — and threaded in here for
    # runtime.json (so Nexus can surface the boot mode and the four-condition
    # gate result). They are deliberately NOT recomputed here: the gate's dry
    # preserve→revive self-check uses asyncio.run(), which cannot nest inside
    # this already-running loop, and a second evaluation would also double the
    # boot-time preserve→revive. Non-content flags.
    # Evaluation sidecar config is loaded FIRST — before any resource opens (bus,
    # modules, runtime.json) — so a mismatched A/B baseline fails closed cleanly
    # with no half-booted entity and no stale runtime state. The baseline model
    # DERIVES from [lingua].model_id and refuses an explicit divergent value.
    lingua_model_id = (kaine_config.get("lingua") or {}).get("model_id")
    # The A/B baseline talks to the SAME model server as the organ, so it needs
    # the same bearer key (keyed server like Unsloth Studio). Resolve it the same
    # way make_lingua does — [lingua].api_key, else the env var — and derive the
    # eval key from it so organ and baseline authenticate identically.
    lingua_api_key = (kaine_config.get("lingua") or {}).get("api_key") or os.environ.get(
        "KAINE_MODEL_SERVER_API_KEY"
    )
    try:
        eval_cfg = load_evaluation_config(
            lingua_model_id=lingua_model_id, lingua_api_key=lingua_api_key
        )
    except ValueError as exc:
        sys.stderr.write(f"Refusing to boot KAINE cycle: {exc}\n")
        return 3
    # Research event log config is INDEPENDENT of [evaluation].enabled — the
    # curated log (and the local-only raw archive) gate on their own flags.
    research_event_log_cfg = load_research_event_log_config()

    # Per-run identity. Minted EARLY — before the seed-sensitive modules or any
    # sink starts — so (a) global randomness is pinned for the whole run and
    # (b) every durable record carries this run's id + seq from the very first
    # write. An explicit [experiment].seed pins the run; a blank one generates a
    # fresh seed that the manifest records, so the run is reproducible after
    # the fact. The context holds only ids/seed/sha/model-ids/config-digest — no
    # entity interior, no operator-identifying data.
    from datetime import datetime, timezone

    from kaine import __version__ as _kaine_version

    experiment_cfg = kaine_config.get("experiment") or {}
    seed = _resolve_seed(kaine_config)
    set_global_seed(seed)
    from kaine.boot import gather_perception_feed_descriptor
    from kaine.plugins import load_plugins

    # Module plugins load (and declare their seams) before the run manifest is
    # written, so the manifest records every substitution. A named plugin that
    # cannot load stops the boot (PluginError) rather than run on defaults.
    plugins = load_plugins(kaine_config, known_modules=known_module_names())

    run_ctx = mint_run_context(
        seed=seed,
        started_at=datetime.now(timezone.utc).isoformat(),
        config=kaine_config,
        model_ids=_gather_model_ids(kaine_config, eval_chat_model_id=eval_cfg.chat_model_id),
        version=_kaine_version,
        # Reproducible perception-feed covariate — gathered at the boot layer
        # (allowed to touch kaine.modules) and passed in as data.
        perception_feed=gather_perception_feed_descriptor(kaine_config),
        plugins=plugins.manifest_entry(),
        revived_from=revive.revived_from if revive is not None else None,
    )
    set_run_context(run_ctx)
    if bool(experiment_cfg.get("write_manifest", True)):
        try:
            manifest_path = write_manifest(run_ctx)
            log.info("run %s manifest written to %s", run_ctx.run_id, manifest_path)
        except Exception:
            log.warning("could not write run manifest", exc_info=True)
    log.info("run_id=%s seed=%d git=%s", run_ctx.run_id, seed, run_ctx.git_sha)

    # Cap torch's CPU thread pool before any module constructs anything
    # heavy. Default cap = max(1, cpu_count // 2), leaving room for the
    # other modules' threads to coexist on a many-core host.
    threads_set = tune_cpu_threads()
    if threads_set:
        log.info("torch CPU thread pool capped at %d threads", threads_set)

    # Cooperative GPU headroom pre-flight (opt-in via [gpu_preflight].enabled).
    # Runs BEFORE the bus/modules open so a starved host refuses to boot cleanly
    # rather than OOM-killing a just-born entity mid-init. It evicts only KAINE's
    # own idle Ollama models and never terminates a process; see preflight.py.
    gpu_cfg = GpuPreflightConfig.from_section(kaine_config.get("gpu_preflight") or {})
    if gpu_cfg.enabled:
        organ_model = (kaine_config.get("lingua") or {}).get("model_id")
        keep = [organ_model] if organ_model else []
        pf = run_preflight(gpu_cfg, keep_models=keep)
        for line in pf.message.splitlines():
            log.info("gpu-preflight: %s", line)
        if not pf.ok:
            sys.stderr.write(
                "Refusing to boot KAINE cycle: insufficient GPU headroom.\n" + pf.message + "\n"
            )
            return 4

    # Boot-time organ CONTENT gate. verify_served_alias proves the right model is
    # LISTED; a served-but-MUTE organ (chain-of-thought not suppressed → empty
    # content) would still pass that yet leave the entity voiceless — the exact
    # way a prior boot came up silent. When Lingua is enabled, probe the organ for
    # real content here and refuse to boot if it returns empty/unreachable. A
    # deliberately-voiceless boot must opt in via KAINE_ALLOW_MUTE_ORGAN=1.
    if (kaine_config.get("modules") or {}).get("lingua"):
        from kaine.organ_window_state import organ_unloaded

        if organ_unloaded():
            log.info("organ-gate: skipped (organ resting — voice-alignment window)")
        else:
            from kaine.setup.organ import verify_organ_generates

            lingua_cfg = kaine_config.get("lingua") or {}
            gate = await verify_organ_generates(
                str(lingua_cfg.get("chat_url", "http://127.0.0.1:11434/v1")),
                str(lingua_cfg.get("model_id") or ""),
                api_key=lingua_cfg.get("api_key") or os.environ.get("KAINE_MODEL_SERVER_API_KEY"),
            )
            log.info("organ-gate: %s", gate.detail)
            if not gate.ok:
                if os.environ.get("KAINE_ALLOW_MUTE_ORGAN") == "1":
                    log.warning(
                        "organ-gate: FAILED but KAINE_ALLOW_MUTE_ORGAN=1 set — "
                        "booting a voiceless entity deliberately"
                    )
                else:
                    sys.stderr.write(
                        "Refusing to boot KAINE cycle: the language organ is not "
                        "producing content.\n" + gate.detail + "\n"
                        "Bring the organ up (serve the model AND suppress thinking) "
                        "or set KAINE_ALLOW_MUTE_ORGAN=1 to boot anyway.\n"
                    )
                    return 5

    bus_config = load_bus_config()
    bus = AsyncBus(bus_config)
    await bus.audit()

    # Emit the first-gestation event now that the bus exists. This is the only
    # lifecycle event that fires at boot; the gate loop emits the rest on a
    # cadence once modules are up.
    if fresh_gestation:
        try:
            await bus.publish(
                _lifecycle_event(
                    STAGE_GESTATION_STARTED,
                    gestation_started_payload(
                        gestation_started_at=stage_state.gestation_started_at
                    ),
                    salience=0.6,
                )
            )
        except Exception:
            log.warning("could not publish stage.gestation.started", exc_info=True)

    async def _publish_lifecycle(type_: str, payload: dict[str, Any], salience: float) -> None:
        await bus.publish(_lifecycle_event(type_, payload, salience=salience))

    # Womb before spawn (maturation-gate-liveness 2.1): a gestating entity is
    # never spawned without a womb that is ready. Hold here, before any module
    # initializes, reporting stage.gestation.no_stimulus on every failed check.
    womb_ready = False
    if staging_enabled and stage_state.is_gestating:
        from kaine.cycle.womb_watch import hold_until_womb_ready

        hold_stop = asyncio.Event()
        hold_loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                hold_loop.add_signal_handler(sig, hold_stop.set)
            except NotImplementedError:
                # Windows / restricted loops have no signal handlers; the default
                # signal behaviour then ends the process, and nothing is spawned yet.
                continue
        try:
            _womb_cfg = MaturationConfig.from_dict(kaine_config.get("developmental_stage"))
            womb_ready = await hold_until_womb_ready(
                kaine_config,
                bus,
                hold_stop,
                publish=_publish_lifecycle,
                retry_seconds=_womb_cfg.womb_ready_retry_seconds,
            )
        finally:
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    hold_loop.remove_signal_handler(sig)
                except NotImplementedError:
                    # Nothing was installed on this loop, so there is nothing to remove.
                    continue
        if not womb_ready:
            log.info("shutdown requested while waiting for the womb; nothing was spawned")
            await bus.close()
            return 0
        from kaine import perception_state as _ps

        _ps.write_desired_locus("virtual", locked=True, locked_by="gestation")
        _ps.write_desired_audio(True)
        _ps.write_desired_video(True)
        log.info("gestation: womb ready; pinned locus to the virtual womb (locked by gestation)")

    # Per-boot act-intent provenance secret (authenticate-intent-provenance,
    # Mechanism B). Generated HERE — the cycle composition root — and held ONLY
    # in this function's scope: it is never published to the bus, written to
    # disk, or logged. The SAME bytes are injected into Praxis (to verify, via
    # build_registry) and Volition (to sign, below), so an act intent forged by
    # any other bus writer fails verification and never reaches an effector.
    intent_secret = generate_intent_secret()

    registry = build_registry(
        bus,
        kaine_config,
        intent_secret=intent_secret,
        plugins=plugins,
        boot_stage=stage_state,
    )
    if not len(registry):
        log.warning("no modules enabled in [modules]; cycle will run but never collect events")

    # Gestation: keep effectors dormant until birth. The gate_runner will
    # call activate() at birth before unlocking the locus.
    if staging_enabled and stage_state.is_gestating:
        _hold_effectors_for_gestation(registry)

    for module in list(registry.all_modules()):
        await module.initialize()

    # Revive the preserved individual after modules initialise (so Eidolon's
    # initialize() reloads its disk file) and before the cognitive cycle starts.
    # Module background loops run briefly on fresh state before the revive lands,
    # which is safe because the cognitive cycle (and so the workspace) has not started.
    if revive is not None:
        refused = await _revive_or_refuse(revive, registry, bus)
        if refused is not None:
            return refused

    # Developmental maturation gate. Constructed after modules exist so it can
    # read Hypnos/Phantasia/Mundus signals; started as a background task once
    # the runtime loop is about to run. Ship-inert when staging is disabled.
    ds_config = MaturationConfig.from_dict(kaine_config.get("developmental_stage"))
    gate_runner = MaturationGateRunner(
        bus=bus,
        config=ds_config,
        registry=registry,
        entity_clock=getattr(registry, "entity_clock", None),
        stage_state=stage_state,
        staging_enabled=staging_enabled,
        womb_feed_configured=womb_ready,
    )

    cycle_cfg = kaine_config.get("cycle") or {}
    syn_cfg = kaine_config.get("syneidesis") or {}
    # Oscillatory-binding coherence layer. `make_coherence_scorer` returns None
    # when [oscillator].enabled is false, in which case Syneidesis selection is
    # bit-for-bit the pre-change behavior (no coherence factor, no metadata key).
    coherence_scorer = make_coherence_scorer(kaine_config)
    # Live four-factor salience (wire-salience-goal-thymos). Both real factors
    # read the entity's current affect/drives through an AffectStateProvider the
    # engine refreshes each tick from thymos.state — dependency injection, so the
    # workspace layer never imports kaine.modules. The Thymos factor ships LIVE
    # by default (the paper's real, already-tested StateModulator); the goal
    # factor is BUILT but ships on the static negative control by default, staged
    # pending validation on logged runs (see config/kaine.toml [syneidesis]).
    affect_provider = AffectStateProvider()
    thymos_modulator, goal_scorer, downgraded_factors = make_salience_factors(
        kaine_config, affect_provider
    )
    # Foveation's fovea size reads the same affect snapshot (arousal → size).
    # Wiring it also means the provider must be refreshed each tick so the arousal
    # it reads is live, not the frozen baseline.
    topos_reads_arousal = _wire_topos_arousal(registry, affect_provider)
    audition_reads_arousal = _wire_audition_arousal(registry, affect_provider)
    # The provider only needs refreshing when a real reader consumes it. When both
    # salience factors are the static negative control AND foveation / general
    # auditory perception are off, the engine stays byte-identical to the
    # pre-change behavior (no affect observation at all).
    # Adaptive conscious access (adaptive-access-rate): the broadcast rate rises
    # from the resting [cycle].experiential_rate_hz toward the processing rate
    # with Thymos arousal (tonic) and salient module reports (phasic). The
    # arousal baseline defaults to Thymos's own so the two cannot disagree.
    from kaine.cycle.access_rate import AccessRateConfig, AccessRateController

    access_rate_cfg = AccessRateConfig.from_section(
        cycle_cfg.get("access_rate"),
        default_baseline=float(
            (kaine_config.get("thymos") or {}).get("baseline_arousal", 0.3)
        ),
    )
    access_rate = AccessRateController(access_rate_cfg) if access_rate_cfg.enabled else None
    reads_affect = (
        isinstance(thymos_modulator, StateModulator)
        or isinstance(goal_scorer, DriveRelevanceGoalScorer)
        or topos_reads_arousal
        or audition_reads_arousal
        or access_rate is not None
    )
    affect_observer = affect_provider.observe if reads_affect else None
    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=int(syn_cfg.get("novelty_window", 32))),
            goal_scorer=goal_scorer,
            thymos_modulator=thymos_modulator,
            downgraded_factors=downgraded_factors,
        ),
        top_k=int(syn_cfg.get("top_k", 5)),
        publication_threshold=float(syn_cfg.get("publication_threshold", 0.35)),
        coherence=coherence_scorer,
    )
    # Executive action selection. By default the drive-biased policy is
    # injected (`drives-to-behavior`): it subsumes the conservative default
    # user-response behavior (one disposition-gated speak intent, no
    # self-response, one-in-flight guard) AND turns drive threshold-crossings
    # that reached the non-inhibited coalition into intents (social_drive →
    # speak initiative; curiosity/boredom/restlessness → internal think).
    # Inhibition still gates everything (Volition checks `inhibited` first).
    # An operator can disable drive initiative — falling back to the plain
    # default policy — via `[volition].drive_initiative = false`.
    volition_cfg = kaine_config.get("volition") or {}
    policy_name = str(volition_cfg.get("policy", "")).strip().lower()
    drive_initiative = bool(volition_cfg.get("drive_initiative", True))
    # Operator-channel set is shared between Empatheia attribution and Volition
    # user-utterance detection. A single [empatheia].operator_sources key
    # configures both.
    empatheia_cfg = kaine_config.get("empatheia") or {}
    _operator_sources_raw = empatheia_cfg.get("operator_sources")
    operator_sources = None
    if _operator_sources_raw is not None:
        if not isinstance(_operator_sources_raw, list) or not all(
            isinstance(x, str) for x in _operator_sources_raw
        ):
            raise ValueError("[empatheia].operator_sources must be a list of strings")
        operator_sources = list(_operator_sources_raw)
    # Sign act intents with the per-boot secret so Praxis can verify their
    # provenance. run_id ties the signature to this run; the signer mints a
    # monotonic seq per intent so a captured signed intent cannot be replayed.
    intent_signer = IntentSigner(intent_secret, run_ctx.run_id)
    if policy_name == "self_initiated_report":
        # Self-initiated report gate: the entity speaks only from its own
        # precision-weighted surprise (no user-utterance / chatbot trigger).
        # Refractory timing reads the shared subjective clock.
        from kaine.workspace.report_policy import SelfInitiatedReportPolicy

        _report_clock = registry.entity_clock.now if registry.entity_clock is not None else None
        # Interruptible utterances (PR #81) are opt-in: an absent
        # [volition].interrupt_threshold keeps await-to-completion; a set
        # value must sit strictly above the report bar (enforced by the
        # policy itself).
        _interrupt_raw = volition_cfg.get("interrupt_threshold")
        # H4 — without an expiry the coarse (source, type) novelty signature
        # suppresses same-signature reports FOREVER; on a stable stimulus the
        # top coalition rarely changes signature, so external speech trends to
        # zero over a multi-day run. None (unset) preserves never-expire.
        _sig_expiry_raw = volition_cfg.get("sig_expiry_s")
        volition = Volition(
            policy=SelfInitiatedReportPolicy(
                report_threshold=float(volition_cfg.get("report_threshold", 0.6)),
                think_threshold=float(volition_cfg.get("think_threshold", 0.45)),
                interrupt_threshold=(float(_interrupt_raw) if _interrupt_raw is not None else None),
                speak_refractory_s=float(volition_cfg.get("speak_refractory_s", 8.0)),
                think_refractory_s=float(volition_cfg.get("think_refractory_s", 3.0)),
                sig_expiry_s=(float(_sig_expiry_raw) if _sig_expiry_raw is not None else None),
                clock=_report_clock,
            ),
            signer=intent_signer,
            operator_sources=operator_sources,
        )
    elif drive_initiative:
        volition = Volition(
            policy=DriveBiasedActionSelectionPolicy(operator_sources=operator_sources),
            signer=intent_signer,
            operator_sources=operator_sources,
        )
    else:
        volition = Volition(
            signer=intent_signer,
            operator_sources=operator_sources,
        )
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=registry,
        processing_rate_hz=float(cycle_cfg.get("processing_rate_hz", 10.0)),
        # Resting conscious-access (P3b) rate; held below processing so the
        # senses outrun awareness. With [cycle.access_rate] enabled the rate used
        # each tick rises from here toward the processing rate with arousal and
        # salient reports; this value stays the resting rate.
        experiential_rate_hz=float(cycle_cfg.get("experiential_rate_hz", 3.333)),
        volition=volition,
        collect_phases=coherence_scorer is not None,
        # H3: tail-seed all cursors so a restarted live entity never replays
        # pre-boot bus events (tests keep the historical read-from-start).
        seed_cursors_to_tail=True,
        # Global subjective-time dilation. 1.0 = real-time (the shipped default,
        # behavior-identical); 0 = frozen (reuses the existing freeze/suspend
        # path — the subjective clock stops); >1 = dilated-fast as an aspirational
        # target (the cycle attempts the faster rate and the existing slip
        # measurement records any overrun honestly). Phase 3 wires the >1
        # throttle/report.
        time_scale=float(cycle_cfg.get("time_scale", 1.0)),
        # The ONE shared subjective clock built by build_registry from
        # [cycle].time_scale and injected into every cognitive module. Handing
        # the SAME instance to the cycle (it takes precedence over time_scale
        # above) means the tick pacing and the modules' cognitive timers dilate
        # off a single time_scale — they can never desynchronize. None only if a
        # registry was built without one (then the cycle constructs its own from
        # time_scale, identical at 1.0).
        entity_clock=registry.entity_clock,
        # Plugins that implement on_cycle_tick observe each tick (plugin-cycle-hook);
        # None when no loaded plugin does, which leaves the cycle unchanged.
        tick_observer=plugins.cycle_observer(),
        # Deterministic mode (opt-in, [experiment].deterministic; default false).
        # When true the engine stamps events from a logical clock and the seed
        # A1 already pinned makes the run bit-for-bit reproducible. Production
        # leaves it false → real wall-clock time. Used by ablation experiments.
        deterministic=bool(experiment_cfg.get("deterministic", False)),
        # DI seam for the live salience factors: the engine refreshes the affect/
        # drive snapshot from each tick's thymos.state. None when both factors are
        # the static negative control (then the tick is byte-identical).
        affect_observer=affect_observer,
        access_rate=access_rate,
        arousal_provider=(
            (lambda: affect_provider.dimensional_state().arousal)
            if access_rate is not None
            else None
        ),
    )
    # Make a live MetricsCollector reachable by Nexus.
    _ = MetricsCollector(cycle, registry)

    # Spot module supervisor (cycle-layer component, not a registry module).
    spot_cfg = SpotConfig.from_section(kaine_config.get("spot") or {})
    fork_manager = ForkManager(Path("state/forks"))

    rebuild_module = _make_rebuild_module(bus, kaine_config, registry, intent_secret)

    await _write_runtime_state(
        cycle,
        registry,
        supervision_mode=supervision_mode,
        gate_checks=gate_checks,
        stage_state=stage_state,
        staging_enabled=staging_enabled,
        revived_from=revive.revived_from if revive is not None else None,
    )

    # Optional evaluation sidecar. NO core module imports kaine.evaluation;
    # the cycle entrypoint is the single coupling point. eval_cfg was loaded at
    # the top of _boot_and_run (fail-closed before any resource opened).
    sidecar: SidecarRegistry | None = None
    research_active = research_event_log_cfg.enabled or research_event_log_cfg.raw_archive.enabled
    if eval_cfg.enabled or research_active:
        sidecar = SidecarRegistry(
            bus=bus,
            config=eval_cfg,
            research_event_log_config=research_event_log_cfg,
            thymos_state_provider=_thymos_state_factory(registry),
            sleep_state_provider=_sleep_state_factory(registry),
            memory_source=_memory_source_factory(registry),
            cognitive_query_client=_cognitive_query_client_factory(registry, eval_cfg),
        )
        try:
            await sidecar.start()
            log.info("evaluation sidecar started")
        except Exception:
            log.warning("evaluation sidecar start failed", exc_info=True)
            sidecar = None

    # Attach the live oscillatory-ablation recorder to the cycle once the sidecar
    # (and its ablation sink) is up. Off unless [evaluation].oscillatory_ablation
    # is set; when off this is a no-op and the cycle takes the plain select path.
    if sidecar is not None and sidecar.ablation_recorder is not None:
        cycle.set_ablation_recorder(sidecar.ablation_recorder)
        log.info("live oscillatory ablation attached to cycle")

    ignition_log = None
    try:
        il_cfg = IgnitionLogConfig.from_section(kaine_config.get("ignition_log"))
    except Exception:
        log.warning("ignition log config invalid; continuing without it", exc_info=True)
        il_cfg = IgnitionLogConfig(enabled=False)

    if il_cfg.enabled:
        try:
            from kaine.modules.topos.feed import load_playlist_manifest

            perception_cfg = kaine_config.get("perception_feed") or {}
            clock = perception_cfg.get("_shared_playlist_clock")
            manifest_path = perception_cfg.get("playlist_manifest")

            if clock is not None and manifest_path:
                manifest = load_playlist_manifest(str(manifest_path))
                position_provider = playlist_position_provider(clock, manifest)
            else:
                def position_provider() -> tuple[int, int, str, float, bool] | None:
                    return None

            audition_mod = registry.get("audition")
            if audition_mod is not None and hasattr(
                audition_mod, "playlist_audio_position"
            ):
                audio_position_provider = audition_mod.playlist_audio_position
            else:
                def audio_position_provider() -> tuple[int, float] | None:
                    return None

            sink = AsyncJsonlSink(
                Path(il_cfg.directory), name="ignition", retention_days=0
            )
            await sink.start()
            ignition_log = IgnitionLog(
                sink,
                position_provider,
                audio_position_provider=audio_position_provider,
            )
            cycle.set_broadcast_observer(ignition_log)
            log.info("ignition log enabled directory=%s", il_cfg.directory)
        except Exception:
            log.warning(
                "ignition log setup failed; continuing without it", exc_info=True
            )
            ignition_log = None

    # Dev-gated LOOPBACK perception-preview server (paper §4.4 explicit
    # override). Populated by Topos/Audition, this bridges the in-RAM preview
    # holder to the SEPARATE Nexus process over a 127.0.0.1-only socket so the
    # live PiP shows what the entity sees. Off by default; only binds when the
    # operator exports KAINE_PERCEPTION_PREVIEW=1. Frames never touch disk.
    preview_server = None
    try:
        from kaine import perception_preview
        from kaine.perception_preview_server import start_preview_server

        preview_server = await start_preview_server(config=kaine_config)
        if preview_server is not None:
            log.info(
                "perception preview server on loopback %s:%d (dev override)",
                preview_server.host,
                preview_server.port,
            )
    except Exception:
        log.warning("perception preview server failed to start", exc_info=True)
        preview_server = None

    # Optional remote perception bridge ([remote_bridge].enabled; ships off).
    # Cycle-layer component like Spot: injects remote operator A/V into the
    # perception modules and streams speech/transcript back over the tailnet.
    remote_bridge = None
    try:
        from kaine.remote.bridge import build_remote_bridge

        remote_bridge = build_remote_bridge(kaine_config, bus=bus, registry=registry)
        if remote_bridge is not None:
            await remote_bridge.start()
    except Exception:
        log.error("remote bridge failed to start", exc_info=True)
        remote_bridge = None

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        log.info("signal received; shutting down")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows / restricted env — fall through to KeyboardInterrupt path.
            pass

    # A fresh launch always starts running: clear any stale operator freeze the
    # previous run may have left behind (freeze is a runtime control, not a boot
    # state).
    try:
        unfreeze()
    except Exception:
        log.debug("could not clear freeze control at startup", exc_info=True)
    # A deliberate fresh launch also clears any prior escalation halt.
    try:
        clear_escalation()
    except Exception:
        log.debug("could not clear escalation at startup", exc_info=True)

    spot = Spot(
        registry=registry,
        fork_manager=fork_manager,
        kaine_config=kaine_config,
        config=spot_cfg,
        rebuild_module=rebuild_module,
        bus=bus,
        on_halt=lambda: stop_event.set(),
        # Best-effort tick<->poll bridge: lets a spot.incident annotation be
        # located within the run by cycle tick, not just Spot's poll index.
        tick_index_provider=lambda: cycle.tick_index,
        escalate_on_crash=(supervision_mode == "unattended"),
    )

    # Autonomous welfare safety-net monitors (cycle-layer, siblings to Spot):
    # the divergence→preserve trigger and the welfare-protective response. Both
    # ship disabled; they reuse the same ForkManager + IncidentLog patterns as
    # Spot and never import kaine.evaluation (the welfare signal is read straight
    # off soma.out via the shared core SustainedThresholdTracker).
    from kaine.cycle.incident_log import IncidentLog
    from kaine.cycle.preservation_monitor import (
        DivergenceMonitor,
        PreservationConfig,
        WelfareProtectiveMonitor,
    )

    preservation_cfg = PreservationConfig.from_section(kaine_config.get("preservation") or {})
    divergence_monitor = None
    welfare_monitor = None
    if preservation_cfg.divergence_monitor.enabled:
        divergence_monitor = DivergenceMonitor(
            registry=registry,
            fork_manager=fork_manager,
            config=preservation_cfg.divergence_monitor,
            bus=bus,
            incident_log=IncidentLog(
                enabled=True,
                path=preservation_cfg.incident_path,
                name="preservation_divergence",
            ),
            # Lived-experience source for the warm-up gate: the cycle's
            # monotonic tick index (logged lived events). The monitor measures
            # lived time off its own monotonic clock. Until BOTH floors are met,
            # no individuation crossing counts — fail-closed.
            observations_provider=lambda: cycle.tick_index,
            require_encryption=preservation_cfg.require_encryption,
        )
    if supervision_mode == "unattended":
        from kaine.cycle.caretaker import CaretakerConfig
        from kaine.cycle.caretaker_runtime import CaretakerNotifier

        caretaker = CaretakerNotifier(
            CaretakerConfig.from_section(kaine_config.get("caretaker") or {})
        )
        await caretaker.start()
    else:
        caretaker = None

    _caretaker_tasks: set[asyncio.Task] = set()

    def _on_welfare_response(action: str) -> None:
        if caretaker is None:
            return
        try:
            task = asyncio.get_running_loop().create_task(
                caretaker.send_event("welfare_response")
            )
        except RuntimeError:
            return
        _caretaker_tasks.add(task)
        task.add_done_callback(_caretaker_tasks.discard)

    if preservation_cfg.welfare_response.enabled:
        welfare_monitor = WelfareProtectiveMonitor(
            registry=registry,
            fork_manager=fork_manager,
            config=preservation_cfg.welfare_response,
            bus=bus,
            incident_log=IncidentLog(
                enabled=True,
                path=preservation_cfg.incident_path,
                name="preservation_welfare",
            ),
            on_end=lambda: stop_event.set(),
            require_encryption=preservation_cfg.require_encryption,
            on_response=_on_welfare_response,
        )

    cycle_task = asyncio.create_task(cycle.run_forever(), name="cycle.run_forever")
    freeze_task = asyncio.create_task(
        _freeze_watch_loop(
            cycle,
            stop_event,
            playlist_clock=(kaine_config.get("perception_feed") or {}).get(
                "_shared_playlist_clock"
            ),
        ),
        name="cycle.freeze_watch",
    )
    spot_task = (
        asyncio.create_task(spot.run(stop_event), name="cycle.spot") if spot_cfg.enabled else None
    )
    divergence_task = (
        asyncio.create_task(divergence_monitor.run(stop_event), name="cycle.divergence_monitor")
        if divergence_monitor is not None
        else None
    )
    welfare_task = (
        asyncio.create_task(welfare_monitor.run(stop_event), name="cycle.welfare_monitor")
        if welfare_monitor is not None
        else None
    )
    # Frozen time is not lived time: the runner subtracts the subjective time
    # the cycle spends paused (maturation-gate-liveness 2.5).
    # A frozen entity is never born, whoever froze it.
    gate_runner.set_pause_sources(
        paused_seconds=cycle.paused_subjective_seconds,
        is_paused=lambda: cycle.is_paused,
    )
    # Birth transition (local-womb-feed 3.6): at birth the local womb blooms
    # once over birth_transition_seconds, then falls silent.
    _womb_feed = kaine_config.get("perception_feed") or {}
    _birth_clock = _womb_feed.get("_shared_womb_clock")
    if _birth_clock is not None:
        from kaine.boot import _womb_params

        _birth_seconds = _womb_params(_womb_feed).birth_transition_seconds
        gate_runner.set_birth_hook(lambda: _birth_clock.begin_birth(_birth_seconds))
    gate_task = (
        asyncio.create_task(gate_runner.run(stop_event), name="cycle.maturation_gate")
        if staging_enabled and stage_state.is_gestating
        else None
    )
    # Womb loss (maturation-gate-liveness 2.2): freeze a gestating entity under
    # its own holder when the womb stops, and release it when the womb returns.
    womb_watch_task = None
    if staging_enabled and stage_state.is_gestating:
        from kaine.cycle.womb_watch import WombLossWatcher

        womb_watch_task = asyncio.create_task(
            WombLossWatcher(
                kaine_config,
                bus,
                publish=_publish_lifecycle,
                is_gestating=lambda: gate_runner.stage.is_gestating,
                notify=caretaker.send_event if caretaker is not None else None,
                check_seconds=ds_config.womb_check_seconds,
                loss_after_seconds=ds_config.womb_loss_after_seconds,
                window_s=ds_config.womb_presence_window_seconds,
                arm_timeout_seconds=ds_config.womb_arm_timeout_seconds,
            ).run(stop_event),
            name="cycle.womb_watch",
        )
    caretaker_task = (
        asyncio.create_task(caretaker.run(stop_event), name="cycle.caretaker")
        if caretaker is not None
        else None
    )
    input_watch_task = None
    if caretaker is not None:
        from kaine.cycle.caretaker import CaretakerConfig as _InputCaretakerConfig
        from kaine.cycle.input_check import InputLossWatcher

        streams: list[str] = []
        modules = kaine_config.get("modules") or {}
        if modules.get("topos"):
            streams.append("topos.out")
        if modules.get("audition"):
            streams.append("audition.out")

        if streams:
            # Validated by the gate (condition 7) before admission.
            threshold_s = _InputCaretakerConfig.from_section(
                kaine_config.get("caretaker") or {}
            ).input_loss_after_s
            input_watch_task = asyncio.create_task(
                InputLossWatcher(
                    bus,
                    streams,
                    threshold_s=threshold_s,
                    on_loss=lambda: caretaker.send_event("input_lost"),
                ).run(stop_event),
                name="cycle.input_watch",
            )
    # A running local womb proves itself from real deliveries: presence events
    # on gestation.out (the same contract an external provider uses), which the
    # maturation gate reads to detect womb loss. gestation.out is not a module
    # stream, so presence never enters the workspace.
    womb_presence_task = _start_womb_presence(kaine_config, bus, stop_event)
    # The readiness readout (local-womb-feed phase 3): measures, never imposes.
    gestation_task = None
    if staging_enabled and stage_state.is_gestating:
        gestation_task = _start_gestation_owner(
            kaine_config,
            bus,
            registry,
            stop_event,
            is_paused=lambda: cycle.is_paused,
        )

    preserve_task = _start_preserve_watcher(
        registry,
        fork_manager,
        preservation_cfg,
        is_paused=lambda: cycle.is_paused,
        request_stop=stop_event.set,
        stop_event=stop_event,
    )
    programme_end_task = _start_programme_end_watcher(
        kaine_config,
        notify=caretaker.send_event if caretaker is not None else None,
        stop_event=stop_event,
    )

    try:
        # Periodically update runtime.json so Nexus has fresh metrics
        # even before any tick happens.
        while not stop_event.is_set() and not cycle_task.done():
            if supervision_mode == "unattended":
                if spot_task is None:
                    log.critical(
                        "Spot supervision task was never started; escalating"
                    )
                    await spot.escalate_supervision_lost(
                        "supervision task never started"
                    )
                    stop_event.set()
                    break
                if spot_task.done() and not spot.escalated:
                    log.critical(
                        "Spot supervision task ended unexpectedly; escalating"
                    )
                    await spot.escalate_supervision_lost(
                        "supervision task ended"
                    )
                    stop_event.set()
                    break
            await _write_runtime_state(
                cycle,
                registry,
                supervision_mode=supervision_mode,
                gate_checks=gate_checks,
                stage_state=gate_runner.stage if staging_enabled else None,
                gate_status=gate_runner.status if staging_enabled else None,
                staging_enabled=staging_enabled,
                revived_from=revive.revived_from if revive is not None else None,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
    finally:
        if womb_presence_task is not None:
            womb_presence_task.cancel()
            try:
                await womb_presence_task
            except asyncio.CancelledError:
                # Expected: we just cancelled it.
                log.debug("womb presence task cancelled at shutdown")
            except Exception:
                log.exception("womb presence task shutdown failed")
        if input_watch_task is not None:
            input_watch_task.cancel()
            try:
                await input_watch_task
            except asyncio.CancelledError:
                # Expected: we just cancelled it.
                log.debug("input watch task cancelled at shutdown")
            except Exception:
                log.exception("input watch task shutdown failed")
        if caretaker is not None:
            try:
                if spot.escalated:
                    from kaine.cycle.escalation_state import read_escalation

                    rec = read_escalation()
                    await caretaker.send_event(
                        "supervision_lost" if rec.module == "spot" else "spot_escalation"
                    )
            except Exception:
                log.warning("caretaker escalation notice failed", exc_info=True)
            try:
                if _caretaker_tasks:
                    await asyncio.gather(*_caretaker_tasks, return_exceptions=True)
            except Exception:
                log.warning("caretaker welfare tasks shutdown failed", exc_info=True)
            try:
                if caretaker_task is not None and not caretaker_task.done():
                    caretaker_task.cancel()
                    try:
                        await caretaker_task
                    except asyncio.CancelledError:
                        # Expected: we just cancelled it.
                        log.debug("caretaker task cancelled at shutdown")
                    except Exception:
                        log.warning("caretaker task raised during shutdown", exc_info=True)
            except Exception:
                log.warning("caretaker task cancellation failed", exc_info=True)
            try:
                await caretaker.stop()
            except Exception:
                log.warning("caretaker stop failed", exc_info=True)
        if not freeze_task.done():
            freeze_task.cancel()
        try:
            await freeze_task
        except asyncio.CancelledError:
            pass  # expected: we just cancelled it
        except Exception:
            log.warning("freeze watch task raised during shutdown", exc_info=True)
        if spot_task is not None:
            if not spot_task.done():
                spot_task.cancel()
            try:
                await spot_task
            except asyncio.CancelledError:
                pass  # expected: we just cancelled it
            except Exception:
                log.warning("spot watchdog task raised during shutdown", exc_info=True)
        for monitor_task in (
            divergence_task, welfare_task, gate_task, womb_watch_task, gestation_task, preserve_task, programme_end_task
        ):
            if monitor_task is None:
                continue
            if not monitor_task.done():
                monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass  # expected: we just cancelled it
            except Exception:
                log.warning("%s raised during shutdown", monitor_task.get_name(), exc_info=True)
        if preview_server is not None:
            try:
                await preview_server.stop()
            except Exception:
                log.warning("perception preview server stop failed", exc_info=True)
            # Drop any lingering in-RAM preview so no stale frame survives the
            # cycle even in-process.
            try:
                perception_preview.clear()
            except Exception:
                log.debug("preview holder clear failed", exc_info=True)
        if remote_bridge is not None:
            try:
                await remote_bridge.stop()
            except Exception:
                log.warning("remote bridge stop failed", exc_info=True)
        if sidecar is not None:
            try:
                await sidecar.stop()
            except Exception:
                log.warning("evaluation sidecar stop failed", exc_info=True)
        try:
            il = ignition_log
        except NameError:
            il = None
        if il is not None:
            try:
                await il.close()
            except Exception:
                log.warning("ignition log close failed", exc_info=True)
        await cycle.shutdown()
        if not cycle_task.done():
            cycle_task.cancel()
        try:
            await cycle_task
        except (asyncio.CancelledError, Exception):
            log.debug("cycle task ended", exc_info=True)
        for module in list(registry.all_modules()):
            try:
                await module.shutdown()
            except Exception:
                log.warning("module %s shutdown failed", module.name, exc_info=True)
        await bus.close()
        _clear_runtime_state()
    # Non-zero exit when Spot escalated, so a process wrapper sees the halt and
    # the operator-reboot requirement is honored rather than silently retried.
    if spot is not None and spot.escalated:
        return 70
    return 0


def _research_logging_active(config: dict[str, Any]) -> bool:
    """True when full logging / admissibility is active for a research run.

    Either the evaluation sidecar (run identity + observers) OR the research
    event log (the curated annotation stream / raw archive) being enabled
    satisfies the "logging/admissibility active" condition of the research gate.
    """
    from kaine.cycle.research_gate import _logging_active

    return _logging_active(config)


def _evaluate_research_safety_net(config: dict[str, Any]) -> "Any":
    """Run the four-condition research gate over the resolved config.

    Reads the [preservation] toggles + the logging toggles, then performs the
    real dry preserve→revive self-check, and returns the combined GateResult.
    """
    from kaine.cycle.research_gate import evaluate_safety_net

    return evaluate_safety_net(config)


def _evaluate_unattended_gate(config: dict[str, Any]) -> "Any":
    """Run the eight-condition unattended gate over the resolved config.

    Reuses the research safety net for conditions 1–5.  Condition 6 comes from
    Spot's selftest.  Condition 8 requires a continuous perception input.
    Condition 7 runs last and needs the outcome of conditions 1–6 and 8 as
    prerequisites.
    """
    net = _evaluate_research_safety_net(config)
    from kaine.cycle.caretaker import check_caretaker_condition
    from kaine.cycle.input_check import check_input_condition
    from kaine.cycle.spot_selftest import check_spot_condition
    from kaine.cycle.unattended_gate import evaluate_unattended_gate

    spot = check_spot_condition(config.get("spot") or {})
    eight = check_input_condition(config)

    # Condition 7 must report on 1–6 and 8, but must not include itself.
    checks = dict(evaluate_unattended_gate(net, built={6: spot, 8: eight}).checks)
    checks.pop("7_caretaker_told", None)
    prerequisites_ok = all(checks.values())

    seven = check_caretaker_condition(
        config.get("caretaker"), prerequisites_ok=prerequisites_ok, conditions=checks
    )
    return evaluate_unattended_gate(net, built={6: spot, 7: seven, 8: eight})


def _record_unattended_gate(result: Any) -> None:
    """Durably append one JSON record of the unattended gate evaluation.

    Best-effort: a write failure is logged and MUST NOT change the boot outcome.
    Paths in condition reasons are scrubbed before write.
    """
    from kaine.cycle.incident_log import IncidentLog, scrub_paths

    logger = logging.getLogger(__name__)
    try:
        conditions = [
            {
                "number": c.number,
                "name": c.name,
                "ok": bool(c.ok),
                "reason": scrub_paths(c.reason),
            }
            for c in result.conditions
        ]
        record: dict[str, Any] = {
            "transition": "gate",
            "ok": bool(result.ok),
            "conditions": conditions,
        }

        async def _write() -> None:
            log = IncidentLog(
                enabled=True, path="state/cycle/incidents", name="unattended_gate"
            )
            await log.start()
            try:
                await log.write(record)
            finally:
                await log.stop()

        asyncio.run(_write())
    except Exception:
        logger.warning("failed to record unattended gate evaluation", exc_info=True)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from kaine.config import ProfileError
    from kaine.cycle.caretaker_runtime import send_event_best_effort
    from kaine.cycle.research_gate import RESEARCH_GATE_EXIT_CODE
    from kaine.cycle.unattended_gate import (
        UNATTENDED_GATE_EXIT_CODE,
        SupervisionConfigError,
        resolve_supervision_mode,
    )

    # --profile selects a named deployment-tier overlay (openspec
    # deployment-tiers); it merely layers config, exactly like KAINE_PROFILE, and
    # never auto-applies beyond the operator's deliberate choice here. Unknown
    # flags are left for the existing downstream handling (parse_known_args).
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--revive", default=None)
    known, _ = parser.parse_known_args(argv)

    # Load config early enough to decide the boot mode. A run is EITHER
    # operator-present OR research-safety-net-verified, never neither. The
    # no-profile path calls _load_kaine_config() with its historical signature
    # (so existing seams are unchanged); a profile is threaded only when the
    # operator explicitly selected one via --profile / KAINE_PROFILE.
    try:
        if known.profile is None and "KAINE_PROFILE" not in os.environ:
            config = _load_kaine_config()
        else:
            config = _load_kaine_config(profile=known.profile)
    except ProfileError as exc:
        sys.stderr.write(f"kaine.cycle: configuration error: {exc}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"Refusing to boot KAINE cycle: could not load config: {exc}\n")
        return 1

    # Exactly one mode per boot. Conflicting selectors refuse before any gate.
    try:
        mode = resolve_supervision_mode(config)
    except SupervisionConfigError as exc:
        sys.stderr.write(f"kaine.cycle: configuration error: {exc}\n")
        return 1

    # The gate is evaluated EXACTLY ONCE here (sync, before the event loop, so
    # the self-check's asyncio.run() does not nest) and threaded into
    # _boot_and_run for runtime.json — never recomputed inside the loop.
    supervision_mode = "operator"
    gate_checks: dict[str, bool] | None = None
    if mode == "unattended":
        # Unattended boot: the eight-condition safety net must be satisfied.
        result = _evaluate_unattended_gate(config)
        for c in result.conditions:
            status = "pass" if c.ok else f"FAIL — {c.reason}"
            log.info("unattended gate %d: %s: %s", c.number, c.name, status)
        # Durably record the gate outcome before the allow/refuse branch.
        _record_unattended_gate(result)
        if not result.ok:
            sys.stderr.write(result.message() + "\n")
            # Best-effort caretaker notice about the refusal; an error here must
            # not change the exit code.
            try:
                from kaine.cycle.caretaker import send_refusal_notice
                send_refusal_notice(config.get("caretaker"), result.checks)
            except Exception:
                log.exception("failed to send caretaker refusal notice")
            return UNATTENDED_GATE_EXIT_CODE
        log.info(result.message())
        supervision_mode = "unattended"
        gate_checks = dict(result.checks)
    elif mode == "research":
        # Unsupervised research boot: the operator-present requirement is
        # REPLACED by the safety-net-present gate (preservation + welfare
        # response + logging + a passing dry preserve→revive self-check).
        result = _evaluate_research_safety_net(config)
        if not result.ok:
            sys.stderr.write(result.message() + "\n")
            return RESEARCH_GATE_EXIT_CODE
        log.info(result.message())
        supervision_mode = "research"
        gate_checks = dict(result.checks)
    elif os.environ.get("KAINE_CYCLE_OPERATOR_PRESENT") != "1":
        sys.stderr.write(
            "Refusing to boot KAINE cycle: operator must be present.\n"
            "\n"
            "Export KAINE_CYCLE_OPERATOR_PRESENT=1 and re-run. The cycle is the\n"
            "entity; do not start it unattended. See FIRST_BOOT.md.\n"
            "\n"
            "For an unsupervised research run, enable the autonomous safety net\n"
            "and set KAINE_RESEARCH_MODE=1 (or [research].enabled) instead.\n"
        )
        return 2

    revive = None
    if known.revive is not None:
        from kaine.cycle.revive_boot import (
            REVIVE_REFUSED_EXIT,
            ReviveRefused,
            ReviveSession,
            prepare_revive,
        )

        try:
            plan = prepare_revive(known.revive)
        except ReviveRefused as exc:
            sys.stderr.write(f"kaine.cycle: revive refused: {exc}\n")
            return REVIVE_REFUSED_EXIT

        revive = ReviveSession(plan)

    from kaine.plugins import PluginError

    kwargs = {
        "supervision_mode": supervision_mode,
        "gate_checks": gate_checks,
    }
    if revive is not None:
        kwargs["revive"] = revive

    try:
        return asyncio.run(_boot_and_run(**kwargs))
    except PluginError as exc:
        # A named plugin that cannot load or supply its seams stops the boot:
        # running on the default models would misrepresent the run.
        if supervision_mode == "unattended":
            try:
                send_event_best_effort(config.get("caretaker"), "boot_failed")
            except Exception:
                log.exception("failed to send caretaker boot_failed notice")
        sys.stderr.write(f"kaine.cycle: plugin error: {exc}\n")
        return 1
    except Exception:
        if supervision_mode == "unattended":
            try:
                send_event_best_effort(config.get("caretaker"), "boot_failed")
            except Exception:
                log.exception("failed to send caretaker boot_failed notice")
        raise
    except KeyboardInterrupt:
        log.info("interrupted; shutdown complete")
        return 0


if __name__ == "__main__":
    sys.exit(main())
