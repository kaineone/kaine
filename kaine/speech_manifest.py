# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The speech-model manifest and the integrity check the runtime runs before
loading a model, kept out of ``kaine.setup`` so the runtime never imports
install tooling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kaine.model_paths import speech_model_dir

__all__ = [
    "SpeechKind",
    "SpeechModel",
    "MANIFEST",
    "validate_tokens_file",
    "verify_model_dir",
    "is_installed",
]

SpeechKind = Literal["stt", "tts"]


@dataclass(frozen=True)
class SpeechModel:
    id: str
    title: str
    kind: SpeechKind
    url: str
    archive_name: str
    size_bytes: int
    sha256: str
    licence: str
    top_dir: str
    required_files: tuple[str, ...]


def _archive_url(tag: str, name: str) -> str:
    return f"https://github.com/k2-fsa/sherpa-onnx/releases/download/{tag}/{name}"


# Pinned on 2026-09-27 from the sherpa-onnx release assets.
MANIFEST: dict[str, SpeechModel] = {
    "moonshine-base-en": SpeechModel(
        id="moonshine-base-en",
        title="Moonshine base English",
        kind="stt",
        url=_archive_url(
            "asr-models",
            "sherpa-onnx-moonshine-base-en-quantized-2026-02-27.tar.bz2",
        ),
        archive_name="sherpa-onnx-moonshine-base-en-quantized-2026-02-27.tar.bz2",
        size_bytes=111_266_225,
        sha256="43232c1d13013d37317163baec3135bd771a186a4356f28c889bab453bb0e891",
        licence="MIT",
        top_dir="sherpa-onnx-moonshine-base-en-quantized-2026-02-27",
        required_files=("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt"),
    ),
    "moonshine-tiny-en": SpeechModel(
        id="moonshine-tiny-en",
        title="Moonshine tiny English",
        kind="stt",
        url=_archive_url(
            "asr-models",
            "sherpa-onnx-moonshine-tiny-en-quantized-2026-02-27.tar.bz2",
        ),
        archive_name="sherpa-onnx-moonshine-tiny-en-quantized-2026-02-27.tar.bz2",
        size_bytes=29_858_559,
        sha256="9ec31b342d8fa3240c3b81b8f82e1cf7e3ac467c93ca5a999b741d5887164f8d",
        licence="MIT",
        top_dir="sherpa-onnx-moonshine-tiny-en-quantized-2026-02-27",
        required_files=("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt"),
    ),
    "kokoro-en": SpeechModel(
        id="kokoro-en",
        title="Kokoro English",
        kind="tts",
        url=_archive_url(
            "tts-models",
            "kokoro-int8-en-v0_19.tar.bz2",
        ),
        archive_name="kokoro-int8-en-v0_19.tar.bz2",
        size_bytes=103_248_205,
        sha256="c9f0dd393615805b0bab050c340834d5e684e732aec91c0e860cd30e982c08bd",
        licence="Apache-2.0 (model); GPL-3.0-or-later (bundled espeak-ng-data)",
        top_dir="kokoro-int8-en-v0_19",
        required_files=(
            "model.int8.onnx",
            "voices.bin",
            "tokens.txt",
            "espeak-ng-data",
        ),
    ),
}


def _sha256_file(p: Path) -> str:
    """Return the SHA-256 hex digest of a file, hashing in 64 KiB chunks."""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_verified_marker(target: Path) -> dict[str, Any] | None:
    """Return the parsed ``.verified`` marker, or ``None`` if it is missing or invalid."""
    try:
        with open(target / ".verified", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def validate_tokens_file(p: Path | str) -> None:
    """Validate a sherpa-onnx ``tokens.txt`` in Python before any native load.

    Mirrors sherpa-onnx's ``ReadTokens``: each non-empty line is either a single
    non-negative integer id (the space token, allowed once) or a symbol followed
    by its non-negative integer id.  Duplicate symbols and duplicate ids are
    both allowed.
    """
    path = Path(p)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"tokens.txt is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"tokens.txt cannot be read: {exc}") from exc

    if "\x00" in text:
        raise ValueError("tokens.txt contains a NUL byte")

    found = 0
    single_field_seen = False
    for line_no, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        if line == "":
            continue
        fields = line.split()
        if len(fields) == 1:
            if single_field_seen:
                raise ValueError(
                    f"tokens.txt line {line_no} is not '<token> <id>' or '<id>': {line!r}"
                )
            id_str = fields[0]
            kind = "one-field"
        elif len(fields) == 2:
            id_str = fields[1]
            kind = "two-field"
        else:
            raise ValueError(
                f"tokens.txt line {line_no} is not '<token> <id>' or '<id>': {line!r}"
            )
        try:
            idx = int(id_str)
        except ValueError as exc:
            raise ValueError(
                f"tokens.txt line {line_no} is not '<token> <id>' or '<id>': {line!r}"
            ) from exc
        if idx < 0:
            raise ValueError(
                f"tokens.txt line {line_no} is not '<token> <id>' or '<id>': {line!r}"
            )
        if kind == "one-field":
            single_field_seen = True
        found += 1

    if found == 0:
        raise ValueError("tokens.txt contains no token lines")


def _verify_error(model_id: str, path: Path, reason: str) -> str:
    model = MANIFEST.get(model_id)
    flag = "--stt" if model and model.kind == "stt" else "--tts"
    return (
        f"model verification failed for {model_id} at {path}: {reason}. "
        f"Reinstall with python -m kaine.setup.speech_models "
        f"{flag} {model_id} [--root DIR]"
    )


def verify_model_dir(model_id: str, path: Path | str) -> None:
    """Raise ``ValueError`` unless ``path`` is a fully verified model directory."""
    model = MANIFEST.get(model_id)
    if model is None:
        raise ValueError(
            f"unknown model id: {model_id}. "
            f"Install with python -m kaine.setup.speech_models --stt/--tts {model_id} [--root DIR]"
        )
    d = Path(path)
    marker = _read_verified_marker(d)
    if marker is None:
        raise ValueError(_verify_error(model_id, d, "missing or invalid .verified marker"))

    if marker.get("model_id") != model_id or marker.get("sha256") != model.sha256:
        raise ValueError(
            _verify_error(model_id, d, ".verified marker does not match the manifest")
        )

    for rel_path, size in (marker.get("files") or {}).items():
        p = d / rel_path
        if not p.exists() or p.stat().st_size != size:
            raise ValueError(
                _verify_error(model_id, d, f"file size mismatch for {rel_path}")
            )

    for req in model.required_files:
        if not (d / req).exists():
            raise ValueError(
                _verify_error(model_id, d, f"required file missing: {req}")
            )

    expected_tokens_sha256 = marker.get("tokens_sha256")
    if expected_tokens_sha256 is None:
        raise ValueError(
            _verify_error(model_id, d, "missing tokens_sha256 in .verified marker")
        )
    actual_tokens_sha256 = _sha256_file(d / "tokens.txt")
    if actual_tokens_sha256 != expected_tokens_sha256:
        raise ValueError(
            _verify_error(model_id, d, "tokens.txt digest mismatch")
        )

    try:
        validate_tokens_file(d / "tokens.txt")
    except ValueError as exc:
        raise ValueError(_verify_error(model_id, d, str(exc))) from exc


def is_installed(model_id: str, root: Path | str | None = None) -> bool:
    """True iff the verified marker is present, valid, and every file matches."""
    model = MANIFEST.get(model_id)
    if model is None:
        return False
    d = speech_model_dir(model_id, root)
    marker = _read_verified_marker(d)
    if not marker:
        return False
    if marker.get("model_id") != model_id or marker.get("sha256") != model.sha256:
        return False

    expected_tokens_sha256 = marker.get("tokens_sha256")
    if expected_tokens_sha256 is None:
        return False
    if not (d / "tokens.txt").exists() or _sha256_file(d / "tokens.txt") != expected_tokens_sha256:
        return False

    for rel_path, size in (marker.get("files") or {}).items():
        p = d / rel_path
        if not p.exists() or p.stat().st_size != size:
            return False
    if not all((d / f).exists() for f in model.required_files):
        return False
    try:
        validate_tokens_file(d / "tokens.txt")
    except ValueError:
        return False
    return True
