# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic per-(source, type) templates.

Every template is a pure callable taking a payload dict and returning a
plain-text line. No hedging, no filler, no self-reference. The renderer
falls back to `fallback_template` for any unregistered key.
"""
from __future__ import annotations

from typing import Any, Callable

TemplateFn = Callable[[dict[str, Any]], str]

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


def _t_soma_report(payload: dict[str, Any]) -> str:
    wellness = payload.get("wellness")
    alerts = payload.get("alerts") or []
    prediction_error = payload.get("prediction_error")
    fatigue_value = payload.get("fatigue_value")
    parts = []
    if alerts:
        parts.append(f"Soma reports wellness {_fmt(wellness)} with alerts on {_fmt(alerts)}")
    else:
        parts.append(f"Soma reports wellness {_fmt(wellness)}, no alerts")
    if prediction_error is not None:
        parts.append(f"prediction error {_fmt(prediction_error)}")
    if fatigue_value is not None:
        parts.append(f"fatigue {_fmt(fatigue_value)}")
    return ", ".join(parts) + "."


def _t_chronos_report(payload: dict[str, Any]) -> str:
    score = payload.get("anomaly_score")
    hab = payload.get("habituation_score")
    rumination = payload.get("rumination_detected")
    tsli = payload.get("time_since_last_interaction_s")
    tpe = payload.get("temporal_prediction_error")
    parts = [
        f"Chronos reports anomaly {_fmt(score)}",
        f"habituation {_fmt(hab)}",
    ]
    if rumination:
        parts.append("rumination detected")
    if tsli is not None and tsli != float("inf"):
        parts.append(f"{_fmt(tsli)} seconds since interaction")
    if tpe is not None:
        parts.append(f"temporal prediction error {_fmt(tpe)}")
    return ", ".join(parts) + "."


def _t_topos_report(payload: dict[str, Any]) -> str:
    change = payload.get("change_score")
    hab = payload.get("habituation_score")
    model = payload.get("encoder_model_id", "unknown encoder")
    return (
        f"Topos via {model} reports change {_fmt(change)}, "
        f"habituation {_fmt(hab)}."
    )


def _t_nous_belief(payload: dict[str, Any]) -> str:
    statement = payload.get("statement", "<unknown>")
    try:
        conf = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return f"[Nous] {statement} (certainty {conf:.0%})"


def _t_nous_policy(payload: dict[str, Any]) -> str:
    policy = payload.get("policy", "<unknown>")
    try:
        efe = float(payload.get("expected_free_energy", 0.0))
    except (TypeError, ValueError):
        efe = 0.0
    return f"[Nous] policy={policy} EFE={efe:.3f}"


def _t_mnemos_recall(payload: dict[str, Any]) -> str:
    count = payload.get("count", 0)
    collection = payload.get("collection", "unknown")
    affect = payload.get("max_affect_intensity")
    msg = (
        f"Mnemos recall returned {_fmt(count)} entries from {_fmt(collection)}"
    )
    if affect:
        msg += f" with peak affect intensity {_fmt(affect)}"
    return msg + "."


def _t_thymos_emotion(payload: dict[str, Any]) -> str:
    emotion = payload.get("emotion", "unknown")
    return f"Thymos categorical emotion is {_fmt(emotion)}."


def _t_thymos_drive(payload: dict[str, Any]) -> str:
    drive = payload.get("drive", "unknown")
    value = payload.get("value")
    return f"Thymos drive {_fmt(drive)} crossed threshold at {_fmt(value)}."


def _t_thymos_state(payload: dict[str, Any]) -> str:
    state = payload.get("state") or {}
    drives = payload.get("drives") or {}
    state_str = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(state.items()))
    drives_str = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(drives.items()))
    emotion = payload.get("emotion", "unknown")
    return (
        f"Thymos state: {state_str}. "
        f"Drives: {drives_str}. Emotion: {emotion}."
    )


def _t_thymos_goal(payload: dict[str, Any]) -> str:
    action = payload.get("action", "updated")
    desc = payload.get("description", "<unnamed>")
    return f"Thymos goal {desc} was {action}."


def _t_eidolon_drift(payload: dict[str, Any]) -> str:
    score = payload.get("score")
    sources = payload.get("top_drifted_sources") or []
    msg = f"Eidolon drift score {_fmt(score)}"
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


def _t_soma_fatigue(payload: dict[str, Any]) -> str:
    value = payload.get("value")
    threshold = payload.get("threshold")
    crossed = payload.get("crossed", False)
    if crossed:
        return (
            f"Soma fatigue {_fmt(value)} crossed maintenance threshold {_fmt(threshold)};"
            " offline maintenance recommended."
        )
    return f"Soma fatigue {_fmt(value)} (threshold {_fmt(threshold)})."


def _t_soma_regulation(payload: dict[str, Any]) -> str:
    action = payload.get("action", "unknown")
    reason = payload.get("reason", "")
    severity = payload.get("severity")
    msg = f"Soma homeostatic advisory: {_fmt(action)} (severity {_fmt(severity)})"
    if reason:
        msg += f" — {reason}"
    return msg + "."


def _t_empatheia_agent_model(payload: dict[str, Any]) -> str:
    agent_label = payload.get("agent_label") or payload.get("agent_id", "unknown")
    familiarity = float(payload.get("familiarity", 0.0))
    return f"[Empatheia] {agent_label} familiarity={familiarity:.0%}"


def _t_empatheia_social_error(payload: dict[str, Any]) -> str:
    agent_label = payload.get("agent_label") or payload.get("agent_id", "unknown")
    deviation_magnitude = float(payload.get("deviation_magnitude", 0.0))
    salience = float(payload.get("salience", 0.0))
    return (
        f"[Empatheia] social surprise: {agent_label} "
        f"deviation={deviation_magnitude:.2f} (salience {salience:.2f})"
    )


def _t_phantasia_world_error(payload: dict[str, Any]) -> str:
    try:
        error = float(payload.get("world_error", 0.0))
    except (TypeError, ValueError):
        error = 0.0
    try:
        salience = float(payload.get("salience", 0.0))
    except (TypeError, ValueError):
        salience = 0.0
    return (
        f"[Phantasia] world-prediction error {error:.2f} (salience {salience:.2f})"
    )


def _t_phantasia_scenario(payload: dict[str, Any]) -> str:
    horizon = payload.get("horizon", 0)
    drift = payload.get("trajectory_drift")
    seed = payload.get("seed_memory_id") or "unseeded"
    msg = (
        f"[Phantasia] imagined scenario from {seed}: "
        f"{_fmt(horizon)}-step trajectory"
    )
    if drift is not None:
        msg += f", drift {_fmt(drift)}"
    return msg + "."


def _t_nous_timeout(payload: dict[str, Any]) -> str:
    elapsed = payload.get("elapsed_ms")
    num_factors = payload.get("num_factors")
    num_actions = payload.get("num_actions")
    return (
        f"[Nous] inference timed out after {_fmt(elapsed)} ms "
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


def _t_vox_synthesized(payload: dict[str, Any]) -> str:
    voice = payload.get("voice", "(default)")
    text_len = payload.get("text_length", 0)
    latency = payload.get("latency_ms")
    success = payload.get("success", True)
    exaggeration = payload.get("exaggeration")
    if not success:
        error = payload.get("error", "unknown error")
        return f"Vox synthesis failed ({error}); voice {_fmt(voice)}."
    parts = [
        f"Vox synthesized {_fmt(text_len)}-char utterance via {_fmt(voice)}"
    ]
    if latency is not None:
        parts.append(f"latency {_fmt(latency)} ms")
    if exaggeration is not None:
        parts.append(f"exaggeration {_fmt(exaggeration)}")
    return ", ".join(parts) + "."


def _t_mnemos_replay(payload: dict[str, Any]) -> str:
    # Privacy: render memory ID and numeric affect only — never the text field.
    memory_id = payload.get("memory_id", "<unknown>")
    affect_intensity = payload.get("affect_intensity")
    affect = payload.get("affect") or {}
    parts = [f"Mnemos replaying memory {_fmt(memory_id)}"]
    if affect_intensity is not None:
        parts.append(f"affect intensity {_fmt(affect_intensity)}")
    if affect:
        aff_str = ", ".join(f"{k} {_fmt(v)}" for k, v in sorted(affect.items()))
        parts.append(f"affect: {aff_str}")
    return ", ".join(parts) + "."


def _t_hypnos_sleep_started(payload: dict[str, Any]) -> str:
    started_at = payload.get("started_at")
    if started_at is not None:
        return f"Hypnos maintenance window started (wall time {_fmt(started_at)})."
    return "Hypnos maintenance window started."


def _t_hypnos_sleep_completed(payload: dict[str, Any]) -> str:
    elapsed = payload.get("total_elapsed_ms")
    phases = payload.get("phases") or []
    n_phases = len(phases)
    n_ok = sum(1 for p in phases if p.get("success"))
    fatigue_triggered = payload.get("fatigue_triggered", False)
    parts = [f"Hypnos completed {n_ok}/{n_phases} phases"]
    if elapsed is not None:
        parts.append(f"in {_fmt(elapsed)} ms")
    if fatigue_triggered:
        parts.append("fatigue-triggered")
    return ", ".join(parts) + "."


def _t_hypnos_association(payload: dict[str, Any]) -> str:
    # Payload is a compact scenario descriptor; zero raw sense data.
    horizon = payload.get("horizon", 0)
    seed_id = payload.get("seed_memory_id") or "unseeded"
    drift = payload.get("trajectory_drift")
    parts = [f"Hypnos associative scenario from {_fmt(seed_id)}: {_fmt(horizon)}-step"]
    if drift is not None:
        parts.append(f"drift {_fmt(drift)}")
    return ", ".join(parts) + "."


def _t_eidolon_self_model(payload: dict[str, Any]) -> str:
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
        f"Eidolon self-model: {len(values)} values, {len(norms)} norms, "
        f"personality [{pers_str}], {n_caps} capabilities."
    )


TEMPLATES: dict[tuple[str, str], TemplateFn] = {
    ("soma", "soma.report"): _t_soma_report,
    ("chronos", "chronos.report"): _t_chronos_report,
    ("topos", "topos.report"): _t_topos_report,
    ("nous", "nous.belief"): _t_nous_belief,
    ("nous", "nous.policy"): _t_nous_policy,
    ("mnemos", "mnemos.recall"): _t_mnemos_recall,
    ("thymos", "thymos.emotion"): _t_thymos_emotion,
    ("thymos", "thymos.drive"): _t_thymos_drive,
    ("thymos", "thymos.state"): _t_thymos_state,
    ("thymos", "thymos.goal"): _t_thymos_goal,
    ("eidolon", "eidolon.drift"): _t_eidolon_drift,
    ("cycle", "cycle.tick"): _t_cycle_tick,
    ("audition", "audition.transcription"): _t_audition_transcription,
    ("audition", "audition.emotion"): _t_audition_emotion,
    ("soma", "soma.fatigue"): _t_soma_fatigue,
    ("soma", "soma.regulation"): _t_soma_regulation,
    ("empatheia", "empatheia.agent_model"): _t_empatheia_agent_model,
    ("empatheia", "empatheia.social_error"): _t_empatheia_social_error,
    ("phantasia", "phantasia.world_error"): _t_phantasia_world_error,
    ("phantasia", "phantasia.scenario"): _t_phantasia_scenario,
    ("nous", "nous.timeout"): _t_nous_timeout,
    ("audition", "audition.prosody"): _t_audition_prosody,
    ("vox", "vox.synthesized"): _t_vox_synthesized,
    ("mnemos", "mnemos.replay"): _t_mnemos_replay,
    ("hypnos", "hypnos.sleep.started"): _t_hypnos_sleep_started,
    ("hypnos", "hypnos.sleep.completed"): _t_hypnos_sleep_completed,
    ("hypnos", "hypnos.association"): _t_hypnos_association,
    ("eidolon", "eidolon.self_model"): _t_eidolon_self_model,
}


def fallback_template(source: str, type_: str, payload: dict[str, Any]) -> str:
    """Structured summary for unrecognized (source, type) pairs."""
    if not payload:
        return f"{source} emitted {type_} with no payload."
    pieces = ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(payload.items()))
    return f"{source} emitted {type_} carrying {pieces}."
