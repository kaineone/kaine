# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Module wiring for KAINE's cycle entrypoint.

The factories map TOML keys to each module's constructor kwargs explicitly, and
unknown TOML keys raise at boot rather than being silently dropped.
`build_registry` walks the `[modules]` toggles and calls the right factory for
each enabled module. Hypnos depends on the Mnemos, Nous and Thymos instances, so
it is constructed in a second pass after the others are in the registry.

This package re-exports every name its submodules define, so callers keep
importing from ``kaine.boot``:

* ``errors``: configuration errors and the unknown-key guards.
* ``common``: the factory type and helpers every factory shares.
* ``factories``: one ``make_<module>`` factory per module; factories never import
  each other.
* ``perception_feed``: the stimulus feed and the womb-to-world transition.
* ``security``: state-encryption install.
* ``registry``: the factory tables and registry construction.
* ``wiring``: oscillators, coherence and salience, and cross-module wiring.
* ``metrics``: device-assignment logging and the metrics collector.
"""
from __future__ import annotations

from kaine.boot.common import (  # noqa: F401 - re-exported
    ModuleFactory,
    _check_injections,
    _effective_hot_swap_mode,
    shared_embedder,
)
from kaine.boot.errors import (  # noqa: F401 - re-exported
    ConfigurationError,
    VoiceAlignmentConfigError,
    _pop,
    _require_keys,
)
from kaine.boot.factories.audition import (  # noqa: F401 - re-exported
    _audition_sherpa_failure_reason,
    _live_mic_source_label,
    make_audition,
)
from kaine.boot.factories.chronos import (  # noqa: F401 - re-exported
    make_chronos,
)
from kaine.boot.factories.eidolon import (  # noqa: F401 - re-exported
    make_eidolon,
)
from kaine.boot.factories.empatheia import (  # noqa: F401 - re-exported
    make_empatheia,
)
from kaine.boot.factories.hypnos import (  # noqa: F401 - re-exported
    _make_organ_window_runner,
    _require_non_empty_abliteration_probes,
    _require_non_empty_capability_probes,
    _resolve_job_queue_trainer,
    _resolve_subprocess_trainer,
    _resolve_trainer,
    _validate_backend_pairing,
    make_hypnos,
    voice_alignment_config_from_section,
)
from kaine.boot.factories.lingua import (  # noqa: F401 - re-exported
    make_lingua,
)
from kaine.boot.factories.mnemos import (  # noqa: F401 - re-exported
    make_mnemos,
)
from kaine.boot.factories.mundus import (  # noqa: F401 - re-exported
    make_mundus,
)
from kaine.boot.factories.nous import (  # noqa: F401 - re-exported
    _NOUS_COMPLEXITY_THRESHOLD,
    make_nous,
)
from kaine.boot.factories.perception import (  # noqa: F401 - re-exported
    make_perception,
)
from kaine.boot.factories.phantasia import (  # noqa: F401 - re-exported
    make_phantasia,
)
from kaine.boot.factories.praxis import (  # noqa: F401 - re-exported
    make_praxis,
)
from kaine.boot.factories.soma import (  # noqa: F401 - re-exported
    make_soma,
)
from kaine.boot.factories.thymos import (  # noqa: F401 - re-exported
    make_thymos,
)
from kaine.boot.factories.topos import (  # noqa: F401 - re-exported
    make_topos,
)
from kaine.boot.factories.vox import (  # noqa: F401 - re-exported
    make_vox,
)
from kaine.boot.metrics import (  # noqa: F401 - re-exported
    _log_device_assignments,
)
from kaine.boot.perception_feed import (  # noqa: F401 - re-exported
    _TRANSITION_DEFAULT_AUDIO_FADE_SECONDS,
    _TRANSITION_DEFAULT_SECONDS,
    _build_monitor_audio_factory,
    _build_perception_feed_audio_factory,
    _build_perception_feed_video_factory,
    _build_screen_source_factory,
    _build_womb_world_transition,
    _install_shared_womb_clock,
    _install_womb_world_transition,
    _plan_womb_world_transition,
    _shared_womb_objects,
    _transition_event_publisher,
    _transition_perceived,
    _transition_setting,
    _womb_lived_offset,
    _womb_params,
    gather_perception_feed_descriptor,
)
from kaine.boot.registry import (  # noqa: F401 - re-exported
    _CLOCKED_FACTORIES,
    SIMPLE_FACTORIES,
    build_registry,
    construct_module,
    known_module_names,
    plugin_injections,
    rewire_module,
)
from kaine.boot.security import (  # noqa: F401 - re-exported
    install_state_encryption,
)
from kaine.boot.wiring import (  # noqa: F401 - re-exported
    _OSCILLATOR_ALLOWED_KEYS,
    _OSCILLATOR_MIN_PLV_WINDOW,
    _OSCILLATOR_MIN_POPULATION,
    _SALIENCE_GOAL_FACTOR_DEFAULT,
    _SALIENCE_THYMOS_FACTOR_DEFAULT,
    _SYNEIDESIS_ALLOWED_KEYS,
    _wire_eidolon_capabilities,
    _wire_lingua_organ_adapter,
    _wire_lingua_self_model,
    _wire_oscillators,
    _wire_self_hearing_gate,
    drive_sources_for,
    make_coherence_scorer,
    make_salience_factors,
    make_source_precision,
    oscillator_enabled,
)
