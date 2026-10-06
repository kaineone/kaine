# SPDX-License-Identifier: LicenseRef-CAL-0.2
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

#: The conscious broadcast, written by Syneidesis.
WORKSPACE_STREAM = WORKSPACE_STREAM
#: Tick, rate and time-scale events from the cycle engine.
CYCLE_STREAM = "cycle.out"
#: Intents chosen by Volition.
VOLITION_STREAM = module_stream("volition")
#: Outcomes reported back to Volition by the effectors.
VOLITION_FEEDBACK_STREAM = "volition_feedback.out"

# --- Lingua's speech channels ---------------------------------------------

#: Speech addressed to the world (Vox reads it).
LINGUA_EXTERNAL_STREAM = "lingua.external"
#: Inner speech (Eidolon reads it; Vox never does).
LINGUA_INTERNAL_STREAM = "lingua.internal"

# --- Module output streams (one per module under kaine/modules/) ----------

AUDITION_STREAM = module_stream("audition")
CHRONOS_STREAM = module_stream("chronos")
ECHO_STREAM = module_stream("echo")
EIDOLON_STREAM = module_stream("eidolon")
EMPATHEIA_STREAM = module_stream("empatheia")
HYPNOS_STREAM = module_stream("hypnos")
#: Lingua's aggregate stream: a copy of every utterance on either channel.
LINGUA_STREAM = module_stream("lingua")
MNEMOS_STREAM = module_stream("mnemos")
MUNDUS_STREAM = module_stream("mundus")
NOUS_STREAM = module_stream("nous")
PERCEPTION_STREAM = module_stream("perception")
PHANTASIA_STREAM = module_stream("phantasia")
PRAXIS_STREAM = module_stream("praxis")
SOMA_STREAM = module_stream("soma")
THYMOS_STREAM = module_stream("thymos")
TOPOS_STREAM = module_stream("topos")
VOX_STREAM = module_stream("vox")

# --- Cycle-layer and lifecycle producers -----------------------------------

#: The womb rhythm, readiness readouts and presence, written during gestation.
GESTATION_STREAM = module_stream("gestation")
#: Individuation divergence verdicts (kaine.cycle.individuation_runtime).
INDIVIDUATION_STREAM = module_stream("individuation")
#: Developmental-stage transitions (kaine.lifecycle.maturation_gate).
LIFECYCLE_STREAM = module_stream("lifecycle")
#: Preservation events from the divergence and welfare monitors.
PRESERVATION_STREAM = module_stream("preservation")
#: Spot module-supervisor incidents (kaine.cycle.spot).
SPOT_STREAM = module_stream("spot")
#: Welfare-protective responses (kaine.cycle.preservation_monitor).
WELFARE_STREAM = module_stream("welfare")

MODULE_STREAMS: frozenset[str] = frozenset(
    {
        AUDITION_STREAM,
        CHRONOS_STREAM,
        ECHO_STREAM,
        EIDOLON_STREAM,
        EMPATHEIA_STREAM,
        HYPNOS_STREAM,
        LINGUA_STREAM,
        MNEMOS_STREAM,
        MUNDUS_STREAM,
        NOUS_STREAM,
        PERCEPTION_STREAM,
        PHANTASIA_STREAM,
        PRAXIS_STREAM,
        SOMA_STREAM,
        THYMOS_STREAM,
        TOPOS_STREAM,
        VOX_STREAM,
    }
)

KNOWN_STREAMS: frozenset[str] = MODULE_STREAMS | frozenset(
    {
        WORKSPACE_STREAM,
        CYCLE_STREAM,
        VOLITION_STREAM,
        VOLITION_FEEDBACK_STREAM,
        LINGUA_EXTERNAL_STREAM,
        LINGUA_INTERNAL_STREAM,
        GESTATION_STREAM,
        INDIVIDUATION_STREAM,
        LIFECYCLE_STREAM,
        PRESERVATION_STREAM,
        SPOT_STREAM,
        WELFARE_STREAM,
    }
)
