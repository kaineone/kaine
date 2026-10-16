# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Oscillators, the coherence scorer and salience factors, and the cross-module wiring the cycle applies after the registry is built."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from kaine.boot.common import _effective_hot_swap_mode
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.defaults import language_section_api_key
from kaine.modules.registry import ModuleRegistry
from kaine.storage import resolve
from kaine.workspace.regulation_bias import RegulationBias
from kaine.workspace.strategies import build_drive_sources, dominant_drive

#: Label of the affect salience factor in downgrade reports.
AFFECT_FACTOR_LABEL = "affect_modulation"

log = logging.getLogger(__name__)


# Allowed keys for the workspace-level [oscillator] section (oscillatory-layer).
_OSCILLATOR_ALLOWED_KEYS: set[str] = {
    "enabled",
    "population_size",
    "plv_window",
    "coherence_floor",
    "coherence_ceiling",
    "beta",
    "threshold",
    "base_drive",
}

# Spec minimums for the oscillatory-binding layer.
_OSCILLATOR_MIN_POPULATION = 16
_OSCILLATOR_MIN_PLV_WINDOW = 10


def oscillator_enabled(kaine_config: dict[str, Any]) -> bool:
    """Whether the oscillatory-binding layer is enabled in config."""
    section = kaine_config.get("oscillator") or {}
    return bool(section.get("enabled", False))


def make_coherence_scorer(kaine_config: dict[str, Any]):
    """Build a `CoherenceScorer` from the [oscillator] section, or ``None`` when
    the layer is disabled. Validates keys and the spec minimums."""
    from kaine.workspace.coherence import CoherenceScorer

    section = dict(kaine_config.get("oscillator") or {})
    _require_keys(section, _OSCILLATOR_ALLOWED_KEYS)
    if not bool(section.get("enabled", False)):
        return None
    plv_window = int(section.get("plv_window", _OSCILLATOR_MIN_PLV_WINDOW))
    population_size = int(section.get("population_size", _OSCILLATOR_MIN_POPULATION))
    if population_size < _OSCILLATOR_MIN_POPULATION:
        raise ConfigurationError(
            f"[oscillator].population_size must be >= {_OSCILLATOR_MIN_POPULATION}"
        )
    if plv_window < _OSCILLATOR_MIN_PLV_WINDOW:
        raise ConfigurationError(f"[oscillator].plv_window must be >= {_OSCILLATOR_MIN_PLV_WINDOW}")
    floor = float(section.get("coherence_floor", 0.8))
    ceiling = float(section.get("coherence_ceiling", 1.25))
    return CoherenceScorer(
        plv_window=plv_window,
        coherence_floor=floor,
        coherence_ceiling=ceiling,
    )


# Allowed keys for the [workspace] section (workspace selection + the live
# four-factor salience source selectors). A typo (e.g. `salience_goal_factors`)
# must fail loudly rather than silently leave the goal factor on its default.
_WORKSPACE_ALLOWED_KEYS: set[str] = {
    "top_k",
    "publication_threshold",
    "novelty_window",
    "salience_affect_factor",
    "salience_goal_factor",
    "arousal_contrast_gain",
    "arm",  # the arm of the planned test, read by the cycle
    "regulation_bias",  # emotion regulation's tier-1 selection bias gate (paper §3.5); false in every study arm
}

# Shipped default source per salience factor (wire-salience-goal-thymos, STAGED
# rollout). The affect module factor ships LIVE (the real, tested StateModulator); the
# goal factor ships on the static baseline pending validation. A factor "warns"
# only when the operator selects "static" for a factor whose default is REAL —
# i.e. a deliberate downgrade — so flipping the goal default to "drive_relevance"
# later would automatically make goal="static" a warned downgrade.
_SALIENCE_AFFECT_FACTOR_DEFAULT = "state_modulator"
_SALIENCE_GOAL_FACTOR_DEFAULT = "static"


def drive_sources_for(registry: ModuleRegistry) -> dict[str, frozenset[str]]:
    """Build the goal factor's drive table from the registered modules' declarations."""
    return build_drive_sources({m.name: m.relieves_drives for m in registry.all_modules()})


def make_salience_factors(
    kaine_config: dict[str, Any],
    affect_provider: Any,
    *,
    drive_sources: Mapping[str, frozenset[str]] | None = None,
):
    """Select the goal + the affect module's salience factors from the [workspace] section.

    Returns ``(affect_modulator, goal_scorer, downgraded_factors)``. Both real
    factors read the entity's current affect/drives through ``affect_provider``
    (dependency injection — the workspace layer never imports ``kaine.modules``).
    ``downgraded_factors`` names each factor the operator deliberately set to the
    static negative control *when that factor ships real by default*, so
    :class:`RuleBasedSalience` warns on a genuine downgrade only (never on the
    staged goal default). Validates the section's keys and the selected values.
    """
    from kaine.modules.affect.modulator import StateModulator
    from kaine.workspace import (
        DriveRelevanceGoalScorer,
        StaticAffectModulator,
        StaticGoalScorer,
    )

    section = dict(kaine_config.get("workspace") or {})
    _require_keys(section, _WORKSPACE_ALLOWED_KEYS)

    affect_factor = str(section.get("salience_affect_factor", _SALIENCE_AFFECT_FACTOR_DEFAULT))
    goal_factor = str(section.get("salience_goal_factor", _SALIENCE_GOAL_FACTOR_DEFAULT))

    if affect_factor == "state_modulator":
        arousal_contrast_gain = float(section.get("arousal_contrast_gain", 8.0))
        if arousal_contrast_gain < 0.0:
            raise ConfigurationError(
                "[workspace].arousal_contrast_gain must be >= 0"
            )
        baseline_arousal = float(
            (kaine_config.get("affect") or {}).get("baseline_arousal", 0.3)
        )
        affect_modulator = StateModulator(
            affect_provider.dimensional_state,
            contrast_gain_max=arousal_contrast_gain,
            baseline_arousal=baseline_arousal,
        )
    elif affect_factor == "static":
        affect_modulator = StaticAffectModulator()
    else:
        raise ConfigurationError(
            "unknown [workspace].salience_affect_factor "
            f"{affect_factor!r} (expected 'state_modulator' or 'static')"
        )

    if goal_factor == "drive_relevance":
        if drive_sources is None:
            raise ConfigurationError(
                "drive_relevance needs the registered modules' drive declarations"
            )
        goal_scorer = DriveRelevanceGoalScorer(
            affect_provider.drive_values, drive_sources=drive_sources
        )
    elif goal_factor == "static":
        goal_scorer = StaticGoalScorer()
    else:
        raise ConfigurationError(
            "unknown [workspace].salience_goal_factor "
            f"{goal_factor!r} (expected 'drive_relevance' or 'static')"
        )

    # A factor is a deliberate downgrade when it is static but ships real.
    downgraded_factors: list[str] = []
    if affect_factor == "static" and _SALIENCE_AFFECT_FACTOR_DEFAULT != "static":
        downgraded_factors.append(f"{AFFECT_FACTOR_LABEL} (set to static)")
    if goal_factor == "static" and _SALIENCE_GOAL_FACTOR_DEFAULT != "static":
        downgraded_factors.append("goal_relevance (set to static)")

    # Honest, non-alarming note that the goal factor is on its staged static
    # baseline (the intended shipped state, not an operator downgrade).
    if goal_factor == "static" and _SALIENCE_GOAL_FACTOR_DEFAULT == "static":
        log.info(
            "salience goal factor is on the staged static baseline "
            "(set [workspace].salience_goal_factor = 'drive_relevance' to activate "
            "the drive-relevance scorer once validated)"
        )

    return affect_modulator, goal_scorer, downgraded_factors


def make_regulation_bias(
    kaine_config: Mapping[str, Any],
    clock: Callable[[], float],
) -> Optional[RegulationBias]:
    """Build the tier-1 emotion regulation bias gate, or ``None`` when disabled.

    The default is enabled (``True``) so a normal boot gets the gate; study
    arms explicitly set it ``False`` to keep the ranking invariant of paper A.1.
    """
    section = dict(kaine_config.get("workspace") or {})
    enabled = section.get("regulation_bias", True)
    if not isinstance(enabled, bool):
        raise ConfigurationError("[workspace].regulation_bias must be true or false")
    if not enabled:
        return None
    return RegulationBias(clock)


def _wire_oscillators(registry: ModuleRegistry, kaine_config: dict[str, Any]) -> None:
    """Attach a live `ModuleOscillator` to every registered module when the
    oscillatory-binding layer is enabled. No-op when disabled. Plugin-declared
    oscillators are attached first and do not require snnTorch; remaining
    modules receive the default oscillator only when snnTorch is available.
    When snnTorch is absent, those modules keep reporting the neutral phase
    (graceful degradation)."""
    section = dict(kaine_config.get("oscillator") or {})
    if not bool(section.get("enabled", False)):
        return
    from kaine.oscillator import make_oscillator, snntorch_available

    population_size = int(section.get("population_size", _OSCILLATOR_MIN_POPULATION))
    plv_window = int(section.get("plv_window", _OSCILLATOR_MIN_PLV_WINDOW))
    beta = float(section.get("beta", 0.9))
    threshold = float(section.get("threshold", 1.0))
    base_drive = float(section.get("base_drive", 1.5))
    defaults = {
        "population_size": population_size,
        "plv_window": plv_window,
        "beta": beta,
        "threshold": threshold,
        "base_drive": base_drive,
    }
    # Plugin oscillators are attached before the snnTorch check so that a
    # plugin can provide an oscillator without the snnTorch dependency.
    plugins = getattr(registry, "plugins", None)
    plugin_modules: set[str] = set()
    if plugins:
        for module in list(registry.all_modules()):
            if plugins.declares_oscillator(module.name):
                if not hasattr(module, "attach_oscillator"):
                    # A declared seam is never dropped silently.
                    raise ConfigurationError(
                        f"a plugin declares oscillator.{module.name} but module "
                        f"{module.name} cannot take an oscillator"
                    )
                osc = plugins.oscillator_for(module.name, defaults)
                module.attach_oscillator(osc)
                plugin_modules.add(module.name)
                log.info("attached plugin oscillator to module %s", module.name)

    if not snntorch_available():
        log.warning(
            "[oscillator].enabled is true but snnTorch is unavailable; modules "
            "without a plugin oscillator report the neutral phase and the "
            "coherence factor degrades to 1.0 "
            "(install the [oscillator] extra to activate)"
        )
        return
    for module in list(registry.all_modules()):
        if module.name in plugin_modules:
            continue
        osc = make_oscillator(
            population_size=population_size,
            plv_window=plv_window,
            beta=beta,
            threshold=threshold,
            base_drive=base_drive,
        )
        if osc is not None and hasattr(module, "attach_oscillator"):
            module.attach_oscillator(osc)
            log.info("attached oscillator to module %s", module.name)


def _wire_language_self_model(registry: ModuleRegistry) -> None:
    """Confirm the language module seeds its persona from the *bus-mediated* self-model module's
    self-model snapshot rather than an in-process self-model module reference.

    Previously this injected a live ``self_model.model`` accessor into the language module — a
    direct boot-time Python reference that pinned the two modules into one
    process. That reference is the coupling the ``distributed-deployment``
    change removes: the self-model module now publishes its self-model to ``self_model.out`` and
    The language module caches it via its own ``_self_model_cache_loop`` (over the shared
    authenticated bus), so the language organ can run in a separate process /
    on a separate trusted GPU host. This helper therefore no longer wires an
    object handle; it stays as the documented seam (and a boot log) so the
    single-host default is unchanged and the decoupling is explicit.

    The sleep module → the episodic memory / planning / affect modules remains an in-process reference (the next
    decoupling target — see docs/07-deployment/README.md); only the read-only
    The language module → the self-model module accessor is bus-mediated here.
    """
    if "language" not in registry or "self_model" not in registry:
        return
    log.info("language persona seeded from bus-mediated self_model.self_model snapshot")


def _wire_language_organ_adapter(
    registry: ModuleRegistry,
    kaine_config: dict[str, Any] | None,
) -> None:
    """Wire the language module's per-request organ adapter resolver when voice alignment
    uses the organ_adapter hot-swap mode and the organ is a KAINE-managed
    llama-server container.
    """
    if kaine_config is None:
        return
    if "language" not in registry or "sleep" not in registry:
        return

    sleep_cfg = kaine_config.get("sleep", {})
    voice_cfg = sleep_cfg.get("voice_alignment", {}) if sleep_cfg else {}
    if not voice_cfg.get("enabled"):
        return

    mode = voice_cfg.get("hot_swap_mode", "manual")
    if _effective_hot_swap_mode(mode, kaine_config) != "organ_adapter":
        return

    language_cfg = kaine_config.get("language", {})
    organ_url = voice_cfg.get("organ_url") or language_cfg.get("chat_url")
    if not organ_url:
        log.warning(
            "organ_adapter hot-swap configured but neither organ_url nor "
            "language.chat_url is set; skipping per-request LoRA wiring"
        )
        return

    adapter_output_dir = resolve(
        voice_cfg.get("adapter_output_dir", "state/sleep/adapters")
    )
    organ_adapters_dir = Path(
        voice_cfg.get("organ_adapters_dir", "/organ-adapters")
    )
    api_key = language_section_api_key(language_cfg)

    from kaine.modules.sleep.organ_adapter import OrganAdapterResolver, organ_root_url

    resolver = OrganAdapterResolver(
        adapter_output_dir=adapter_output_dir,
        volume=organ_adapters_dir,
        organ_url=organ_root_url(organ_url),
        api_key=api_key,
    )
    registry.get("language").set_lora_resolver(resolver)
    log.info(
        "language applies its own voice-alignment adapter when the organ has it loaded"
    )


def _wire_self_model_capabilities(registry: ModuleRegistry) -> None:
    """Inject the effectors module's effector whitelist into the self-model module's self-inference engine
    so the self-model's ``capability_map`` reflects what the entity can execute
    (the ``eidolon-self-inference`` "Capability map from Effectors whitelist"
    requirement). No-op unless both modules are present. Idempotent: the whitelist
    is fixed for the boot, so re-running (e.g. after a supervisor rebuild) is safe."""
    if "effectors" not in registry or "self_model" not in registry:
        return
    effectors = registry.get("effectors")
    self_model = registry.get("self_model")
    engine = getattr(self_model, "self_inference", None)
    if engine is None or not hasattr(engine, "set_whitelist_commands"):
        return
    effector_names = sorted(getattr(effectors, "enabled_effectors", ()) or ())
    engine.set_whitelist_commands(effector_names)
    log.info("wired self-model capability whitelist from effectors (%d effectors)", len(effector_names))


def _wire_affect_drive_relevance(registry: ModuleRegistry) -> None:
    """Give the affect module the drive-to-source table its goal-significance check scores
    against: the same table the salience goal factor builds from each registered
    module's ``relieves_drives`` declaration, with the dominant-drive rule handed
    in so the affect module never imports the workspace. Re-run by ``rewire_module`` so a
    restarted affect module, or a restarted module that changes the table, is re-wired."""
    if "affect" not in registry:
        return
    affect = registry.get("affect")
    affect.set_drive_relevance(drive_sources_for(registry), dominant_drive)
    log.info("wired affect goal significance to the drive-to-source table")


def _wire_affect_development(
    registry: ModuleRegistry,
    probe: Optional[Callable[[], bool]] = None,
) -> None:
    """Store and wire the affect module's developmental-phase probe.

    The affect module's emotion regulation is off during the developmental
    phase (paper §3.5); the probe returns True while the entity is developing.
    A supervisor rebuild re-runs this helper without a probe and reuses the
    stored one.
    """
    if probe is not None:
        setattr(registry, "affect_development_probe", probe)
    stored = getattr(registry, "affect_development_probe", None)
    if "affect" in registry and stored is not None:
        affect = registry.get("affect")
        setter = getattr(affect, "set_development_probe", None)
        if callable(setter):
            setter(stored)
            log.info("wired affect development probe")


def _wire_self_hearing_gate(registry: ModuleRegistry) -> None:
    """Share one SpeakingGate between the vocal and audition modules so the entity does
    not transcribe its own spoken output. No-op unless both modules are
    enabled. Whether the gate is ever *opened* is controlled by the vocal module's
    `suppress_self_hearing` flag, so an isolated-headset operator can stay
    full-duplex by setting it false.

    Reuses an existing gate already installed on either side so a supervisor rebuild
    of one module does not replace the live gate and leave the old instance
    wired to the other side.
    """
    if "vocal" not in registry or "audition" not in registry:
        return
    from kaine.modules.vocal.coordination import SpeakingGate

    vocal = registry.get("vocal")
    audition = registry.get("audition")
    # Reuse an existing gate if one side already has one; otherwise create a
    # fresh shared gate. This makes rewire_module idempotent and preserves the
    # gate object across supervisor rebuilds.
    gate: Optional[Any] = None
    if hasattr(vocal, "_speaking_gate") and vocal._speaking_gate is not None:
        gate = vocal._speaking_gate
    elif hasattr(audition, "_speaking_gate") and audition._speaking_gate is not None:
        gate = audition._speaking_gate
    if gate is None:
        gate = SpeakingGate()
    if hasattr(vocal, "set_speaking_gate"):
        vocal.set_speaking_gate(gate)
    if hasattr(audition, "set_speaking_gate"):
        audition.set_speaking_gate(gate)
    log.info("wired self-hearing gate between vocal and audition")
