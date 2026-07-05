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

import asyncio
import json
import logging
import os
import signal
import sys
import tomllib
from pathlib import Path
from typing import Any

from kaine.boot import (
    SIMPLE_FACTORIES,
    MetricsCollector,
    build_registry,
    make_coherence_scorer,
    make_hypnos,
    make_salience_factors,
    rewire_module,
)
from kaine.boot import _CLOCKED_FACTORIES as CLOCKED_FACTORIES
from kaine.bus.client import AsyncBus
from kaine.bus.config import load_bus_config, load_secrets_doc
from kaine.cycle.affect_state import AffectStateProvider
from kaine.cycle.control_state import read_control, unfreeze
from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.escalation_state import clear_escalation, read_escalation
from kaine.cycle.preflight import GpuPreflightConfig, run_preflight
from kaine.cycle.spot import Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.perception_state import write_desired_audio, write_desired_video
from kaine.state_io import write_json_atomic
from kaine.evaluation import SidecarRegistry, load_evaluation_config
from kaine.evaluation.config import load_research_event_log_config
from kaine.experiment import mint_run_context, set_global_seed, set_run_context, write_manifest
from kaine.hardware import tune_cpu_threads
from kaine.modules.thymos.modulator import StateModulator
from kaine.workspace import (
    DriveRelevanceGoalScorer,
    NoveltyTracker,
    RuleBasedSalience,
    Syneidesis,
)
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.security.intent_signing import IntentSigner, generate_intent_secret
from kaine.workspace.volition import Volition

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
                recalls = await mnemos.recall(
                    "what happened earlier", k=20, collection="episodic"
                )
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
            return {"text": oldest.text, "timestamp": oldest.payload.get("timestamp"),
                    **oldest.payload}

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
                        prompt=prompt, model=model,
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
                pass

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
    resolved = env.get("KAINE_QDRANT_API_KEY") or (
        (secrets_doc.get("qdrant") or {}).get("api_key")
    )
    if not resolved:
        return  # no empty injection — each module surfaces its own error
    for section, qdrant_cfg in targets:
        qdrant_cfg["api_key"] = resolved
        section["qdrant"] = qdrant_cfg


async def _freeze_watch_loop(cycle: CognitiveCycle, stop_event: asyncio.Event) -> None:
    """Poll the operator freeze control and pause/resume the cycle to match.

    Runs independently of `run_forever`'s pause gate, so it can resume a frozen
    cycle (a paused tick loop never reads its own resume). Freezing also pauses
    live perception so no sensory data accumulates while the entity is suspended.
    """
    while not stop_event.is_set():
        try:
            control = read_control()
            if control.frozen and not cycle.is_paused:
                log.info(
                    "freezing cycle (operator)%s",
                    f": {control.reason}" if control.reason else "",
                )
                await cycle.pause()
                try:
                    write_desired_audio(False)
                    write_desired_video(False)
                except Exception:
                    log.debug("perception pause on freeze failed", exc_info=True)
            elif not control.frozen and cycle.is_paused:
                log.info("resuming cycle (operator)")
                await cycle.resume()
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
) -> dict[str, Any]:
    from kaine.config import OPERATOR_CONFIG_PATH, load_kaine_config

    target = Path(path or "config/kaine.toml")
    if not target.exists():
        raise FileNotFoundError(f"config/kaine.toml not found at {target}")
    # Deep-merge the gitignored operator override (config/kaine.operator.toml)
    # over the shipped config before merging secrets, so operator choices from
    # the first-run wizard apply at boot.
    config = load_kaine_config(target, OPERATOR_CONFIG_PATH)
    _merge_qdrant_secret(config, secrets_path=secrets_path, env=env)
    return config


async def _write_runtime_state(
    cycle: CognitiveCycle,
    registry,
    *,
    supervision_mode: str | None = None,
    gate_checks: dict[str, bool] | None = None,
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


async def _boot_and_run(
    *,
    supervision_mode: str = "operator",
    gate_checks: dict[str, bool] | None = None,
) -> int:
    kaine_config = _load_kaine_config()
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
    # fresh seed that the manifest records, so the run is reproducible after the
    # fact. The context holds only ids/seed/sha/model-ids/config-digest — no
    # entity interior, no operator-identifying data.
    from datetime import datetime, timezone

    from kaine import __version__ as _kaine_version

    experiment_cfg = kaine_config.get("experiment") or {}
    seed = _resolve_seed(kaine_config)
    set_global_seed(seed)
    from kaine.boot import gather_perception_feed_descriptor

    run_ctx = mint_run_context(
        seed=seed,
        started_at=datetime.now(timezone.utc).isoformat(),
        config=kaine_config,
        model_ids=_gather_model_ids(
            kaine_config, eval_chat_model_id=eval_cfg.chat_model_id
        ),
        version=_kaine_version,
        # Reproducible perception-feed covariate — gathered at the boot layer
        # (allowed to touch kaine.modules) and passed in as data.
        perception_feed=gather_perception_feed_descriptor(kaine_config),
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
                "Refusing to boot KAINE cycle: insufficient GPU headroom.\n"
                + pf.message
                + "\n"
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
                lingua_cfg.get("chat_url", "http://127.0.0.1:11434/v1"),
                str(lingua_cfg.get("model_id") or ""),
                api_key=lingua_cfg.get("api_key")
                or os.environ.get("KAINE_MODEL_SERVER_API_KEY"),
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

    # Per-boot act-intent provenance secret (authenticate-intent-provenance,
    # Mechanism B). Generated HERE — the cycle composition root — and held ONLY
    # in this function's scope: it is never published to the bus, written to
    # disk, or logged. The SAME bytes are injected into Praxis (to verify, via
    # build_registry) and Volition (to sign, below), so an act intent forged by
    # any other bus writer fails verification and never reaches an effector.
    intent_secret = generate_intent_secret()

    registry = build_registry(bus, kaine_config, intent_secret=intent_secret)
    if not len(registry):
        log.warning(
            "no modules enabled in [modules]; cycle will run but never collect events"
        )

    for module in list(registry.all_modules()):
        await module.initialize()

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
    # The provider only needs refreshing when a real factor reads it. When both
    # factors are the static negative control the engine stays byte-identical to
    # the pre-change behavior (no affect observation at all).
    reads_affect = isinstance(thymos_modulator, StateModulator) or isinstance(
        goal_scorer, DriveRelevanceGoalScorer
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
    drive_initiative = bool(volition_cfg.get("drive_initiative", True))
    # Sign act intents with the per-boot secret so Praxis can verify their
    # provenance. run_id ties the signature to this run; the signer mints a
    # monotonic seq per intent so a captured signed intent cannot be replayed.
    intent_signer = IntentSigner(intent_secret, run_ctx.run_id)
    if drive_initiative:
        volition = Volition(
            policy=DriveBiasedActionSelectionPolicy(), signer=intent_signer
        )
    else:
        volition = Volition(signer=intent_signer)
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=registry,
        processing_rate_hz=float(cycle_cfg.get("processing_rate_hz", 10.0)),
        # Resting conscious-access (P3b) baseline; held below processing so the
        # senses outrun awareness. Arousal-modulated variability is future work.
        experiential_rate_hz=float(cycle_cfg.get("experiential_rate_hz", 3.333)),
        volition=volition,
        collect_phases=coherence_scorer is not None,
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
        # Deterministic mode (opt-in, [experiment].deterministic; default false).
        # When true the engine stamps events from a logical clock and the seed
        # A1 already pinned makes the run bit-for-bit reproducible. Production
        # leaves it false → real wall-clock time. Used by ablation experiments.
        deterministic=bool(experiment_cfg.get("deterministic", False)),
        # DI seam for the live salience factors: the engine refreshes the affect/
        # drive snapshot from each tick's thymos.state. None when both factors are
        # the static negative control (then the tick is byte-identical).
        affect_observer=affect_observer,
    )
    # Make a live MetricsCollector reachable by Nexus.
    _ = MetricsCollector(cycle, registry)

    # Spot module supervisor (cycle-layer component, not a registry module).
    spot_cfg = SpotConfig.from_section(kaine_config.get("spot") or {})
    fork_manager = ForkManager(Path("state/forks"))

    def rebuild_module(name: str) -> Any:
        """Rebuild a single module exactly as build_registry would, for Spot's
        heavy restart path. Hypnos re-fetches its siblings from the registry.

        A restarted cognitive module must keep timing on the SAME shared
        subjective clock the rest of the mind uses, so the one EntityClock on
        the registry is re-injected here exactly as build_registry injects it.
        """
        section = dict(kaine_config.get(name) or {})
        shared_clock = registry.entity_clock
        if name == "hypnos":
            mnemos = registry.get("mnemos") if "mnemos" in registry else None
            thymos = registry.get("thymos") if "thymos" in registry else None
            phantasia = (
                registry.get("phantasia") if "phantasia" in registry else None
            )
            return make_hypnos(
                bus,
                dict(kaine_config.get("hypnos") or {}),
                mnemos=mnemos,
                nous_process=None,
                thymos=thymos,
                phantasia=phantasia,
                kaine_config=kaine_config,
                entity_clock=shared_clock,
            )
        if name in CLOCKED_FACTORIES:
            return SIMPLE_FACTORIES[name](bus, section, entity_clock=shared_clock)
        if name == "praxis":
            # A restarted Praxis must keep verifying act-intent provenance, so
            # re-inject the same per-boot secret build_registry used. Without it
            # the fail-closed default would refuse every act intent post-restart.
            return SIMPLE_FACTORIES[name](bus, section, intent_secret=intent_secret)
        return SIMPLE_FACTORIES[name](bus, section)

    await _write_runtime_state(
        cycle, registry, supervision_mode=supervision_mode, gate_checks=gate_checks
    )

    # Optional evaluation sidecar. NO core module imports kaine.evaluation;
    # the cycle entrypoint is the single coupling point. eval_cfg was loaded at
    # the top of _boot_and_run (fail-closed before any resource opened).
    sidecar: SidecarRegistry | None = None
    research_active = (
        research_event_log_cfg.enabled or research_event_log_cfg.raw_archive.enabled
    )
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

    preservation_cfg = PreservationConfig.from_section(
        kaine_config.get("preservation") or {}
    )
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
        )

    cycle_task = asyncio.create_task(cycle.run_forever(), name="cycle.run_forever")
    freeze_task = asyncio.create_task(
        _freeze_watch_loop(cycle, stop_event), name="cycle.freeze_watch"
    )
    spot_task = (
        asyncio.create_task(spot.run(stop_event), name="cycle.spot")
        if spot_cfg.enabled
        else None
    )
    divergence_task = (
        asyncio.create_task(
            divergence_monitor.run(stop_event), name="cycle.divergence_monitor"
        )
        if divergence_monitor is not None
        else None
    )
    welfare_task = (
        asyncio.create_task(
            welfare_monitor.run(stop_event), name="cycle.welfare_monitor"
        )
        if welfare_monitor is not None
        else None
    )
    try:
        # Periodically update runtime.json so Nexus has fresh metrics
        # even before any tick happens.
        while not stop_event.is_set() and not cycle_task.done():
            await _write_runtime_state(
                cycle,
                registry,
                supervision_mode=supervision_mode,
                gate_checks=gate_checks,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
    finally:
        if not freeze_task.done():
            freeze_task.cancel()
        try:
            await freeze_task
        except (asyncio.CancelledError, Exception):
            pass
        if spot_task is not None:
            if not spot_task.done():
                spot_task.cancel()
            try:
                await spot_task
            except (asyncio.CancelledError, Exception):
                pass
        for monitor_task in (divergence_task, welfare_task):
            if monitor_task is None:
                continue
            if not monitor_task.done():
                monitor_task.cancel()
            try:
                await monitor_task
            except (asyncio.CancelledError, Exception):
                pass
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
    evaluation_on = bool((config.get("evaluation") or {}).get("enabled", False))
    rel = config.get("research_event_log") or {}
    rel_on = bool(rel.get("enabled", False)) or bool(
        (rel.get("raw_archive") or {}).get("enabled", False)
    )
    return evaluation_on or rel_on


def _evaluate_research_safety_net(config: dict[str, Any]) -> "Any":
    """Run the four-condition research gate over the resolved config.

    Reads the [preservation] toggles + the logging toggles, then performs the
    real dry preserve→revive self-check, and returns the combined GateResult.
    """
    from kaine.cycle.preservation_monitor import PreservationConfig
    from kaine.cycle.research_gate import (
        evaluate_research_gate,
        run_preflight_self_check,
    )

    preservation_cfg = PreservationConfig.from_section(config.get("preservation") or {})
    self_check_ok, self_check_reason = run_preflight_self_check()
    if not self_check_ok and self_check_reason:
        log.error("research-gate self-check failed: %s", self_check_reason)
    # require_encryption is enforced at the runtime write boundary (preserve_live
    # fails closed). The gate additionally refuses the boot up-front when
    # encryption is required but [security.state_encryption] is off, so the run
    # never starts with a net that cannot persist. The key-present half is
    # enforced separately by install_state_encryption (fail-closed at boot).
    encryption_enabled = bool(
        ((config.get("security") or {}).get("state_encryption") or {}).get(
            "enabled", False
        )
    )
    encryption_satisfied = (not preservation_cfg.require_encryption) or encryption_enabled
    return evaluate_research_gate(
        preservation_enabled=preservation_cfg.divergence_monitor.enabled,
        welfare_response_wired=preservation_cfg.welfare_response.enabled,
        logging_active=_research_logging_active(config),
        self_check_passed=self_check_ok,
        encryption_satisfied=encryption_satisfied,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from kaine.cycle.research_gate import (
        RESEARCH_GATE_EXIT_CODE,
        research_mode_requested,
    )

    # Load config early enough to decide the boot mode. A run is EITHER
    # operator-present OR research-safety-net-verified, never neither.
    try:
        config = _load_kaine_config()
    except Exception as exc:
        sys.stderr.write(f"Refusing to boot KAINE cycle: could not load config: {exc}\n")
        return 1

    # The gate is evaluated EXACTLY ONCE here (sync, before the event loop, so
    # the self-check's asyncio.run() does not nest) and threaded into
    # _boot_and_run for runtime.json — never recomputed inside the loop.
    supervision_mode = "operator"
    gate_checks: dict[str, bool] | None = None
    if research_mode_requested(config):
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

    try:
        return asyncio.run(
            _boot_and_run(
                supervision_mode=supervision_mode, gate_checks=gate_checks
            )
        )
    except KeyboardInterrupt:
        log.info("interrupted; shutdown complete")
        return 0


if __name__ == "__main__":
    sys.exit(main())
