# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Module wiring for KAINE's cycle entrypoint.

The factories map TOML keys to each module's constructor kwargs explicitly, and
unknown TOML keys raise at boot rather than being silently dropped.
`build_registry` walks the `[modules]` toggles and calls the right factory for
each enabled module. The sleep module depends on the episodic memory, planning and affect modules' instances, so
it is constructed in a second pass after the others are in the registry.

This package re-exports every name its submodules define, so callers keep
importing from ``kaine.boot``:

* ``errors``: configuration errors and the unknown-key guards.
* ``common``: the factory type and helpers every factory shares.
* ``factories``: one ``make_<module>`` factory per module; factories never import
  each other.
* ``perception_feed``: the stimulus feed and the stimulus-source-to-world transition.
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
from kaine.boot.factories.affect import (  # noqa: F401 - re-exported
    make_affect,
)
from kaine.boot.factories.audition import (  # noqa: F401 - re-exported
    _audition_sherpa_failure_reason,
    _live_mic_source_label,
    make_audition,
)
from kaine.boot.factories.effectors import (  # noqa: F401 - re-exported
    make_effectors,
)
from kaine.boot.factories.embodiment import (  # noqa: F401 - re-exported
    make_embodiment,
)
from kaine.boot.factories.episodic_memory import (  # noqa: F401 - re-exported
    make_episodic_memory,
)
from kaine.boot.factories.interoception import (  # noqa: F401 - re-exported
    make_interoception,
)
from kaine.boot.factories.language import (  # noqa: F401 - re-exported
    make_language,
)
from kaine.boot.factories.perceptual_locus import (  # noqa: F401 - re-exported
    make_perceptual_locus,
)
from kaine.boot.factories.planning import (  # noqa: F401 - re-exported
    _PLANNING_COMPLEXITY_THRESHOLD,
    make_planning,
)
from kaine.boot.factories.self_model import (  # noqa: F401 - re-exported
    make_self_model,
)
from kaine.boot.factories.sequence import (  # noqa: F401 - re-exported
    make_sequence,
)
from kaine.boot.factories.sleep import (  # noqa: F401 - re-exported
    _make_organ_window_runner,
    _require_non_empty_abliteration_probes,
    _require_non_empty_capability_probes,
    _resolve_job_queue_trainer,
    _resolve_subprocess_trainer,
    _resolve_trainer,
    _validate_backend_pairing,
    make_sleep,
    voice_alignment_config_from_section,
)
from kaine.boot.factories.social_cognition import (  # noqa: F401 - re-exported
    make_social_cognition,
)
from kaine.boot.factories.vision import (  # noqa: F401 - re-exported
    make_vision,
)
from kaine.boot.factories.vocal import (  # noqa: F401 - re-exported
    make_vocal,
)
from kaine.boot.factories.world_model import (  # noqa: F401 - re-exported
    make_world_model,
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
    _build_stimulus_source_world_transition,
    _install_shared_stimulus_source_clock,
    _install_stimulus_source_world_transition,
    _plan_stimulus_source_world_transition,
    _shared_stimulus_source_objects,
    _stimulus_source_lived_offset,
    _stimulus_source_params,
    _transition_event_publisher,
    _transition_perceived,
    _transition_setting,
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
    _SALIENCE_AFFECT_FACTOR_DEFAULT,
    _SALIENCE_GOAL_FACTOR_DEFAULT,
    _WORKSPACE_ALLOWED_KEYS,
    _wire_language_organ_adapter,
    _wire_language_self_model,
    _wire_oscillators,
    _wire_self_hearing_gate,
    _wire_self_model_capabilities,
    drive_sources_for,
    make_coherence_scorer,
    make_salience_factors,
    oscillator_enabled,
)
