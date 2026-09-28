# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consent-gated, pinned and verified fetcher for sherpa-onnx speech models.

Nothing is downloaded at runtime.  Model weights live under
``models_dir() / "sherpa-onnx" /``.  Archives are pinned by URL, size and
sha256, and are only ever extracted after both size and digest checks pass.

A successful install writes ``model_dir / ".verified"`` (JSON).  The marker
records the archive sha256 and the size of every regular file under the model
directory, so a truncated or tampered install is detected and replaced on the
next run.  Symlinked or dangling targets are replaced, never followed.  On
Python builds without ``tarfile.data_filter`` (before 3.11.4), extraction
writes each validated regular file by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from kaine.model_paths import models_dir

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


@dataclass(frozen=True)
class FetchResult:
    model_id: str
    ok: bool
    detail: str = ""
    path: Path | None = None


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

DEFAULT_STT = "moonshine-base-en"
DEFAULT_TTS = "kokoro-en"


def model_dir(model_id: str, root: Path | str | None = None) -> Path:
    """Directory where the extracted model for ``model_id`` is expected to live."""
    return (Path(root) if root else models_dir()) / "sherpa-onnx" / model_id


def _sha256_file(p: Path) -> str:
    """Return the SHA-256 hex digest of a file, hashing in 64 KiB chunks."""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_verified_marker(model: SpeechModel, target: Path) -> None:
    """Write ``target / ".verified"`` with the archive sha256, every file size,
    and the digest of ``tokens.txt``."""
    files: dict[str, int] = {}
    for path in target.rglob("*"):
        if path.is_file() and path.name != ".verified":
            files[str(path.relative_to(target))] = path.stat().st_size
    marker = {
        "model_id": model.id,
        "sha256": model.sha256,
        "files": files,
        "tokens_sha256": _sha256_file(target / "tokens.txt"),
    }
    with open(target / ".verified", "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2, sort_keys=True)


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
    d = model_dir(model_id, root)
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


def describe(model_id: str) -> str:
    """Single-line human description of a model, suitable for the CLI prompt."""
    model = MANIFEST.get(model_id)
    if model is None:
        return f"{model_id}: unknown model"
    purpose = "speech-to-text" if model.kind == "stt" else "text-to-speech"
    mb = model.size_bytes / 1_000_000
    return f"{model.id}: {model.title} ({purpose}), {mb:.1f} MB, {model.licence}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_downloader(
    url: str, dest_path: str, *, max_bytes: int | None = None
) -> None:
    """Streaming stdlib download: 64 KiB chunks, 60 s timeout.

    When ``max_bytes`` is set, raise ``ValueError`` if the running total
    exceeds it.  This pins the download to the declared model size.
    """
    total = 0
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest_path, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ValueError("download exceeded the pinned size")
            f.write(chunk)


def _validate_and_extract(tf: tarfile.TarFile, extract_dir: Path, top_dir: str) -> None:
    """Manually validate every tar member, then extract safely.

    On Python >= 3.11.4 ``tarfile.data_filter`` is available and we use the
    ``data`` filter.  On older builds we write the validated members ourselves
    with fixed permissions (0o644 for files, 0o755 for directories).
    """
    base = extract_dir.resolve()
    members: list[tarfile.TarInfo] = []
    for member in tf.getmembers():
        if not (member.isfile() or member.isdir()):
            raise ValueError(
                f"rejected member {member.name}: not a regular file or directory"
            )
        if os.path.isabs(member.name) or member.name.startswith("/"):
            raise ValueError(f"rejected member {member.name}: absolute path")
        parts = Path(member.name).parts
        if any(part == ".." for part in parts):
            raise ValueError(f"rejected member {member.name}: contains ..")
        if not parts or parts[0] != top_dir:
            raise ValueError(
                f"rejected member {member.name}: wrong top-level directory "
                f"(expected {top_dir})"
            )
        dest = (extract_dir / member.name).resolve()
        if not dest.is_relative_to(base):
            raise ValueError(
                f"rejected member {member.name}: resolves outside extraction dir"
            )
        members.append(member)

    if hasattr(tarfile, "data_filter"):
        tf.extractall(path=str(extract_dir), members=members, filter="data")
        return

    for member in members:
        dest = extract_dir / member.name
        if member.isdir():
            dest.mkdir(parents=True, exist_ok=True)
            dest.chmod(0o755)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                raise ValueError(f"unable to read member {member.name}")
            with open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            dest.chmod(0o644)


def fetch(
    model_id: str,
    *,
    root: Path | str | None = None,
    downloader: Callable[[str, str], None] | None = None,
) -> FetchResult:
    """Download, verify and extract a pinned model.  Never raises for expected failures."""
    model = MANIFEST.get(model_id)
    if model is None:
        return FetchResult(
            model_id=model_id, ok=False, detail=f"unknown model id: {model_id}"
        )

    root_path = Path(root) if root else models_dir()
    target = model_dir(model_id, root_path)

    if is_installed(model_id, root_path):
        return FetchResult(
            model_id=model_id, ok=True, detail="already installed", path=target
        )

    base = root_path / "sherpa-onnx"
    base.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=base, prefix=f"{model_id}_") as tmp:
        archive_path = Path(tmp) / model.archive_name
        try:
            if downloader is None:
                _default_downloader(
                    model.url, str(archive_path), max_bytes=model.size_bytes
                )
            else:
                downloader(model.url, str(archive_path))
        except Exception as exc:
            return FetchResult(
                model_id=model_id, ok=False, detail=f"download failed: {exc}"
            )

        actual_size = archive_path.stat().st_size
        if actual_size != model.size_bytes:
            return FetchResult(
                model_id=model_id,
                ok=False,
                detail=f"size mismatch: expected {model.size_bytes}, got {actual_size}",
            )

        actual_hash = _sha256_file(archive_path)
        if actual_hash != model.sha256:
            return FetchResult(
                model_id=model_id,
                ok=False,
                detail=f"sha256 mismatch: expected {model.sha256}, got {actual_hash}",
            )

        extract_dir = Path(tmp) / "extract"
        extract_dir.mkdir()

        try:
            with tarfile.open(archive_path, "r:bz2") as tf:
                _validate_and_extract(tf, extract_dir, model.top_dir)
        except Exception as exc:
            return FetchResult(
                model_id=model_id, ok=False, detail=f"extraction failed: {exc}"
            )

        src = extract_dir / model.top_dir
        for req in model.required_files:
            if not (src / req).exists():
                return FetchResult(
                    model_id=model_id,
                    ok=False,
                    detail=f"required file missing after extraction: {req}",
                )

        try:
            if target.is_symlink():
                target.unlink()
            elif target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(src), str(target))
            _write_verified_marker(model, target)
        except OSError as exc:
            return FetchResult(
                model_id=model_id, ok=False, detail=f"install failed: {exc}"
            )

    return FetchResult(model_id=model_id, ok=True, detail="installed", path=target)


def required_speech_models(config: dict) -> list[str]:
    """Return the sherpa-onnx model ids that the config needs.

    - STT when ``[audition].backend == "sherpa_onnx"`` and
      ``[audition].transcription_enabled`` is true.
    - TTS when ``[vox].backend == "sherpa_onnx"``.

    Unknown ids are skipped with a warning.
    """
    ids: list[str] = []

    audition = config.get("audition") or {}
    if str(audition.get("backend", "speaches")).strip().lower() == "sherpa_onnx":
        if bool(audition.get("transcription_enabled", False)):
            stt_id = str(audition.get("sherpa_model_id", DEFAULT_STT)).strip()
            if stt_id in MANIFEST:
                ids.append(stt_id)
            else:
                warnings.warn(f"skipping unknown speech model id: {stt_id}")

    vox = config.get("vox") or {}
    if str(vox.get("backend", "chatterbox")).strip().lower() == "sherpa_onnx":
        tts_id = str(vox.get("sherpa_model_id", DEFAULT_TTS)).strip()
        if tts_id in MANIFEST:
            ids.append(tts_id)
        else:
            warnings.warn(f"skipping unknown speech model id: {tts_id}")

    return ids


def main(
    argv: list[str] | None = None,
    input_fn: Callable[[str], str] = input,
    downloader: Callable[[str, str], None] | None = None,
) -> int:
    """CLI: ``python -m kaine.setup.speech_models [--stt ID] [--tts ID] [--yes] [--root DIR]``."""
    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.speech_models",
        description=(
            "Fetch pinned sherpa-onnx speech model weights. "
            "Kokoro English is Apache-2.0 (model); "
            "GPL-3.0-or-later (espeak-ng-data and the espeak-ng engine built into sherpa-onnx). "
            "Each run prints the licence and asks for consent unless --yes."
        ),
    )
    parser.add_argument("--stt", metavar="ID", help="STT model id to fetch")
    parser.add_argument("--tts", metavar="ID", help="TTS model id to fetch")
    parser.add_argument("--yes", action="store_true", help="skip confirmation")
    parser.add_argument("--root", metavar="DIR", default=None, help="models root directory")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else None

    selected: list[str] = []
    if args.stt:
        if args.stt not in MANIFEST:
            print(f"unknown STT model id: {args.stt}", file=sys.stderr)
            return 2
        if MANIFEST[args.stt].kind != "stt":
            print(
                f"model {args.stt} is not an STT model "
                f"(expected kind 'stt', got '{MANIFEST[args.stt].kind}')",
                file=sys.stderr,
            )
            return 2
        selected.append(args.stt)
    if args.tts:
        if args.tts not in MANIFEST:
            print(f"unknown TTS model id: {args.tts}", file=sys.stderr)
            return 2
        if MANIFEST[args.tts].kind != "tts":
            print(
                f"model {args.tts} is not a TTS model "
                f"(expected kind 'tts', got '{MANIFEST[args.tts].kind}')",
                file=sys.stderr,
            )
            return 2
        selected.append(args.tts)
    if not selected:
        selected = [DEFAULT_STT, DEFAULT_TTS]

    for mid in selected:
        print(describe(mid))

    if not args.yes:
        answer = input_fn(f"Download {len(selected)} model(s)? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("nothing was fetched")
            return 0

    all_ok = True
    for mid in selected:
        result = fetch(mid, root=root, downloader=downloader)
        status = "ok" if result.ok else "failed"
        print(f"{mid}: {status} — {result.detail}")
        if not result.ok:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
