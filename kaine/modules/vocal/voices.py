# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pure rules for picking a voice the speech engine ships when none is configured.

This is the implementation of openspec vox-default-voice: an explicit
``[vocal].default_voice`` wins first, otherwise the first voice in sorted order is
chosen, filtered by ``[vocal].voice_gender`` only where the engine makes gender
knowable. Kokoro speaker names encode gender, but the Chatterbox server reports
none, so gender filtering is only applied for Kokoro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Sequence

__all__ = [
    "VOICE_GENDERS",
    "VoiceSelectionError",
    "VoiceChoice",
    "ChatterboxVoice",
    "normalize_gender",
    "kokoro_gender",
    "parse_chatterbox_voices",
    "select_chatterbox_voice",
    "select_kokoro_speaker",
    "kokoro_speaker_name",
]

VOICE_GENDERS: tuple[str, ...] = ("any", "female", "male")


class VoiceSelectionError(ValueError):
    """No voice can be chosen from the candidates and configuration given."""


@dataclass(frozen=True)
class VoiceChoice:
    name: str
    speaker_id: int | None
    source: str
    gender_applied: bool
    note: str


@dataclass(frozen=True)
class ChatterboxVoice:
    filename: str
    display_name: str


def normalize_gender(value: object) -> str:
    """Return a canonical gender string, or raise ValueError for bad input."""
    if value is None:
        return "any"
    if not isinstance(value, str):
        raise ValueError(
            f"[vocal].voice_gender must be one of 'any', 'female' or 'male'; got {value!r}"
        )
    cleaned = value.strip().casefold()
    if cleaned == "":
        return "any"
    if cleaned in VOICE_GENDERS:
        return cleaned
    raise ValueError(
        f"[vocal].voice_gender must be one of 'any', 'female' or 'male'; got {value!r}"
    )


def kokoro_gender(name: str) -> str | None:
    """Decode the gender encoded in a Kokoro speaker name, if any.

    Speaker names use a two-letter prefix: the first letter is the language
    variant and the second letter is the gender. The prefix is either the whole
    name (for example ``"af"``) or is followed by an underscore (for example
    ``"am_adam"``).
    """
    match = re.fullmatch(r"[a-z]([fm])(?:_.*)?", name)
    if match is None:
        return None
    return "female" if match.group(1) == "f" else "male"


def parse_chatterbox_voices(payload: object) -> list[ChatterboxVoice]:
    """Parse the JSON body of GET /get_predefined_voices from a Chatterbox server."""
    seen: dict[str, ChatterboxVoice] = {}

    if isinstance(payload, dict):
        for filename in payload.keys():
            if not isinstance(filename, str) or filename == "":
                continue
            display_name = PurePath(filename).stem
            if filename not in seen:
                seen[filename] = ChatterboxVoice(
                    filename=filename, display_name=display_name
                )
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                filename = entry.get("filename")
                if not isinstance(filename, str) or filename == "":
                    continue
                raw_display = entry.get("display_name")
                if isinstance(raw_display, str) and raw_display != "":
                    display_name = raw_display
                else:
                    display_name = PurePath(filename).stem
            elif isinstance(entry, str):
                filename = entry
                if filename == "":
                    continue
                display_name = PurePath(filename).stem
            else:
                continue

            if filename not in seen:
                seen[filename] = ChatterboxVoice(
                    filename=filename, display_name=display_name
                )
    else:
        raise VoiceSelectionError(
            f"the Chatterbox server returned an unexpected voice list "
            f"({type(payload).__name__})"
        )

    return list(seen.values())


def select_chatterbox_voice(
    voices: Sequence[ChatterboxVoice],
    *,
    gender: str = "any",
    default_voice: str | None = None,
    server: str = "the Chatterbox server",
) -> VoiceChoice:
    """Pick a Chatterbox predefined voice deterministically."""
    if len(voices) == 0:
        raise VoiceSelectionError(
            f"{server} lists no predefined voices; add one to its voices directory, "
            "or set [vocal].predefined_voice_id or [vocal].default_voice"
        )

    dv = default_voice.strip() if isinstance(default_voice, str) else ""
    if dv:
        for voice in voices:
            if voice.filename == dv:
                return VoiceChoice(
                    name=voice.filename,
                    speaker_id=None,
                    source="default_voice",
                    gender_applied=False,
                    note="named in [vocal].default_voice",
                )

        dv_folded = dv.casefold()
        candidates = [
            voice
            for voice in voices
            if dv_folded == voice.filename.casefold()
            or dv_folded == PurePath(voice.filename).stem.casefold()
            or dv_folded == voice.display_name.casefold()
        ]
        if candidates:
            voice = min(candidates, key=lambda v: (v.filename.casefold(), v.filename))
            return VoiceChoice(
                name=voice.filename,
                speaker_id=None,
                source="default_voice",
                gender_applied=False,
                note="named in [vocal].default_voice",
            )

        raise VoiceSelectionError(
            f"[vocal].default_voice {dv!r} is not among the {len(voices)} voices {server} ships"
        )

    g = normalize_gender(gender)
    voice = min(voices, key=lambda v: (v.filename.casefold(), v.filename))
    n = len(voices)
    if g == "any":
        note = f"first of {n} shipped voices in sorted order"
    else:
        note = (
            f"first of {n} shipped voices in sorted order; [vocal].voice_gender = {g!r} "
            "not applied because the Chatterbox server reports no gender"
        )
    return VoiceChoice(
        name=voice.filename,
        speaker_id=None,
        source="automatic",
        gender_applied=False,
        note=note,
    )


def select_kokoro_speaker(
    speakers: Sequence[str],
    *,
    gender: str = "any",
    default_voice: str | None = None,
    model_id: str = "kokoro-en",
) -> VoiceChoice:
    """Pick a Kokoro preset speaker deterministically."""
    dv = default_voice.strip() if isinstance(default_voice, str) else ""
    if dv:
        if len(speakers) == 0:
            raise VoiceSelectionError(
                f"[vocal].default_voice {dv!r} cannot be checked: the speech manifest has no "
                f"speaker table for {model_id}; set [vocal].sherpa_speaker_id"
            )
        for i, name in enumerate(speakers):
            if name.casefold() == dv.casefold():
                return VoiceChoice(
                    name=name,
                    speaker_id=i,
                    source="default_voice",
                    gender_applied=False,
                    note="named in [vocal].default_voice",
                )
        raise VoiceSelectionError(
            f"[vocal].default_voice {dv!r} is not a speaker of {model_id} "
            f"(speakers: {', '.join(speakers)})"
        )

    g = normalize_gender(gender)

    if len(speakers) == 0:
        if g == "any":
            return VoiceChoice(
                name="",
                speaker_id=0,
                source="automatic",
                gender_applied=False,
                note=f"{model_id} has no speaker table; using speaker 0",
            )
        raise VoiceSelectionError(
            f"[vocal].voice_gender = {g!r} cannot be applied: the speech manifest has no "
            f"speaker table for {model_id}; set [vocal].sherpa_speaker_id"
        )

    candidates = [
        (i, name)
        for i, name in enumerate(speakers)
        if g == "any" or kokoro_gender(name) == g
    ]
    if not candidates:
        raise VoiceSelectionError(
            f"no speaker of {model_id} matches [vocal].voice_gender = {g!r}"
        )

    i, name = min(candidates, key=lambda c: (c[1].casefold(), c[1], c[0]))
    if g == "any":
        note = f"first of {len(speakers)} {model_id} speakers in sorted order"
    else:
        note = f"first {g} speaker of {model_id} in sorted order"
    return VoiceChoice(
        name=name,
        speaker_id=i,
        source="automatic",
        gender_applied=(g != "any"),
        note=note,
    )


def kokoro_speaker_name(speakers: Sequence[str], speaker_id: int) -> str:
    """Return the speaker name for ``speaker_id``, or the empty string when out of range."""
    if 0 <= speaker_id < len(speakers):
        return speakers[speaker_id]
    return ""
