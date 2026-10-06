# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The factory tables and registry construction: build, construct and rewire modules."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.common import ModuleFactory, shared_embedder
from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.audition import make_audition
from kaine.boot.factories.chronos import make_chronos
from kaine.boot.factories.eidolon import make_eidolon
from kaine.boot.factories.empatheia import make_empatheia
from kaine.boot.factories.hypnos import make_hypnos
from kaine.boot.factories.lingua import make_lingua
from kaine.boot.factories.mnemos import make_mnemos
from kaine.boot.factories.mundus import make_mundus
from kaine.boot.factories.nous import make_nous
from kaine.boot.factories.perception import make_perception
from kaine.boot.factories.phantasia import make_phantasia
from kaine.boot.factories.praxis import make_praxis
from kaine.boot.factories.soma import make_soma
from kaine.boot.factories.thymos import make_thymos
from kaine.boot.factories.topos import make_topos
from kaine.boot.factories.vox import make_vox
from kaine.boot.metrics import _log_device_assignments
from kaine.boot.perception_feed import _install_shared_womb_clock, _install_womb_world_transition
from kaine.boot.security import install_state_encryption
from kaine.boot.wiring import (
    _wire_eidolon_capabilities,
    _wire_lingua_organ_adapter,
    _wire_lingua_self_model,
    _wire_oscillators,
    _wire_self_hearing_gate,
)
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry

log = logging.getLogger(__name__)


SIMPLE_FACTORIES: dict[str, ModuleFactory] = {
    "soma": make_soma,
    "chronos": make_chronos,
    "topos": make_topos,
    "nous": make_nous,
    "mnemos": make_mnemos,
    "eidolon": make_eidolon,
    "thymos": make_thymos,
    "praxis": make_praxis,
    "lingua": make_lingua,
    "audition": make_audition,
    "vox": make_vox,
    "mundus": make_mundus,
    "perception": make_perception,
    "empatheia": make_empatheia,
    "phantasia": make_phantasia,
}


# Factories for modules that time a COGNITIVE process and therefore take the
# shared subjective EntityClock (biological-timing-and-dilation Phase 2). The
# clock dilates their integrals/cadences coherently with the cycle's tick
# pacing. Every other module is purely event-driven (paces off the subjective
# cycle already) or times only infrastructure, so it gets no clock.
_CLOCKED_FACTORIES: frozenset[str] = frozenset({"soma", "topos", "mnemos", "thymos", "perception", "chronos", "vox"})


def plugin_injections(plugins: Any, name: str) -> Optional[dict[str, Any]]:
    """The constructor injections the loaded plugins supply for module ``name``
    (``None`` when no plugins are loaded or the module has no plugin seams)."""
    if not plugins:
        return None
    from kaine.plugins import INJECTABLE_SEAMS

    if name not in INJECTABLE_SEAMS:
        return None
    return plugins.injections_for(name) or None


def known_module_names() -> list[str]:
    """Every module name boot can construct (for validating oscillator seams)."""
    return [*SIMPLE_FACTORIES, "hypnos"]


def build_registry(
    bus: AsyncBus,
    kaine_config: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
    intent_secret: Optional[bytes] = None,
    plugins: Any = None,
    boot_stage: Any | None = None,
) -> ModuleRegistry:
    """Construct every enabled module from kaine.toml and register it.

    Builds (or receives) the ONE shared ``EntityClock`` for this boot from
    ``[cycle].time_scale`` and injects the SAME instance into every cognitive
    module plus onto the registry. The cycle entrypoint reads
    ``registry.entity_clock`` back and hands it to the ``CognitiveCycle``, so the
    tick pacing and the modules' cognitive timers all dilate off one
    ``time_scale`` — no two cognitive clocks ever desynchronize. At the shipped
    default ``time_scale = 1.0`` the clock reads real elapsed time, so behavior
    is identical to before this wiring.
    """
    install_state_encryption(kaine_config)
    toggles = kaine_config.get("modules") or {}

    from kaine.extras import check, format_missing

    missing = check(kaine_config)
    errors = [m for m in missing if m.severity == "error"]
    if errors:
        raise ConfigurationError(format_missing(missing))
    for m in missing:
        log.warning(
            "Module %s needs %r (extra %r) but it is not installed; "
            "degrading gracefully.",
            m.module,
            m.import_name,
            m.extra,
        )

    registry = ModuleRegistry()
    # One shared subjective clock for the whole mind. Built here from
    # [cycle].time_scale (default 1.0 = real-time) unless the caller already
    # constructed one, so build_registry and the cycle can share a single
    # instance regardless of construction order.
    if entity_clock is None:
        time_scale = float((kaine_config.get("cycle") or {}).get("time_scale", 1.0))
        entity_clock = EntityClock(scale=time_scale)
    registry.entity_clock = entity_clock
    # Loaded module plugins (kaine.plugins); Spot's restart path and the
    # oscillator wiring read them back from the registry.
    registry.plugins = plugins
    # The unified perception feed is a single top-level [perception_feed] section
    # (unified-perception-feed) that parameterizes BOTH the vision surface
    # (Topos) and the hearing surface (Audition) from one source of truth. Read
    # it once and inject it into both factories' sections under a reserved key
    # the factories pop. Keeping it top-level (not under [topos]/[audition])
    # means picture and sound cannot drift to different seeds/manifests.
    perception_feed = dict(kaine_config.get("perception_feed") or {})
    # A configured deterministic feed (seeded/playlist) is the entity's VIRTUAL
    # world, so booting with one selected must bind the senses to it: select the
    # `virtual` locus and mark both modalities desired. Without this the locus-
    # gated capture supervisors keep the virtual feed dark (the shipped desired-
    # state defaults to locus=`physical`, flags off) and Topos/Audition publish
    # nothing — the "awake but senseless" failure. mode off/live leave the
    # desired-state to the operator (live = real camera/mic, operator-toggled).
    _feed_mode = str(perception_feed.get("mode", "off")).lower()
    _womb_world_transition = None
    # Playlist real-time A/V sync (playlist-realtime-av-sync): the video and audio
    # playlist feeds must share ONE start-clock so they present the same manifest
    # item at the same wall-clock moment and cross item boundaries together. Build
    # it once here from the manifest's item count and inject the SAME instance
    # into both the Topos (video) and Audition (audio) factory sections, so
    # picture and sound cannot drift onto different items. Any manifest problem is
    # left for the factories to surface with their existing errors.
    if _feed_mode == "playlist" and (
        bool(toggles.get("topos", False)) or bool(toggles.get("audition", False))
    ):
        try:
            from kaine.modules.topos.feed import (
                PlaylistClock,
                load_playlist_manifest,
            )

            _manifest_path = str(perception_feed.get("playlist_manifest", "")).strip()
            if _manifest_path:
                _pl_manifest = load_playlist_manifest(_manifest_path)
                _pl_clock = PlaylistClock(len(_pl_manifest.items))
                perception_feed["_shared_playlist_clock"] = _pl_clock
                # Also stash the clock in the config section itself so the
                # Hypnos factory (which reads kaine_config, not this local
                # copy) can inject the SAME instance — sleep pauses playback
                # via the clock at the perception suspend/restore seam
                # (playlist-sleep-pause). No new bus/event channel: the
                # injected-clock pattern is the established mechanism.
                if kaine_config is not None:
                    kaine_config.setdefault("perception_feed", {})
                    kaine_config["perception_feed"]["_shared_playlist_clock"] = _pl_clock
        except Exception:
            log.warning(
                "could not build the shared playlist clock; feeds fall back to "
                "private clocks (video/audio may drift)",
                exc_info=True,
            )
        # Womb-to-world transition (womb-to-world-transition): a born being's
        # viewing opens with a crossfade from the womb's last field to the
        # programme's first frame. Building it pauses the shared clock under
        # `transition` before any surface reads, so programme time zero is the
        # end of the crossfade. When the conditions do not hold, boot logs why
        # and the programme starts as before.
        if perception_feed.get("_shared_playlist_clock") is not None:
            _womb_world_transition = _install_womb_world_transition(
                perception_feed,
                kaine_config,
                perception_feed["_shared_playlist_clock"],
                stage_state=boot_stage,
                bus=bus,
                video_present=bool(toggles.get("topos", False)),
            )
    # Womb (local-womb-feed): one shared womb clock for both surfaces, offset by
    # the lived gestation time, so the heartbeat is seen and heard together and
    # the maternal trajectory continues across boots instead of replaying.
    if _feed_mode == "womb" and (
        bool(toggles.get("topos", False)) or bool(toggles.get("audition", False))
    ):
        _install_shared_womb_clock(
            perception_feed, kaine_config, entity_clock, stage_state=boot_stage
        )
    if _feed_mode in ("seeded", "playlist", "womb") and (
        bool(toggles.get("topos", False)) or bool(toggles.get("audition", False))
    ):
        from kaine import perception_state as _ps

        _desired = _ps.select_virtual_feed()
        if _desired.locus != "virtual":
            log.warning(
                "perception feed mode=%s configured but locus is locked to %s; "
                "the virtual feed will not deliver until the operator unlocks it",
                _feed_mode,
                _desired.locus,
            )
        else:
            log.info(
                "perception feed mode=%s -> locus=virtual audio=%s video=%s",
                _feed_mode,
                _desired.audio_live_desired,
                _desired.video_live_desired,
            )
    # Topos and Audition read the shared feed (and the playlist clock stashed
    # into kaine_config above) inside construct_module, so boot and Spot's
    # restart path hand them the same instance.
    for name in SIMPLE_FACTORIES:
        if not bool(toggles.get(name, False)):
            continue
        module = construct_module(
            name,
            bus,
            kaine_config,
            registry=registry,
            entity_clock=entity_clock,
            intent_secret=intent_secret,
            injections=plugin_injections(plugins, name),
        )
        if module is None:
            log.warning(
                "module %s not registered: its configured backend could not load (see the health surface)",
                name,
            )
            continue
        registry.register(module)
        log.info("registered module %s", name)
    if _womb_world_transition is not None:
        # The video surface starts and judges the crossfade only if Topos is
        # really there; without it the audio surface does, so a Topos whose
        # backend could not load never leaves the programme held.
        _womb_world_transition.controller.set_video_present("topos" in registry)

    if bool(toggles.get("hypnos", False)):
        # construct_module hands Hypnos its sibling modules from the registry.
        # Nous is now a pymdp/JAX active-inference engine with no NAR subprocess,
        # so there is no process for Hypnos's belief-revision phase to step;
        # that phase skips cleanly when nous_process is None.
        hypnos = construct_module(
            "hypnos",
            bus,
            kaine_config,
            registry=registry,
            entity_clock=entity_clock,
        )
        registry.register(hypnos)
        log.info("registered module hypnos")
    _wire_self_hearing_gate(registry)
    _wire_lingua_self_model(registry)
    _wire_lingua_organ_adapter(registry, kaine_config)
    _wire_eidolon_capabilities(registry)
    _log_device_assignments(registry, kaine_config)
    _wire_oscillators(registry, kaine_config)
    return registry


def construct_module(
    name: str,
    bus: AsyncBus,
    kaine_config: dict[str, Any],
    *,
    registry: ModuleRegistry,
    entity_clock: Optional[EntityClock] = None,
    intent_secret: Optional[bytes] = None,
    injections: Optional[Mapping[str, Any]] = None,
) -> Optional[BaseModule]:
    """Construct a single module exactly as `build_registry` would.

    Copies the module's section from ``kaine_config``, wires the shared
    perception feed for Topos/Audition/Soma, injects ``entity_clock`` into
    clocked factories, injects ``intent_secret`` into Praxis, and dispatches
    plugin injections to Chronos, Soma, Nous and Audition.

    Returns ``None`` when the module's factory returns ``None`` — i.e. its
    configured backend could not load. The caller is responsible for skipping
    registration and surfacing the reason.
    """
    if name not in SIMPLE_FACTORIES and name != "hypnos":
        raise ConfigurationError(f"unknown module {name!r}")

    if injections and name not in {"chronos", "soma", "nous", "audition"}:
        raise ConfigurationError(
            f"module {name!r} does not accept injections"
        )

    section = dict(kaine_config.get(name) or {})
    if name in ("topos", "audition", "soma"):
        section["perception_feed"] = dict(kaine_config.get("perception_feed") or {})

    if name in ("mnemos", "empatheia"):
        section["_embedder"] = shared_embedder(registry, kaine_config)

    if name == "hypnos":
        mnemos = registry.get("mnemos") if "mnemos" in registry else None
        thymos = registry.get("thymos") if "thymos" in registry else None
        phantasia = registry.get("phantasia") if "phantasia" in registry else None
        return make_hypnos(
            bus,
            section,
            mnemos=mnemos,
            nous_process=None,
            thymos=thymos,
            phantasia=phantasia,
            kaine_config=kaine_config,
            entity_clock=entity_clock,
            embedder=shared_embedder(registry, kaine_config),
        )

    factory = SIMPLE_FACTORIES[name]
    if name in _CLOCKED_FACTORIES:
        if name in {"chronos", "soma", "nous"}:
            return factory(
                bus, section, entity_clock=entity_clock, injections=injections
            )
        return factory(bus, section, entity_clock=entity_clock)
    if name == "praxis":
        return factory(bus, section, intent_secret=intent_secret)
    if name in {"chronos", "soma", "nous"}:
        return factory(bus, section, injections=injections)
    if name == "audition":
        return factory(bus, section, injections=injections)
    return factory(bus, section)


def rewire_module(registry: ModuleRegistry, name: str, kaine_config: dict[str, Any]) -> None:
    """Re-run the post-registration wiring after Spot rebuilds ``name``.

    Spot's heavy restart path constructs a fresh module and swaps it into the
    registry via ``replace``; the new instance must be re-wired exactly as
    ``build_registry`` wires the full set, except for oscillators (below). The individual wirings are idempotent
    and cheap, so we re-run the global helpers rather than scoping to one
    module (the ``name`` argument documents intent and lets a future
    optimization narrow the work without changing callers).

    Oscillators are deliberately NOT rebuilt here: Spot hands the rebuilt
    module its predecessor's oscillator, and every other module keeps its own,
    so no module's phase history is reset by another module's restart
    (oscillator-continuity-on-restart).
    """
    _wire_self_hearing_gate(registry)
    _wire_lingua_self_model(registry)
    _wire_lingua_organ_adapter(registry, kaine_config)
    _wire_eidolon_capabilities(registry)
