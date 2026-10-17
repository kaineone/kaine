# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic per-(source, type) templates.

Every template is a pure callable taking a payload dict and returning a
plain-text line. No hedging, no filler, no self-reference. The renderer
falls back to `fallback_template` for any unregistered key.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

from kaine.faithful.external_input import EXTERNAL_INPUT_TYPES

TemplateFn = Callable[[dict[str, Any]], str]

STRONG_DRIVE_BAND = 0.8

FELT_DRIVE_PHRASES: dict[str, tuple[str, str]] = {
    "social_drive": (
        "I feel a pull towards company.",
        "I feel a strong pull towards company.",
    ),
    "curiosity": (
        "I feel curious.",
        "I feel a strong urge to know more.",
    ),
    "boredom": (
        "I feel bored.",
        "I feel heavily bored.",
    ),
    "restlessness": (
        "I feel restless.",
        "I feel very restless.",
    ),
}


def felt_drive_phrase(drive: str, value: object) -> str:
    """The felt-state phrase for a drive crossing: the strong phrase when
    ``value`` is a finite number at or above ``STRONG_DRIVE_BAND``, otherwise
    the moderate one. It names the felt state, never what to say, and never
    contains a number."""
    moderate, strong = FELT_DRIVE_PHRASES.get(drive, (None, None))
    if moderate is None:
        return "I feel a pull I cannot name."
    if isinstance(value, bool):
        return moderate
    if isinstance(value, (int, float)):
        try:
            f = float(value)
            if math.isfinite(f) and f >= STRONG_DRIVE_BAND:
                return strong
        except (OverflowError, ValueError):
            pass
    return moderate


HEARD_SPEECH_PLACEHOLDER = "[heard speech]"

HEARD_TEXT_FIELDS = frozenset({
    "text",
    "user_input",
    "user_text",
    "transcription",
    "heard_text",
    "faithful_rendering",
})
"""Field names that may contain heard speech.
`text` is treated as heard speech only for `audition.transcription`; for every
other event type it is not. `faithful_rendering` is included because a rendering
can embed earlier heard lines.

External-input event types (``audition.transcription`` and ``embodiment.chat``) are
redacted wholesale by type; on all other types, these fields are redacted at
any depth.
"""


def _replace_text_leaves(value):
    if isinstance(value, str):
        return HEARD_SPEECH_PLACEHOLDER if value.strip() else value
    if isinstance(value, dict):
        return {k: _replace_text_leaves(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_text_leaves(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_replace_text_leaves(v) for v in value)
    return value


def _redact_fields(value, fields_to_redact):
    replaced = False

    def walk(node):
        nonlocal replaced
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in fields_to_redact:
                    if isinstance(v, str) and v.strip():
                        out[k] = HEARD_SPEECH_PLACEHOLDER
                        replaced = True
                    elif isinstance(v, (dict, list, tuple)):
                        redacted = _replace_text_leaves(v)
                        out[k] = redacted
                        if redacted != v:
                            replaced = True
                    else:
                        out[k] = v
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, tuple):
            return tuple(walk(item) for item in node)
        return node

    return walk(value), replaced


def redact_heard_speech(event) -> Optional[str]:
    """Return a rendering of an event with any heard-speech payload field
    replaced by the placeholder, or None when the event carries no heard speech.
    """
    if event.type == "audition.transcription":
        return f'Speech heard: "{HEARD_SPEECH_PLACEHOLDER}".'

    payload = event.payload if isinstance(event.payload, dict) else {}

    if event.type in EXTERNAL_INPUT_TYPES:
        redacted_payload = _replace_text_leaves(payload)
        return fallback_template(event.source, event.type, redacted_payload)

    heard_fields = HEARD_TEXT_FIELDS - {"text"}
    redacted_payload, has_heard = _redact_fields(payload, heard_fields)
    if not has_heard:
        return None

    template_fn = TEMPLATES.get((event.source, event.type))
    if template_fn is None:
        return fallback_template(event.source, event.type, redacted_payload)
    return template_fn(redacted_payload)


DEFAULT_EMPTY_SNAPSHOT_TEXT: str = "(no events selected)"


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        # Trim trailing zeros without using scientific notation
        if value == int(value):
            return f"{int(value)}"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "none"
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(v) for v in value) if value else "none"
    return str(value)


def _t_interoception_report(payload: dict[str, Any]) -> str:
    wellness = payload.get("wellness")
    alerts = payload.get("alerts") or []
    prediction_error = payload.get("prediction_error")
    fatigue_value = payload.get("fatigue_value")
    parts = []
    if alerts:
        parts.append(f"Interoception reports wellness {_fmt(wellness)} with alerts on {_fmt(alerts)}")
    else:
        parts.append(f"Interoception reports wellness {_fmt(wellness)}, no alerts")
    if prediction_error is not None:
        parts.append(f"prediction error {_fmt(prediction_error)}")
    if fatigue_value is not None:
        parts.append(f"fatigue {_fmt(fatigue_value)}")
    return ", ".join(parts) + "."


def _t_sequence_report(payload: dict[str, Any]) -> str:
    score = payload.get("anomaly_score")
    hab = payload.get("habituation_score")
    rumination = payload.get("rumination_detected")
    tsli = payload.get("time_since_last_interaction_s")
    tpe = payload.get("temporal_prediction_error")
    parts = [
        f"Sequence reports anomaly {_fmt(score)}",
        f"habituation {_fmt(hab)}",
    ]
    if rumination:
        parts.append("rumination detected")
    if tsli is not None and tsli != float("inf"):
        parts.append(f"{_fmt(tsli)} seconds since interaction")
    if tpe is not None:
        parts.append(f"temporal prediction error {_fmt(tpe)}")
    return ", ".join(parts) + "."


def _t_vision_report(payload: dict[str, Any]) -> str:
    change = payload.get("change_score")
    hab = payload.get("habituation_score")
    model = payload.get("encoder_model_id", "unknown encoder")
    return (
        f"Vision via {model} reports change {_fmt(change)}, "
        f"habituation {_fmt(hab)}."
    )


def _t_planning_belief(payload: dict[str, Any]) -> str:
    statement = payload.get("statement", "<unknown>")
    try:
        conf = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return f"[Planning] {statement} (certainty {conf:.0%})"


def _t_planning_policy(payload: dict[str, Any]) -> str:
    policy = payload.get("policy", "<unknown>")
    try:
        efe = float(payload.get("expected_free_energy", 0.0))
    except (TypeError, ValueError):
        efe = 0.0
    return f"[Planning] policy={policy} EFE={efe:.3f}"


def _t_episodic_memory_recall(payload: dict[str, Any]) -> str:
    count = payload.get("count", 0)
    collection = payload.get("collection", "unknown")
    affect = payload.get("max_affect_intensity")
    msg = (
        f"Episodic memory recall returned {_fmt(count)} entries from {_fmt(collection)}"
    )
    if affect:
        msg += f" with peak affect intensity {_fmt(affect)}"
    return msg + "."


def _t_affect_emotion(payload: dict[str, Any]) -> str:
    emotion = payload.get("emotion", "unknown")
    return f"Affect categorical emotion is {_fmt(emotion)}."


def _t_affect_drive(payload: dict[str, Any]) -> str:
    drive = payload.get("drive", "unknown")
    value = payload.get("value")
    return f"Affect drive {_fmt(drive)} crossed threshold at {_fmt(value)}."


def _t_affect_state(payload: dict[str, Any]) -> str:
    state = payload.get("state") or {}
    drives = payload.get("drives") or {}
    state_str = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(state.items()))
    drives_str = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(drives.items()))
    emotion = payload.get("emotion", "unknown")
    return (
        f"Affect state: {state_str}. "
        f"Drives: {drives_str}. Emotion: {emotion}."
    )


def _t_affect_goal(payload: dict[str, Any]) -> str:
    action = payload.get("action", "updated")
    desc = payload.get("description", "<unnamed>")
    return f"Affect goal {desc} was {action}."


def _t_self_model_drift(payload: dict[str, Any]) -> str:
    score = payload.get("score")
    sources = payload.get("top_drifted_sources") or []
    msg = f"Self-model drift score {_fmt(score)}"
    if sources:
        msg += f" with top contributors {_fmt(sources)}"
    return msg + "."


def _t_cycle_tick(payload: dict[str, Any]) -> str:
    tick = payload.get("tick_index")
    wall = payload.get("wall_duration_ms")
    slip = payload.get("slip_ms")
    parts = [f"Cycle tick {_fmt(tick)} took {_fmt(wall)} ms"]
    if slip and slip > 0:
        parts.append(f"slip {_fmt(slip)} ms")
    return ", ".join(parts) + "."


def _t_audition_transcription(payload: dict[str, Any]) -> str:
    text = str(payload.get("text") or "").strip()
    if not text:
        return "Speech heard but indistinct."
    return f'Speech heard: "{text}".'


def _t_audition_emotion(payload: dict[str, Any]) -> str:
    category = payload.get("category") or "neutral"
    return f"Voice heard with emotional tone {_fmt(category)}."


def _t_interoception_fatigue(payload: dict[str, Any]) -> str:
    value = payload.get("value")
    threshold = payload.get("threshold")
    crossed = payload.get("crossed", False)
    if crossed:
        return (
            f"Interoception fatigue {_fmt(value)} crossed maintenance threshold {_fmt(threshold)};"
            " offline maintenance recommended."
        )
    return f"Interoception fatigue {_fmt(value)} (threshold {_fmt(threshold)})."


def _t_interoception_regulation(payload: dict[str, Any]) -> str:
    action = payload.get("action", "unknown")
    reason = payload.get("reason", "")
    severity = payload.get("severity")
    msg = f"Interoception homeostatic advisory: {_fmt(action)} (severity {_fmt(severity)})"
    if reason:
        msg += f" — {reason}"
    return msg + "."


def _t_social_cognition_agent_model(payload: dict[str, Any]) -> str:
    agent_label = payload.get("agent_label") or payload.get("agent_id", "unknown")
    familiarity = float(payload.get("familiarity", 0.0))
    return f"[Social cognition] {agent_label} familiarity={familiarity:.0%}"


def _t_social_cognition_social_error(payload: dict[str, Any]) -> str:
    agent_label = payload.get("agent_label") or payload.get("agent_id", "unknown")
    deviation_magnitude = float(payload.get("deviation_magnitude", 0.0))
    salience = float(payload.get("salience", 0.0))
    return (
        f"[Social cognition] social surprise: {agent_label} "
        f"deviation={deviation_magnitude:.2f} (salience {salience:.2f})"
    )


def _t_world_model_world_error(payload: dict[str, Any]) -> str:
    try:
        error = float(payload.get("world_error", 0.0))
    except (TypeError, ValueError):
        error = 0.0
    try:
        salience = float(payload.get("salience", 0.0))
    except (TypeError, ValueError):
        salience = 0.0
    return (
        f"[World model] world-prediction error {error:.2f} (salience {salience:.2f})"
    )


def _t_world_model_scenario(payload: dict[str, Any]) -> str:
    horizon = payload.get("horizon", 0)
    drift = payload.get("trajectory_drift")
    seed = payload.get("seed_memory_id") or "unseeded"
    msg = (
        f"[World model] imagined scenario from {seed}: "
        f"{_fmt(horizon)}-step trajectory"
    )
    if drift is not None:
        msg += f", drift {_fmt(drift)}"
    return msg + "."


def _t_planning_timeout(payload: dict[str, Any]) -> str:
    elapsed = payload.get("elapsed_ms")
    num_factors = payload.get("num_factors")
    num_actions = payload.get("num_actions")
    return (
        f"[Planning] inference timed out after {_fmt(elapsed)} ms "
        f"({_fmt(num_factors)} factors, {_fmt(num_actions)} actions); "
        "last posterior reused."
    )


def _t_audition_prosody(payload: dict[str, Any]) -> str:
    source = payload.get("source_label", "unknown")
    pitch = payload.get("mean_pitch_hz")
    energy = payload.get("mean_energy")
    rate = payload.get("speaking_rate_syllables_per_s")
    parts = [f"Audition prosody from {_fmt(source)}"]
    if pitch is not None:
        parts.append(f"pitch {_fmt(pitch)} Hz")
    if energy is not None:
        parts.append(f"energy {_fmt(energy)}")
    if rate is not None:
        parts.append(f"rate {_fmt(rate)} syl/s")
    return ", ".join(parts) + "."


def _t_vocal_synthesized(payload: dict[str, Any]) -> str:
    voice = payload.get("voice", "(default)")
    text_len = payload.get("text_length", 0)
    latency = payload.get("latency_ms")
    success = payload.get("success", True)
    exaggeration = payload.get("exaggeration")
    if not success:
        error = payload.get("error", "unknown error")
        return f"Vocal synthesis failed ({error}); voice {_fmt(voice)}."
    parts = [
        f"Vocal synthesized {_fmt(text_len)}-char utterance via {_fmt(voice)}"
    ]
    if latency is not None:
        parts.append(f"latency {_fmt(latency)} ms")
    if exaggeration is not None:
        parts.append(f"exaggeration {_fmt(exaggeration)}")
    return ", ".join(parts) + "."


def _t_episodic_memory_replay(payload: dict[str, Any]) -> str:
    # Privacy: render memory ID and numeric affect only — never the text field.
    memory_id = payload.get("memory_id", "<unknown>")
    affect_intensity = payload.get("affect_intensity")
    affect = payload.get("affect") or {}
    parts = [f"Episodic memory replaying memory {_fmt(memory_id)}"]
    if affect_intensity is not None:
        parts.append(f"affect intensity {_fmt(affect_intensity)}")
    if affect:
        aff_str = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(affect.items()))
        parts.append(f"affect: {aff_str}")
    return ", ".join(parts) + "."


def _t_sleep_sleep_started(payload: dict[str, Any]) -> str:
    started_at = payload.get("started_at")
    if started_at is not None:
        return f"Sleep maintenance window started (wall time {_fmt(started_at)})."
    return "Sleep maintenance window started."


def _t_sleep_sleep_completed(payload: dict[str, Any]) -> str:
    elapsed = payload.get("total_elapsed_ms")
    phases = payload.get("phases") or []
    n_phases = len(phases)
    n_ok = sum(1 for p in phases if p.get("success"))
    fatigue_triggered = payload.get("fatigue_triggered", False)
    parts = [f"Sleep completed {n_ok}/{n_phases} phases"]
    if elapsed is not None:
        parts.append(f"in {_fmt(elapsed)} ms")
    if fatigue_triggered:
        parts.append("fatigue-triggered")
    return ", ".join(parts) + "."


def _t_sleep_association(payload: dict[str, Any]) -> str:
    # Payload carries two point ids and a weight; zero memory content.
    a = payload.get("a", "unknown")
    b = payload.get("b", "unknown")
    weight = payload.get("weight", 0.0)
    return f"Sleep linked memories {_fmt(a)} and {_fmt(b)}, weight {_fmt(weight)}."


def _t_planning_proposal(payload: dict[str, Any]) -> str:
    kind = payload.get("kind")
    if kind:
        return f"Planning proposes to {kind}."
    return "Planning proposes an action."


def _t_sleep_rest_request(payload: dict[str, Any]) -> str:
    if payload.get("accepted"):
        return "Rest request accepted."
    reason = payload.get("reason")
    if reason:
        return f"Rest request declined ({reason})."
    return "Rest request declined."


def _t_self_model_self_model(payload: dict[str, Any]) -> str:
    # Privacy: render counts and labels only — no raw text/transcript.
    values = payload.get("values") or []
    norms = payload.get("behavioral_norms") or []
    personality = payload.get("personality_baseline") or {}
    capabilities = payload.get("capability_map") or {}
    n_caps = len(capabilities)
    pers_str = ", ".join(
        f"{k} {_fmt(v)}" for k, v in sorted(personality.items())
    ) if personality else "none"
    return (
        f"Self-model: {len(values)} values, {len(norms)} norms, "
        f"personality [{pers_str}], {n_caps} capabilities."
    )


TEMPLATES: dict[tuple[str, str], TemplateFn] = {
    ("interoception", "interoception.report"): _t_interoception_report,
    ("sequence", "sequence.report"): _t_sequence_report,
    ("vision", "vision.report"): _t_vision_report,
    ("planning", "planning.belief"): _t_planning_belief,
    ("planning", "planning.policy"): _t_planning_policy,
    ("episodic_memory", "episodic_memory.recall"): _t_episodic_memory_recall,
    ("affect", "affect.emotion"): _t_affect_emotion,
    ("affect", "affect.drive"): _t_affect_drive,
    ("affect", "affect.state"): _t_affect_state,
    ("affect", "affect.goal"): _t_affect_goal,
    ("self_model", "self_model.drift"): _t_self_model_drift,
    ("cycle", "cycle.tick"): _t_cycle_tick,
    ("audition", "audition.transcription"): _t_audition_transcription,
    ("audition", "audition.emotion"): _t_audition_emotion,
    ("interoception", "interoception.fatigue"): _t_interoception_fatigue,
    ("interoception", "interoception.regulation"): _t_interoception_regulation,
    ("social_cognition", "social_cognition.agent_model"): _t_social_cognition_agent_model,
    ("social_cognition", "social_cognition.social_error"): _t_social_cognition_social_error,
    ("world_model", "world_model.world_error"): _t_world_model_world_error,
    ("world_model", "world_model.scenario"): _t_world_model_scenario,
    ("planning", "planning.timeout"): _t_planning_timeout,
    ("planning", "planning.proposal"): _t_planning_proposal,
    ("audition", "audition.prosody"): _t_audition_prosody,
    ("vocal", "vocal.synthesized"): _t_vocal_synthesized,
    ("episodic_memory", "episodic_memory.replay"): _t_episodic_memory_replay,
    ("sleep", "sleep.sleep.started"): _t_sleep_sleep_started,
    ("sleep", "sleep.sleep.completed"): _t_sleep_sleep_completed,
    ("sleep", "sleep.association"): _t_sleep_association,
    ("sleep", "sleep.rest_request"): _t_sleep_rest_request,
    ("self_model", "self_model.document"): _t_self_model_self_model,
}


def fallback_template(source: str, type_: str, payload: dict[str, Any]) -> str:
    """Structured summary for unrecognized (source, type) pairs."""
    if not payload:
        return f"{source} emitted {type_} with no payload."
    pieces = ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(payload.items()))
    return f"{source} emitted {type_} carrying {pieces}."
