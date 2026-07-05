# SPDX-License-Identifier: LicenseRef-CAL-0.2
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
    "soma", "chronos", "topos", "nous", "mnemos", "eidolon", "thymos",
    "praxis", "lingua", "audition", "vox", "hypnos", "echo",
]
# Canonical set of streams the live system actually publishes to.
_PRODUCER_STREAMS = {module_stream(m) for m in _MODULE_NAMES} | {
    "workspace.broadcast",   # Syneidesis
    "cycle.out",             # cycle engine
    "lingua.external",       # Lingua external speech
    "lingua.internal",       # Lingua internal speech
    "volition.out",          # executive action-selection intents
}


def _configured_stream_refs() -> list[tuple[str, str]]:
    """(location, stream_name) for every stream a consumer reads, per config."""
    refs: list[tuple[str, str]] = []
    for s in _CONFIG.get("chronos", {}).get("user_input_streams", []):
        refs.append(("chronos.user_input_streams", s))
    thymos = _CONFIG.get("thymos", {})
    for key in ("soma_stream", "chronos_stream", "mnemos_stream"):
        if key in thymos:
            refs.append((f"thymos.{key}", thymos[key]))
    eidolon = _CONFIG.get("eidolon", {})
    if "internal_speech_stream" in eidolon:
        refs.append(("eidolon.internal_speech_stream", eidolon["internal_speech_stream"]))
    vox = _CONFIG.get("vox", {})
    for key in ("lingua_external_stream", "thymos_state_stream"):
        if key in vox:
            refs.append((f"vox.{key}", vox[key]))
    soma = _CONFIG.get("soma", {})
    if "cycle_stream" in soma:
        refs.append(("soma.cycle_stream", soma["cycle_stream"]))
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


def test_chronos_reads_the_audition_producer_stream():
    assert module_stream("audition") == "audition.out"
    assert "audition.out" in _CONFIG["chronos"]["user_input_streams"]
    # Verify no legacy stream name leaked back in.
    for stream in _CONFIG["chronos"]["user_input_streams"]:
        assert not stream.startswith("audio_"), f"legacy stream name found: {stream}"


def test_chronos_code_default_user_input_stream_resolves():
    """The in-code fallback must also use the real producer stream, not just
    the config value (config overrides it, but the default must not be a typo)."""
    from kaine.modules.chronos.module import DEFAULT_USER_INPUT_STREAMS

    assert module_stream("audition") in DEFAULT_USER_INPUT_STREAMS
    legacy = [s for s in DEFAULT_USER_INPUT_STREAMS if s.startswith("audio_")]
    assert not legacy, f"legacy stream name(s) in DEFAULT_USER_INPUT_STREAMS: {legacy}"
