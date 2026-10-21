# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Canonical bus stream names.

Pure module: it imports only ``kaine.bus.schema``. Every value matches the
stream its producer writes today; this module names streams, it does not
change any producer. A module's output stream is ``module_stream(<name>)``,
that is ``<name>.out``.
"""

from __future__ import annotations

from kaine.bus.schema import WORKSPACE_STREAM, module_stream

# --- Workspace, cycle and action selection --------------------------------

# WORKSPACE_STREAM (imported above) is the broadcast, written by the workspace.
#: Tick, rate and time-scale events from the cycle engine.
CYCLE_STREAM = "cycle.out"
#: Intents chosen by the action selection module.
ACTION_SELECTION_STREAM = module_stream("action_selection")
#: Outcomes reported back to the action selection module by the effectors module.
ACTION_SELECTION_FEEDBACK_STREAM = "action_selection_feedback.out"

# --- The language module's speech channels ---------------------------------------------

#: Speech addressed to the world (the vocal module reads it).
LANGUAGE_EXTERNAL_STREAM = "language.external"
#: Inner speech (the self-model module reads it; the vocal module never does).
LANGUAGE_INTERNAL_STREAM = "language.internal"

# --- Module output streams (one per module under kaine/modules/) ----------

AUDITION_STREAM = module_stream("audition")
SEQUENCE_STREAM = module_stream("sequence")
RECORDER_STREAM = module_stream("recorder")
SELF_MODEL_STREAM = module_stream("self_model")
SOCIAL_COGNITION_STREAM = module_stream("social_cognition")
SLEEP_STREAM = module_stream("sleep")
#: The language module's aggregate stream: a copy of every utterance on either channel.
LANGUAGE_STREAM = module_stream("language")
EPISODIC_MEMORY_STREAM = module_stream("episodic_memory")
EMBODIMENT_STREAM = module_stream("embodiment")
PLANNING_STREAM = module_stream("planning")
PERCEPTUAL_LOCUS_STREAM = module_stream("perceptual_locus")
WORLD_MODEL_STREAM = module_stream("world_model")
EFFECTORS_STREAM = module_stream("effectors")
INTEROCEPTION_STREAM = module_stream("interoception")
AFFECT_STREAM = module_stream("affect")
VISION_STREAM = module_stream("vision")
VOCAL_STREAM = module_stream("vocal")

# --- Cycle-layer and lifecycle producers -----------------------------------

#: The stimulus source rhythm, readiness readouts and presence, written during the developmental phase.
DEVELOPMENT_STREAM = "development.out"
#: The developmental owner's bus source. It is derived from the stream so the two
#: always agree; the stored stage value of the same spelling is a different name.
DEVELOPMENT_SOURCE = DEVELOPMENT_STREAM.removesuffix(".out")

#: Awake-floor operator events (kaine.cycle.housekeeping_floor); not a module stream, so nothing published there enters the workspace.
HOUSEKEEPING_STREAM = "housekeeping.out"
#: The housekeeping floor's bus source. Derived from the stream so the two always agree.
HOUSEKEEPING_SOURCE = HOUSEKEEPING_STREAM.removesuffix(".out")

#: The perception feed's own bus source and stream (stimulus-source-to-world
#: transition outcomes). It is distinct from the perceptual locus module's stream,
#: so each has its own cap and the rename never folds one onto the other.
PERCEPTION_FEED_SOURCE = "perception_feed"
PERCEPTION_FEED_STREAM = module_stream(PERCEPTION_FEED_SOURCE)
#: Individuation divergence verdicts (kaine.cycle.individuation_runtime).
INDIVIDUATION_STREAM = module_stream("individuation")
#: Developmental-stage transitions (kaine.lifecycle.maturation_gate).
LIFECYCLE_STREAM = module_stream("lifecycle")
#: Preservation events from the divergence and welfare monitors.
PRESERVATION_STREAM = module_stream("preservation")
#: The supervisor module-supervisor incidents (kaine.cycle.supervisor).
SUPERVISOR_STREAM = module_stream("supervisor")
#: Welfare-protective responses (kaine.cycle.preservation_monitor).
WELFARE_STREAM = module_stream("welfare")

MODULE_STREAMS: frozenset[str] = frozenset(
    {
        AUDITION_STREAM,
        SEQUENCE_STREAM,
        RECORDER_STREAM,
        SELF_MODEL_STREAM,
        SOCIAL_COGNITION_STREAM,
        SLEEP_STREAM,
        LANGUAGE_STREAM,
        EPISODIC_MEMORY_STREAM,
        EMBODIMENT_STREAM,
        PLANNING_STREAM,
        PERCEPTUAL_LOCUS_STREAM,
        WORLD_MODEL_STREAM,
        EFFECTORS_STREAM,
        INTEROCEPTION_STREAM,
        AFFECT_STREAM,
        VISION_STREAM,
        VOCAL_STREAM,
    }
)

KNOWN_STREAMS: frozenset[str] = MODULE_STREAMS | frozenset(
    {
        WORKSPACE_STREAM,
        CYCLE_STREAM,
        ACTION_SELECTION_STREAM,
        ACTION_SELECTION_FEEDBACK_STREAM,
        LANGUAGE_EXTERNAL_STREAM,
        LANGUAGE_INTERNAL_STREAM,
        DEVELOPMENT_STREAM,
        HOUSEKEEPING_STREAM,
        PERCEPTION_FEED_STREAM,
        INDIVIDUATION_STREAM,
        LIFECYCLE_STREAM,
        PRESERVATION_STREAM,
        SUPERVISOR_STREAM,
        WELFARE_STREAM,
    }
)

__all__ = [
    "AUDITION_STREAM",
    "SEQUENCE_STREAM",
    "CYCLE_STREAM",
    "RECORDER_STREAM",
    "SELF_MODEL_STREAM",
    "SOCIAL_COGNITION_STREAM",
    "DEVELOPMENT_STREAM",
    "DEVELOPMENT_SOURCE",
    "HOUSEKEEPING_STREAM",
    "HOUSEKEEPING_SOURCE",
    "PERCEPTION_FEED_SOURCE",
    "PERCEPTION_FEED_STREAM",
    "SLEEP_STREAM",
    "INDIVIDUATION_STREAM",
    "KNOWN_STREAMS",
    "LIFECYCLE_STREAM",
    "LANGUAGE_EXTERNAL_STREAM",
    "LANGUAGE_INTERNAL_STREAM",
    "LANGUAGE_STREAM",
    "EPISODIC_MEMORY_STREAM",
    "MODULE_STREAMS",
    "EMBODIMENT_STREAM",
    "PLANNING_STREAM",
    "PERCEPTUAL_LOCUS_STREAM",
    "WORLD_MODEL_STREAM",
    "EFFECTORS_STREAM",
    "PRESERVATION_STREAM",
    "INTEROCEPTION_STREAM",
    "SUPERVISOR_STREAM",
    "AFFECT_STREAM",
    "VISION_STREAM",
    "ACTION_SELECTION_FEEDBACK_STREAM",
    "ACTION_SELECTION_STREAM",
    "VOCAL_STREAM",
    "WELFARE_STREAM",
    "WORKSPACE_STREAM",
]
