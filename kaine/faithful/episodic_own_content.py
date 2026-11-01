# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The event fields the episodic memory store keeps beyond ``INTERNAL_EVENT_TYPES``.

``INTERNAL_EVENT_TYPES`` (``kaine.faithful.external_input``) declares the types
whose whole payload holds only the entity's own values and words. It also feeds
the language module's prompt layout, so the episodic store does not widen it.
This module declares, for the episodic store only, further ``(source, type)``
pairs whose producers were audited field by field
(``openspec/changes/episodic-recall-content/design.md``, "Own-content audit").

Each audited pair has a field allowlist. The store keeps a field only when the
allowlist names it and its value passes the field's rule; every other field,
including one a producer adds later, is dropped. Free text is never allowed: a
string field must be one of a fixed set of values or match a short token
pattern with no spaces, so a heard sentence cannot pass even if a producer
started to copy one. The heard rule still runs first, so a member with a heard
field is stored as ``<heard omitted>`` whatever its type.

It also names fields of declared types that the store drops although the
language module renders their payload (``EPISODIC_DECLARED_FIELD_DENYLISTS``):
the playlist media file name and the speech events' ``faithful_rendering``.

Nothing in the language module reads this module, so the organ's prompt layout
(``layout_digest``) does not depend on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from kaine.faithful.external_input import INTERNAL_EVENT_TYPES


class FieldRule:
    """Decides whether one field value may be stored."""

    def admits(self, value: Any) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class Number(FieldRule):
    """An int or float (never a bool); ``None`` too when ``optional``."""

    optional: bool = False

    def admits(self, value: Any) -> bool:
        if value is None:
            return self.optional
        return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class Flag(FieldRule):
    """A bool."""

    def admits(self, value: Any) -> bool:
        return isinstance(value, bool)


@dataclass(frozen=True)
class OneOf(FieldRule):
    """One string out of a fixed set; ``None`` too when ``optional``."""

    values: frozenset[str]
    optional: bool = False

    def admits(self, value: Any) -> bool:
        if value is None:
            return self.optional
        return isinstance(value, str) and value in self.values


@dataclass(frozen=True)
class Matches(FieldRule):
    """A string that fully matches ``pattern``; ``None`` too when ``optional``."""

    pattern: re.Pattern[str]
    optional: bool = False

    def admits(self, value: Any) -> bool:
        if value is None:
            return self.optional
        return isinstance(value, str) and self.pattern.fullmatch(value) is not None


@dataclass(frozen=True)
class AnyOf(FieldRule):
    """A value that passes at least one of ``rules``."""

    rules: tuple[FieldRule, ...]

    def admits(self, value: Any) -> bool:
        return any(rule.admits(value) for rule in self.rules)


@dataclass(frozen=True)
class ListOf(FieldRule):
    """A list or tuple of at most ``max_len`` items, every item passing ``item``."""

    item: FieldRule
    max_len: int

    def admits(self, value: Any) -> bool:
        if not isinstance(value, (list, tuple)) or len(value) > self.max_len:
            return False
        return all(self.item.admits(v) for v in value)


@dataclass(frozen=True)
class MapOf(FieldRule):
    """A mapping whose every key is in ``keys`` and every value passes ``value``."""

    keys: frozenset[str]
    value: FieldRule

    def admits(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        return all(
            isinstance(k, str) and k in self.keys and self.value.admits(v)
            for k, v in value.items()
        )


# A short label from code or operator configuration: no spaces, no quotes.
TOKEN = Matches(re.compile(r"[A-Za-z0-9_.:\-]{1,64}"))

# The store's own trace ids: a uuid (hex or dashed), a backend integer id, or a
# short-term buffer slot.
MEMORY_ID = Matches(
    re.compile(
        r"[0-9a-f]{32}"
        r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        r"|[0-9]{1,20}"
        r"|short_term:[0-9]{1,20}"
    )
)

# Names of the cognitive modules (each module class's ``name``). A coalition
# member's source is one of these.
MODULE_SOURCES: frozenset[str] = frozenset(
    {
        "affect",
        "audition",
        "effectors",
        "embodiment",
        "episodic_memory",
        "interoception",
        "language",
        "perceptual_locus",
        "planning",
        "recorder",
        "self_model",
        "sequence",
        "sleep",
        "social_cognition",
        "vision",
        "vocal",
        "world_model",
    }
)
MODULE_SOURCE = OneOf(MODULE_SOURCES)

# kaine.modules.affect.appraisal.CategoricalEmotion values.
EMOTIONS: frozenset[str] = frozenset(
    {"joy", "sadness", "anger", "fear", "surprise", "disgust", "neutral"}
)

# kaine.modules.planning.generative_model: ACTION_SPACE and the state labels of
# the perceptual factors.
PLANNING_ACTIONS: frozenset[str] = frozenset(
    {"no_op", "request_think", "request_speak", "request_maintenance"}
)
PLANNING_STATE_LABELS: frozenset[str] = PLANNING_ACTIONS | frozenset(
    {
        "salience_low",
        "salience_medium",
        "salience_high",
        "affect_calm_pleasant",
        "affect_excited_pleasant",
        "affect_calm_unpleasant",
        "affect_excited_unpleasant",
        "cluster_other",
        "cluster_perception",
        "cluster_affect",
        "cluster_self",
    }
)
# kaine.modules.planning.module._state_label: a state without a label.
PLANNING_POSITIONAL_LABEL = Matches(re.compile(r"factor[0-9]{1,4}_state[0-9]{1,6}"))
# kaine.modules.planning.module._ACTION_TO_PROPOSAL_KIND values.
PROPOSAL_KINDS: frozenset[str] = frozenset({"think", "speak", "rest"})

# kaine.modules.interoception.regulation._ACTIONS.
INTEROCEPTION_ACTIONS: frozenset[str] = frozenset(
    {"reduce_rate", "shed_module", "request_maintenance"}
)

# kaine.perception_state.LOCI and the reasons evaluate_locus_switch returns.
LOCI: frozenset[str] = frozenset({"physical", "virtual", "off"})
LOCUS_DENIAL_REASONS: frozenset[str] = frozenset(
    {
        "invalid locus",
        "already in that locus",
        "locus locked by development gate",
        "locus locked by operator",
        "self-switch disabled by policy",
        "inhibited",
        "minimum dwell time not elapsed",
    }
)

# kaine.modules.effectors.effectors: the effector classes' names.
EFFECTOR_NAMES: frozenset[str] = frozenset({"notify", "file_write", "shell"})

# kaine.modules.embodiment.channels.CONTINUOUS_CHANNEL_RANGE keys.
EMBODIMENT_CHANNELS: frozenset[str] = frozenset(
    {"drive", "yaw_rate", "gaze_yaw", "gaze_pitch", "interact"}
)

# kaine.memory_kinds.EPISODIC_MEMORY_COLLECTION_KINDS.
MEMORY_COLLECTIONS: frozenset[str] = frozenset(
    {"short_term", "episodic", "semantic", "procedural"}
)

# kaine.modules.vocal: the synthesis backends and the prosody parameters they apply.
VOCAL_BACKENDS: frozenset[str] = frozenset({"chatterbox", "sherpa_onnx"})
VOCAL_PROSODY: frozenset[str] = frozenset(
    {"temperature", "exaggeration", "cfg_weight", "speed_factor"}
)
# Intent origins (kaine.workspace): the only producer sets "planning".
INTENT_ORIGINS: frozenset[str] = frozenset({"planning"})

# kaine.modules.world_model: backends, engines and the encoder layout version.
WORLD_MODEL_BACKENDS: frozenset[str] = frozenset({"fake", "dreamerv3"})
WORLD_MODEL_ENGINES: frozenset[str] = frozenset({"jax", "numpy"})
WORLD_MODEL_ENCODER_VERSIONS: frozenset[str] = frozenset({"world-model-encoder-v1"})

_N = Number()
_N_OPT = Number(optional=True)
_FLAG = Flag()

# The audit's result: every field listed here was traced to its producer and
# holds only numbers, flags, fixed values or code/config labels. A field the
# audit found able to carry outside words (an exception message, an error
# detail, a label copied from a request) is deliberately absent.
EPISODIC_FIELD_ALLOWLISTS: Mapping[tuple[str, str], Mapping[str, FieldRule]] = {
    ("affect", "affect.regulation"): {
        "tier": _N,
        "action": OneOf(
            frozenset({"attentional_deployment", "reappraisal", "request_maintenance"})
        ),
        "source": OneOf(MODULE_SOURCES, optional=True),
        "bias": _N,
        "decay_s": _N,
        "intensity": _N,
        "episode_s": _N,
        "size": _N,
        "emotion_before": OneOf(EMOTIONS),
        "emotion_after": OneOf(EMOTIONS),
    },
    ("effectors", "effectors.action"): {
        "effector": OneOf(EFFECTOR_NAMES),
        "success": _FLAG,
        "elapsed_ms": _N,
        "blocked": _FLAG,
        "provenance_rejected": _FLAG,
        "alert": _FLAG,
    },
    ("embodiment", "embodiment.efference"): {
        "channels": MapOf(EMBODIMENT_CHANNELS, _N),
        "forwarded": _FLAG,
    },
    ("episodic_memory", "episodic_memory.recall"): {
        "count": _N,
        "collection": OneOf(MEMORY_COLLECTIONS),
        "query_length": _N,
        "max_affect_intensity": _N,
        "error": _FLAG,
    },
    ("interoception", "interoception.warmup.started"): {
        "min_samples": _N,
        "min_seconds": _N,
        "samples_seen": _N,
        "lived_seconds": _N,
    },
    ("interoception", "interoception.warmup.completed"): {
        "samples_seen": _N,
        "lived_seconds": _N,
    },
    ("interoception", "interoception.regulation.withheld"): {
        "would_be_action": OneOf(INTEROCEPTION_ACTIONS),
        "prediction_error": _N,
        "sustain_elapsed_s": _N,
        "severity": _N_OPT,
        "reason": OneOf(frozenset({"warmup"})),
    },
    ("perceptual_locus", "perceptual_locus.changed"): {
        "locus": OneOf(LOCI),
        "by": OneOf(frozenset({"entity"})),
    },
    ("perceptual_locus", "perceptual_locus.denied"): {
        "requested": OneOf(LOCI),
        "reason": OneOf(LOCUS_DENIAL_REASONS),
    },
    ("planning", "planning.belief"): {
        "statement": AnyOf((OneOf(PLANNING_STATE_LABELS), PLANNING_POSITIONAL_LABEL)),
        "kind": OneOf(frozenset({"belief"})),
        "frequency": _N,
        "confidence": _N,
    },
    ("planning", "planning.policy"): {
        "policy": OneOf(PLANNING_ACTIONS),
        "expected_free_energy": _N,
        "horizon": _N,
        "param_info_gain": _FLAG,
    },
    ("planning", "planning.proposal"): {
        "proposal_id": Matches(re.compile(r"[0-9a-f]{32}")),
        "action": OneOf(PLANNING_ACTIONS),
        "kind": OneOf(PROPOSAL_KINDS),
        "step": _N,
        "preference": _N,
    },
    ("planning", "planning.error"): {
        "elapsed_ms": _N,
        "num_factors": _N,
        "num_actions": _N,
    },
    ("planning", "planning.timeout"): {
        "elapsed_ms": _N,
        "num_factors": _N,
        "num_actions": _N,
    },
    ("self_model", "self_model.drift"): {
        "score": _N,
        "recent_count": _N,
        "historical_count": _N,
        "reference_count": _N,
        "top_drifted_sources": ListOf(MODULE_SOURCE, max_len=len(MODULE_SOURCES)),
        "alert": _FLAG,
    },
    ("sleep", "sleep.association"): {
        "a": MEMORY_ID,
        "b": MEMORY_ID,
        "weight": _N,
    },
    ("sleep", "sleep.ignition_audit"): {
        "sleep_index": _N,
        "realized_total": _N,
        "input_triggered": _N,
        "drive_triggered": _N,
        "self_initiated": _N,
        "planning_initiated": _N,
        "unrealizable_planning_intents": _N,
        "realization_failed_count": _N,
        "planning_proposals_realized": _N,
        "planning_proposals_declined": _N,
        "planning_proposals_forwarded": _N,
    },
    ("social_cognition", "social_cognition.agent_model"): {
        "agent_id": TOKEN,
        "agent_label": TOKEN,
        "familiarity": _N,
        "reliability": _N,
        "interaction_count": _N,
        "source_label": TOKEN,
    },
    ("social_cognition", "social_cognition.social_error"): {
        "agent_id": TOKEN,
        "agent_label": TOKEN,
        "salience": _N,
        "deviation_magnitude": _N,
    },
    ("vocal", "vocal.synthesized"): {
        "text_length": _N,
        "bytes_produced": _N,
        "exaggeration": _N_OPT,
        "cfg_weight": _N_OPT,
        "temperature": _N_OPT,
        "speed_factor": _N_OPT,
        "latency_ms": _N,
        "success": _FLAG,
        "backend": OneOf(VOCAL_BACKENDS),
        "prosody_applied": ListOf(OneOf(VOCAL_PROSODY), max_len=len(VOCAL_PROSODY)),
        "origin": OneOf(INTENT_ORIGINS),
    },
    ("world_model", "world_model.world_error"): {
        "world_error": _N,
        "salience": _N,
        "tick_index": _N,
        "backend": OneOf(WORLD_MODEL_BACKENDS),
        "engine": OneOf(WORLD_MODEL_ENGINES, optional=True),
    },
    ("world_model", "world_model.scenario"): {
        "seed_memory_id": MEMORY_ID,
        "horizon": _N,
        "step_magnitudes": ListOf(_N, max_len=1024),
        "trajectory_drift": _N,
        "encoder_version": OneOf(WORLD_MODEL_ENCODER_VERSIONS),
        "backend": OneOf(WORLD_MODEL_BACKENDS),
        "engine": OneOf(WORLD_MODEL_ENGINES, optional=True),
    },
}

# Fields of ``INTERNAL_EVENT_TYPES`` pairs that the episodic store drops at any
# depth, although the language module renders the rest of the payload. The
# list is the store's alone, so the prompt layout does not change.
#
# * ``item``: the basename of the playlist media file (an operator-chosen file
#   name, often a film title). The entity perceives the film, not its file
#   name (the eyes-and-ears rule); ``item_order`` stays.
# * ``faithful_rendering`` on the entity's own speech: a rendering of the same
#   coalition the trace already holds as members. With the numeric awareness
#   rendering, the fallback template writes every field of an untemplated type
#   into it, ``audition.perception``'s ``item`` included.
EPISODIC_DECLARED_FIELD_DENYLISTS: Mapping[tuple[str, str], frozenset[str]] = {
    ("vision", "vision.report"): frozenset({"item"}),
    ("audition", "audition.perception"): frozenset({"item"}),
    ("language", "internal_speech"): frozenset({"faithful_rendering"}),
    ("language", "external_speech"): frozenset({"faithful_rendering"}),
}

# Every pair whose member the episodic store keeps with a payload: the stripped
# payload less its denied fields for ``INTERNAL_EVENT_TYPES``, the allowlisted
# fields for the audited pairs. Any other pair is stored as
# ``<unclassified omitted>``.
EPISODIC_OWN_CONTENT: frozenset[tuple[str, str]] = INTERNAL_EVENT_TYPES | frozenset(
    EPISODIC_FIELD_ALLOWLISTS
)


def _plain(value: Any) -> Any:
    """A copy of an admitted value with tuples as lists."""
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def allowlisted_payload(source: str, type_: str, payload: Any) -> dict[str, Any] | None:
    """The fields of an audited pair's payload that the store may keep.

    Returns ``None`` when ``(source, type_)`` has no field allowlist. Otherwise
    returns the payload's allowlisted fields whose values pass their rules, in
    payload order; every other field is dropped.
    """
    rules = EPISODIC_FIELD_ALLOWLISTS.get((source, type_))
    if rules is None:
        return None
    if not isinstance(payload, dict):
        return {}
    kept: dict[str, Any] = {}
    for key, value in payload.items():
        rule = rules.get(key) if isinstance(key, str) else None
        if rule is not None and rule.admits(value):
            kept[key] = _plain(value)
    return kept


def _without_keys(value: Any, keys: frozenset[str]) -> Any:
    """A copy of ``value`` with every mapping key in ``keys`` removed at any depth."""
    if isinstance(value, dict):
        return {k: _without_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, (list, tuple)):
        return [_without_keys(v, keys) for v in value]
    return value


def declared_payload(source: str, type_: str, payload: Any) -> Any:
    """The payload of an ``INTERNAL_EVENT_TYPES`` member as the store keeps it:
    without the fields ``EPISODIC_DECLARED_FIELD_DENYLISTS`` names for its pair."""
    denied = EPISODIC_DECLARED_FIELD_DENYLISTS.get((source, type_))
    if not denied:
        return payload
    return _without_keys(payload, denied)
