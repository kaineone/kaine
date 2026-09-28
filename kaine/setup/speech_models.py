# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consent-gated, pinned and verified fetcher for sherpa-onnx speech models.

Nothing is downloaded at runtime.  Model weights live under
``models_dir() / "sherpa-onnx" /``.  Archives are pinned by URL, size and
sha256, and are only ever extracted after both size and digest checks pass.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

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
        licence="Apache-2.0",
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


def is_installed(model_id: str, root: Path | str | None = None) -> bool:
    """True iff every required file for ``model_id`` exists under its model dir."""
    model = MANIFEST.get(model_id)
    if model is None:
        return False
    d = model_dir(model_id, root)
    return all((d / f).exists() for f in model.required_files)


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
    """Manually validate every tar member, then extract with the ``data`` filter."""
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
    tf.extractall(path=str(extract_dir), members=members, filter="data")


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

        if target.exists():
            if not is_installed(model_id, root_path):
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            else:
                return FetchResult(
                    model_id=model_id, ok=True, detail="already installed", path=target
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(src), str(target))

    return FetchResult(model_id=model_id, ok=True, detail="installed", path=target)


def main(
    argv: list[str] | None = None,
    input_fn: Callable[[str], str] = input,
    downloader: Callable[[str, str], None] | None = None,
) -> int:
    """CLI: ``python -m kaine.setup.speech_models [--stt ID] [--tts ID] [--yes] [--root DIR]``."""
    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.speech_models",
        description="Fetch pinned sherpa-onnx speech model weights.",
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
