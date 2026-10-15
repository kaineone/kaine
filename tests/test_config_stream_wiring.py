# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Guard against config stream-reference typos (e.g. audition.out vs
audition.out). Every stream name a module is configured to consume must
resolve to a real producer stream that some module publishes to."""
from __future__ import annotations

import pathlib
import tomllib

from kaine.bus.schema import module_stream

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CONFIG = tomllib.loads((_ROOT / "config" / "kaine.toml").read_text())

# Modules whose producer stream is `<name>.out`.
_MODULE_NAMES = [
    "interoception", "sequence", "vision", "planning", "episodic_memory", "self_model", "affect",
    "effectors", "language", "audition", "vocal", "sleep", "social_cognition",
    "embodiment", "perceptual_locus", "world_model", "recorder",
]
# Canonical set of streams the live system actually publishes to.
# ``language.out`` is the language module's aggregate producer and is already included via
# ``module_stream("language")`` in the list above.
_PRODUCER_STREAMS = {module_stream(m) for m in _MODULE_NAMES} | {
    "workspace.broadcast",   # the workspace
    "cycle.out",             # cycle engine
    "language.external",       # the language module's external speech
    "language.internal",       # the language module's internal speech
    "action_selection.out",          # executive action-selection intents
}


def _configured_stream_refs() -> list[tuple[str, str]]:
    """(location, stream_name) for every stream a consumer reads, per config."""
    refs: list[tuple[str, str]] = []
    for s in _CONFIG.get("sequence", {}).get("user_input_streams", []):
        refs.append(("sequence.user_input_streams", s))
    affect = _CONFIG.get("affect", {})
    for key in ("interoception_stream", "sequence_stream", "episodic_memory_stream"):
        if key in affect:
            refs.append((f"affect.{key}", affect[key]))
    self_model = _CONFIG.get("self_model", {})
    if "internal_speech_stream" in self_model:
        refs.append(("self_model.internal_speech_stream", self_model["internal_speech_stream"]))
    vocal = _CONFIG.get("vocal", {})
    for key in ("language_external_stream", "affect_state_stream"):
        if key in vocal:
            refs.append((f"vocal.{key}", vocal[key]))
    interoception = _CONFIG.get("interoception", {})
    if "cycle_stream" in interoception:
        refs.append(("interoception.cycle_stream", interoception["cycle_stream"]))
    return refs


def test_config_stream_references_resolve_to_real_producers():
    bad = [
        (loc, name)
        for loc, name in _configured_stream_refs()
        if name not in _PRODUCER_STREAMS
    ]
    assert not bad, (
        "config references streams no module produces (wiring typo?): "
        + ", ".join(f"{loc}={name!r}" for loc, name in bad)
    )


def test_sequence_reads_the_audition_producer_stream():
    assert module_stream("audition") == "audition.out"
    assert "audition.out" in _CONFIG["sequence"]["user_input_streams"]
    # Verify no legacy stream name leaked back in.
    for stream in _CONFIG["sequence"]["user_input_streams"]:
        assert not stream.startswith("audio_"), f"legacy stream name found: {stream}"


def test_sequence_code_default_user_input_stream_resolves():
    """The in-code fallback must also use the real producer stream, not just
    the config value (config overrides it, but the default must not be a typo)."""
    from kaine.modules.sequence.module import DEFAULT_USER_INPUT_STREAMS

    assert module_stream("audition") in DEFAULT_USER_INPUT_STREAMS
    legacy = [s for s in DEFAULT_USER_INPUT_STREAMS if s.startswith("audio_")]
    assert not legacy, f"legacy stream name(s) in DEFAULT_USER_INPUT_STREAMS: {legacy}"
