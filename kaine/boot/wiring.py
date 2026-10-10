# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Oscillators, the coherence scorer and salience factors, and the cross-module wiring the cycle applies after the registry is built."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Optional

from kaine.boot.common import _effective_hot_swap_mode
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.defaults import lingua_section_api_key
from kaine.modules.registry import ModuleRegistry
from kaine.storage import resolve
from kaine.workspace.strategies import build_drive_sources, dominant_drive

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


# Allowed keys for the [syneidesis] section (workspace selection + the live
# four-factor salience source selectors). A typo (e.g. `salience_goal_factors`)
# must fail loudly rather than silently leave the goal factor on its default.
_SYNEIDESIS_ALLOWED_KEYS: set[str] = {
    "top_k",
    "publication_threshold",
    "novelty_window",
    "salience_thymos_factor",
    "salience_goal_factor",
    "arousal_contrast_gain",
}

# Shipped default source per salience factor (wire-salience-goal-thymos, STAGED
# rollout). The Thymos factor ships LIVE (the real, tested StateModulator); the
# goal factor ships on the static baseline pending validation. A factor "warns"
# only when the operator selects "static" for a factor whose default is REAL —
# i.e. a deliberate downgrade — so flipping the goal default to "drive_relevance"
# later would automatically make goal="static" a warned downgrade.
_SALIENCE_THYMOS_FACTOR_DEFAULT = "state_modulator"
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
    """Select the goal + Thymos salience factors from the [syneidesis] section.

    Returns ``(thymos_modulator, goal_scorer, downgraded_factors)``. Both real
    factors read the entity's current affect/drives through ``affect_provider``
    (dependency injection — the workspace layer never imports ``kaine.modules``).
    ``downgraded_factors`` names each factor the operator deliberately set to the
    static negative control *when that factor ships real by default*, so
    :class:`RuleBasedSalience` warns on a genuine downgrade only (never on the
    staged goal default). Validates the section's keys and the selected values.
    """
    from kaine.modules.thymos.modulator import StateModulator
    from kaine.workspace import (
        DriveRelevanceGoalScorer,
        StaticGoalScorer,
        StaticThymosModulator,
    )

    section = dict(kaine_config.get("syneidesis") or {})
    _require_keys(section, _SYNEIDESIS_ALLOWED_KEYS)

    thymos_factor = str(section.get("salience_thymos_factor", _SALIENCE_THYMOS_FACTOR_DEFAULT))
    goal_factor = str(section.get("salience_goal_factor", _SALIENCE_GOAL_FACTOR_DEFAULT))

    if thymos_factor == "state_modulator":
        arousal_contrast_gain = float(section.get("arousal_contrast_gain", 8.0))
        if arousal_contrast_gain < 0.0:
            raise ConfigurationError(
                "[syneidesis].arousal_contrast_gain must be >= 0"
            )
        baseline_arousal = float(
            (kaine_config.get("thymos") or {}).get("baseline_arousal", 0.3)
        )
        thymos_modulator = StateModulator(
            affect_provider.dimensional_state,
            contrast_gain_max=arousal_contrast_gain,
            baseline_arousal=baseline_arousal,
        )
    elif thymos_factor == "static":
        thymos_modulator = StaticThymosModulator()
    else:
        raise ConfigurationError(
            "unknown [syneidesis].salience_thymos_factor "
            f"{thymos_factor!r} (expected 'state_modulator' or 'static')"
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
            "unknown [syneidesis].salience_goal_factor "
            f"{goal_factor!r} (expected 'drive_relevance' or 'static')"
        )

    # A factor is a deliberate downgrade when it is static but ships real.
    downgraded_factors: list[str] = []
    if thymos_factor == "static" and _SALIENCE_THYMOS_FACTOR_DEFAULT != "static":
        downgraded_factors.append("thymos_modulation (set to static)")
    if goal_factor == "static" and _SALIENCE_GOAL_FACTOR_DEFAULT != "static":
        downgraded_factors.append("goal_relevance (set to static)")

    # Honest, non-alarming note that the goal factor is on its staged static
    # baseline (the intended shipped state, not an operator downgrade).
    if goal_factor == "static" and _SALIENCE_GOAL_FACTOR_DEFAULT == "static":
        log.info(
            "salience goal factor is on the staged static baseline "
            "(set [syneidesis].salience_goal_factor = 'drive_relevance' to activate "
            "the drive-relevance scorer once validated)"
        )

    return thymos_modulator, goal_scorer, downgraded_factors

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


def _wire_lingua_self_model(registry: ModuleRegistry) -> None:
    """Confirm Lingua seeds its persona from the *bus-mediated* Eidolon
    self-model snapshot rather than an in-process Eidolon reference.

    Previously this injected a live ``eidolon.model`` accessor into Lingua — a
    direct boot-time Python reference that pinned the two modules into one
    process. That reference is the coupling the ``distributed-deployment``
    change removes: Eidolon now publishes its self-model to ``eidolon.out`` and
    Lingua caches it via its own ``_self_model_cache_loop`` (over the shared
    authenticated bus), so the language organ can run in a separate process /
    on a separate trusted GPU host. This helper therefore no longer wires an
    object handle; it stays as the documented seam (and a boot log) so the
    single-host default is unchanged and the decoupling is explicit.

    Hypnos→Mnemos/Nous/Thymos remains an in-process reference (the next
    decoupling target — see docs/07-deployment/README.md); only the read-only
    Lingua→Eidolon accessor is bus-mediated here.
    """
    if "lingua" not in registry or "eidolon" not in registry:
        return
    log.info("lingua persona seeded from bus-mediated eidolon.self_model snapshot")


def _wire_lingua_organ_adapter(
    registry: ModuleRegistry,
    kaine_config: dict[str, Any] | None,
) -> None:
    """Wire Lingua's per-request organ adapter resolver when voice alignment
    uses the organ_adapter hot-swap mode and the organ is a KAINE-managed
    llama-server container.
    """
    if kaine_config is None:
        return
    if "lingua" not in registry or "hypnos" not in registry:
        return

    hypnos_cfg = kaine_config.get("hypnos", {})
    voice_cfg = hypnos_cfg.get("voice_alignment", {}) if hypnos_cfg else {}
    if not voice_cfg.get("enabled"):
        return

    mode = voice_cfg.get("hot_swap_mode", "manual")
    if _effective_hot_swap_mode(mode, kaine_config) != "organ_adapter":
        return

    lingua_cfg = kaine_config.get("lingua", {})
    organ_url = voice_cfg.get("organ_url") or lingua_cfg.get("chat_url")
    if not organ_url:
        log.warning(
            "organ_adapter hot-swap configured but neither organ_url nor "
            "lingua.chat_url is set; skipping per-request LoRA wiring"
        )
        return

    adapter_output_dir = resolve(
        voice_cfg.get("adapter_output_dir", "state/hypnos/adapters")
    )
    organ_adapters_dir = Path(
        voice_cfg.get("organ_adapters_dir", "/organ-adapters")
    )
    api_key = lingua_section_api_key(lingua_cfg)

    from kaine.modules.hypnos.organ_adapter import OrganAdapterResolver, organ_root_url

    resolver = OrganAdapterResolver(
        adapter_output_dir=adapter_output_dir,
        volume=organ_adapters_dir,
        organ_url=organ_root_url(organ_url),
        api_key=api_key,
    )
    registry.get("lingua").set_lora_resolver(resolver)
    log.info(
        "lingua applies its own voice-alignment adapter when the organ has it loaded"
    )


def _wire_eidolon_capabilities(registry: ModuleRegistry) -> None:
    """Inject the Praxis effector whitelist into Eidolon's self-inference engine
    so the self-model's ``capability_map`` reflects what the entity can execute
    (the ``eidolon-self-inference`` "Capability map from Praxis whitelist"
    requirement). No-op unless both modules are present. Idempotent: the whitelist
    is fixed for the boot, so re-running (e.g. after a Spot rebuild) is safe."""
    if "praxis" not in registry or "eidolon" not in registry:
        return
    praxis = registry.get("praxis")
    eidolon = registry.get("eidolon")
    engine = getattr(eidolon, "self_inference", None)
    if engine is None or not hasattr(engine, "set_whitelist_commands"):
        return
    effectors = sorted(getattr(praxis, "enabled_effectors", ()) or ())
    engine.set_whitelist_commands(effectors)
    log.info("wired eidolon capability whitelist from praxis (%d effectors)", len(effectors))


def _wire_thymos_drive_relevance(registry: ModuleRegistry) -> None:
    """Give Thymos the drive-to-source table its goal-significance check scores
    against: the same table the salience goal factor builds from each registered
    module's ``relieves_drives`` declaration, with the dominant-drive rule handed
    in so Thymos never imports the workspace. Re-run by ``rewire_module`` so a
    restarted Thymos, or a restarted module that changes the table, is re-wired."""
    if "thymos" not in registry:
        return
    thymos = registry.get("thymos")
    thymos.set_drive_relevance(drive_sources_for(registry), dominant_drive)
    log.info("wired thymos goal significance to the drive-to-source table")


def _wire_self_hearing_gate(registry: ModuleRegistry) -> None:
    """Share one SpeakingGate between vox and audition so the entity does
    not transcribe its own spoken output. No-op unless both modules are
    enabled. Whether the gate is ever *opened* is controlled by vox's
    `suppress_self_hearing` flag, so an isolated-headset operator can stay
    full-duplex by setting it false.

    Reuses an existing gate already installed on either side so a Spot rebuild
    of one module does not replace the live gate and leave the old instance
    wired to the other side.
    """
    if "vox" not in registry or "audition" not in registry:
        return
    from kaine.modules.vox.coordination import SpeakingGate

    vox = registry.get("vox")
    audition = registry.get("audition")
    # Reuse an existing gate if one side already has one; otherwise create a
    # fresh shared gate. This makes rewire_module idempotent and preserves the
    # gate object across Spot rebuilds.
    gate: Optional[Any] = None
    if hasattr(vox, "_speaking_gate") and vox._speaking_gate is not None:
        gate = vox._speaking_gate
    elif hasattr(audition, "_speaking_gate") and audition._speaking_gate is not None:
        gate = audition._speaking_gate
    if gate is None:
        gate = SpeakingGate()
    if hasattr(vox, "set_speaking_gate"):
        vox.set_speaking_gate(gate)
    if hasattr(audition, "set_speaking_gate"):
        audition.set_speaking_gate(gate)
    log.info("wired self-hearing gate between vox and audition")
