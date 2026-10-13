# SPDX-License-Identifier: LicenseRef-CAL-0.4
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
ACTION_SELECTION_STREAM = module_stream("volition")
#: Outcomes reported back to the action selection module by the effectors module.
ACTION_SELECTION_FEEDBACK_STREAM = "volition_feedback.out"

# --- The language module's speech channels ---------------------------------------------

#: Speech addressed to the world (the vocal module reads it).
LANGUAGE_EXTERNAL_STREAM = "lingua.external"
#: Inner speech (the self-model module reads it; the vocal module never does).
LANGUAGE_INTERNAL_STREAM = "lingua.internal"

# --- Module output streams (one per module under kaine/modules/) ----------

AUDITION_STREAM = module_stream("audition")
SEQUENCE_STREAM = module_stream("chronos")
RECORDER_STREAM = module_stream("echo")
SELF_MODEL_STREAM = module_stream("eidolon")
SOCIAL_COGNITION_STREAM = module_stream("empatheia")
SLEEP_STREAM = module_stream("hypnos")
#: The language module's aggregate stream: a copy of every utterance on either channel.
LANGUAGE_STREAM = module_stream("lingua")
EPISODIC_MEMORY_STREAM = module_stream("mnemos")
EMBODIMENT_STREAM = module_stream("mundus")
PLANNING_STREAM = module_stream("nous")
PERCEPTUAL_LOCUS_STREAM = module_stream("perception")
WORLD_MODEL_STREAM = module_stream("phantasia")
EFFECTORS_STREAM = module_stream("praxis")
INTEROCEPTION_STREAM = module_stream("soma")
AFFECT_STREAM = module_stream("thymos")
VISION_STREAM = module_stream("topos")
VOCAL_STREAM = module_stream("vox")

# --- Cycle-layer and lifecycle producers -----------------------------------

#: The stimulus source rhythm, readiness readouts and presence, written during the developmental phase.
DEVELOPMENT_STREAM = "gestation.out"
#: The developmental owner's bus source. It is derived from the stream so the two
#: always agree; the stored stage value of the same spelling is a different name.
DEVELOPMENT_SOURCE = DEVELOPMENT_STREAM.removesuffix(".out")

#: The perception feed's own bus source and stream (stimulus-source-to-world
#: transition outcomes). Before the keys step this is also the perceptual locus
#: module's stream; after it the two differ.
PERCEPTION_FEED_SOURCE = "perception"
PERCEPTION_FEED_STREAM = module_stream(PERCEPTION_FEED_SOURCE)
#: Individuation divergence verdicts (kaine.cycle.individuation_runtime).
INDIVIDUATION_STREAM = module_stream("individuation")
#: Developmental-stage transitions (kaine.lifecycle.maturation_gate).
LIFECYCLE_STREAM = module_stream("lifecycle")
#: Preservation events from the divergence and welfare monitors.
PRESERVATION_STREAM = module_stream("preservation")
#: The supervisor module-supervisor incidents (kaine.cycle.supervisor).
SUPERVISOR_STREAM = module_stream("spot")
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
