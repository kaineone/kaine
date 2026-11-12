# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Speech rung catalogue: ordered TTS and STT ladders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpeechRung:
    backend: str
    model_id: str
    label: str
    licence: str
    mapped: bool
    fetch_command: str
    quantization: str | None = None
    weights_sha256: str | None = None


TTS_LADDER: tuple[SpeechRung, ...] = (
    SpeechRung(
        backend="chatterbox",
        model_id="chatterbox",
        label="Chatterbox (GPU service)",
        licence="MIT",
        mapped=False,
        fetch_command="",
    ),
    SpeechRung(
        backend="sherpa_onnx",
        model_id="kokoro-en",
        label="Kokoro English int8 (CPU)",
        licence="Apache-2.0 (model); GPL-3.0-or-later (espeak-ng-data)",
        mapped=False,
        fetch_command="python -m kaine.setup.speech_models --tts kokoro-en",
        quantization="int8",
    ),
)

STT_LADDER: tuple[SpeechRung, ...] = (
    SpeechRung(
        backend="speaches",
        model_id="medium.en",
        label="Speaches faster-whisper medium.en (service)",
        licence="MIT",
        mapped=False,
        fetch_command="",
    ),
    SpeechRung(
        backend="sherpa_onnx",
        model_id="moonshine-base-en",
        label="Moonshine base English (CPU)",
        licence="MIT",
        mapped=False,
        fetch_command="python -m kaine.setup.speech_models --stt moonshine-base-en",
    ),
    SpeechRung(
        backend="sherpa_onnx",
        model_id="moonshine-tiny-en",
        label="Moonshine tiny English (CPU)",
        licence="MIT",
        mapped=False,
        fetch_command="python -m kaine.setup.speech_models --stt moonshine-tiny-en",
    ),
)

LADDERS: dict[str, tuple[SpeechRung, ...]] = {
    "vocal.tts": TTS_LADDER,
    "audition.stt": STT_LADDER,
}


def rung_key(rung: SpeechRung) -> str:
    return f"{rung.backend}:{rung.model_id}"


def lookup_footprint(
    rung: SpeechRung,
    component: str,
    entries: list[Any],
    host_class: str,
) -> int | None:
    """Return the calibrated peak footprint in bytes for a rung, or None."""
    matches = [
        e
        for e in entries
        if e.component == component
        and e.backend == rung.backend
        and e.model_id == rung.model_id
        and e.host_class == host_class
    ]
    if not matches:
        return None
    return max(e.bytes for e in matches)


def is_rung_installed(rung: SpeechRung) -> bool:
    """Check whether a rung's model is present on this host."""
    if rung.backend in ("chatterbox", "speaches"):
        return True
    if rung.backend == "sherpa_onnx":
        from kaine.speech_manifest import is_installed

        return is_installed(rung.model_id)
    return False


@dataclass(frozen=True)
class RungSelection:
    rung: SpeechRung
    reason: str
    hints: tuple[str, ...]


def select_rung(
    ladder: tuple[SpeechRung, ...],
    component: str,
    entries: list[Any],
    host_class: str,
    budget_bytes: int | None,
) -> RungSelection | None:
    """Select the heaviest installed rung that fits within budget.

    Walk the ladder from heaviest to lightest. For each rung:
    1. If not installed, record a hint naming its fetch_command and skip.
    2. Look up its calibrated footprint. If no calibration data, treat as
       uncalibrated (fits by default, since we cannot prove it does not).
    3. If budget_bytes is None (no budget constraint), accept it.
    4. If the footprint fits within budget_bytes, accept it.
    5. Otherwise skip (too large).

    Return a RungSelection with the chosen rung, the reason for the choice,
    and any hints about better rungs that are not installed.
    Return None only when no rung in the ladder is installed.
    """
    hints: list[str] = []
    for rung in ladder:
        if not is_rung_installed(rung):
            if rung.fetch_command:
                hints.append(f"{rung.label} is not installed; fetch with: {rung.fetch_command}")
            continue

        footprint = lookup_footprint(rung, component, entries, host_class)

        if budget_bytes is None or footprint is None:
            reason = "heaviest installed rung"
            if footprint is None:
                reason += " (uncalibrated)"
            return RungSelection(rung=rung, reason=reason, hints=tuple(hints))

        if footprint <= budget_bytes:
            reason = "heaviest installed rung that fits"
            return RungSelection(rung=rung, reason=reason, hints=tuple(hints))

    return None
