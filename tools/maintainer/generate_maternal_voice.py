#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Generate the maternal-voice audio repertoire for the KAINE developmental stimulus.

This offline maintainer script renders every take of every item listed in the
texts TOML file through the Chatterbox TTS model, then writes trimmed,
level-normalised, peak-limited FLAC files and a JSON manifest. It is intended
to be run by a maintainer on a workstation with a CUDA-capable GPU; the
runtime playback module reads the manifest and audio files.

Usage:
    python tools/maintainer/generate_maternal_voice.py [--texts PATH]
        [--out DIR] [--reference-dir DIR] [--device DEVICE]
        [--only ID ...] [--verify]

The rendered voice is not a recording of a real person. It is a neural TTS
rendering conditioned on the CMU ARCTIC "slt" speaker, a female US English
speaker recorded at Carnegie Mellon University for building speech synthesis
voices (Kominek and Black 2003). The CMU ARCTIC data is released under a licence
free for any purpose that requires retaining its notice.

Chatterbox applies its Perth implicit watermark (resemble-perth) to every raw
output waveform before the post-processing in this script.
"""

import hashlib
import json
import math
import re
import sys
import time
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, where Chatterbox 0.1.6 environments often live
    import tomli as tomllib
import urllib.error
import urllib.request
from importlib.metadata import version as package_version
from pathlib import Path

CHATTERBOX_VERSION = "0.1.6"
MODEL_REPO = "ResembleAI/chatterbox"
MODEL_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
MODEL_FILES = (
    "ve.safetensors",
    "t3_cfg.safetensors",
    "s3gen.safetensors",
    "tokenizer.json",
    "conds.pt",
)
BASE_SEED = 20261018
OUTPUT_SAMPLE_RATE = 8000
TARGET_RMS_DBFS = -20.0
PEAK_CEILING_DBFS = -1.0
TRIM_TOP_DB = 40.0
EXAGGERATION = 0.5
CFG_WEIGHT = 0.5
TEMPERATURE = 0.8
REFERENCE_BASE_URL = "http://festvox.org/cmu_arctic/cmu_arctic/cmu_us_slt_arctic/wav/"
REFERENCE_FILES = (
    ("arctic_a0001.wav", "7862eb2cccb56875910f6bf46f9b8d26dac36e7672829aabe3956b0837ae122e"),
    ("arctic_a0003.wav", "0b32e00846e132826f46d7e5cabb2d8b370a5dc654bac0447cb63285f81cc413"),
    ("arctic_a0004.wav", "2a653cf74346ff24690f8a2abcff5091b81463f277b0062c851031a293f25167"),
    ("arctic_a0005.wav", "f93c823f955875d2389ae0f731a95128afb1ee096df7614e063e8b4b5695801d"),
    ("arctic_a0006.wav", "69b800a69455e35d05162b78b69446294ace69be903693ffd02ccd0150f17d66"),
    ("arctic_a0007.wav", "3c10caa9c2b5434f64c393a85a70aba57adf2858628d7983a8fd4f98a19a83d6"),
    ("arctic_a0008.wav", "603ac9585ddb5022d9c973bde867d7957fa1b8c1f44b2ee40fbbafedde8b5f0e"),
)
REFERENCE_ATTRIBUTION = (
    "CMU ARCTIC speaker slt (Kominek and Black 2003), "
    "Carnegie Mellon University, http://www.festvox.org/cmu_arctic/"
)


_ID_RE = re.compile(r"^[a-z0-9-]+$")


def file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, streaming in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1_048_576)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_texts(path: Path):
    """Load and validate the texts TOML file.

    Returns (items, initial_unlocked, texts_sha256).
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    if "initial_unlocked" not in data:
        raise SystemExit("error: texts file is missing 'initial_unlocked'")
    initial_unlocked = data["initial_unlocked"]
    if not isinstance(initial_unlocked, int):
        raise SystemExit("error: 'initial_unlocked' must be an integer")

    raw_items = data.get("item")
    if not isinstance(raw_items, list):
        raise SystemExit("error: texts file must contain an array of tables named 'item'")

    if not (1 <= initial_unlocked <= len(raw_items)):
        raise SystemExit(
            f"error: initial_unlocked must be between 1 and {len(raw_items)} (got {initial_unlocked})"
        )

    seen = set()
    items = []
    for idx, it in enumerate(raw_items):
        if not isinstance(it, dict):
            raise SystemExit(f"error: item {idx} is not a table")
        for field in ("id", "kind", "takes", "text"):
            if field not in it:
                raise SystemExit(f"error: item {idx} is missing field '{field}'")

        id_ = it["id"]
        kind = it["kind"]
        takes = it["takes"]
        text = it["text"]

        if not isinstance(id_, str) or not _ID_RE.fullmatch(id_):
            raise SystemExit(f"error: item {idx} id must match ^[a-z0-9-]+$ (got {id_!r})")
        if id_ in seen:
            raise SystemExit(f"error: duplicate item id {id_!r}")
        if kind not in ("passage", "phrase"):
            raise SystemExit(f"error: item {id_!r} kind must be 'passage' or 'phrase' (got {kind!r})")
        if not isinstance(takes, int) or takes < 1:
            raise SystemExit(f"error: item {id_!r} takes must be an integer >= 1 (got {takes!r})")
        if not isinstance(text, str) or not text:
            raise SystemExit(f"error: item {id_!r} text must be a non-empty string")
        if "\u2014" in text or "\u2013" in text:
            raise SystemExit(f"error: item {id_!r} text contains a dash character (U+2014 or U+2013)")

        seen.add(id_)
        items.append({"id": id_, "kind": kind, "takes": takes, "text": text})

    return items, initial_unlocked, file_sha256(path)


def load_existing_manifest(out_dir: Path):
    """Return the parsed manifest.json, or None if it does not exist."""
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    with open(manifest_path, "rb") as f:
        return json.load(f)


def download_file(url: str, dest: Path) -> None:
    """Download a URL to a path, retrying up to five times on network errors."""
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:
                while True:
                    chunk = response.read(1_048_576)
                    if not chunk:
                        break
                    out.write(chunk)
            return
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"warning: download attempt {attempt + 1}/5 failed for {url}: {exc}", file=sys.stderr)
            if attempt < 4:
                time.sleep(1)
    raise SystemExit(f"error: failed to download {url} after 5 attempts")


def ensure_reference_files(ref_dir: Path) -> None:
    """Ensure reference WAV files exist with the expected SHA-256 hashes."""
    ref_dir.mkdir(parents=True, exist_ok=True)
    for name, expected_digest in REFERENCE_FILES:
        path = ref_dir / name
        if path.exists():
            if file_sha256(path) == expected_digest:
                continue
            raise SystemExit(
                f"error: reference file {name} exists but its hash does not match {expected_digest}; "
                "remove it manually"
            )

        url = REFERENCE_BASE_URL + name
        print(f"downloading reference {name} ...")
        download_file(url, path)
        if file_sha256(path) != expected_digest:
            path.unlink(missing_ok=True)
            raise SystemExit(f"error: downloaded reference file {name} hash mismatch (expected {expected_digest})")


def build_reference_wav(ref_dir: Path):
    """Concatenate reference files with 0.3 s silence and write slt-reference.wav."""
    segments = []
    sr = None
    for name, _ in REFERENCE_FILES:
        y, file_sr = librosa.load(str(ref_dir / name), sr=None, mono=True)
        if sr is None:
            sr = file_sr
        elif file_sr != sr:
            raise SystemExit(
                f"error: reference file {name} sample rate {file_sr} differs from {sr}"
            )
        segments.append(y)
        segments.append(np.zeros(int(sr * 0.3), dtype=y.dtype))

    if segments:
        segments.pop()  # remove trailing silence

    concat = np.concatenate(segments) if segments else np.array([], dtype=np.float32)
    reference_wav = ref_dir / "slt-reference.wav"
    soundfile.write(str(reference_wav), concat, sr, subtype="PCM_16")
    return reference_wav, file_sha256(reference_wav)


def load_model(device: str):
    """Download model files and load ChatterboxTTS from the checkpoint directory."""
    paths = []
    for filename in MODEL_FILES:
        path = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=filename,
            revision=MODEL_REVISION,
        )
        paths.append(path)

    ckpt_dir = Path(paths[0]).parent
    print(f"loading ChatterboxTTS from {ckpt_dir} on {device} ...")
    model = ChatterboxTTS.from_local(str(ckpt_dir), device)
    return model


def render_take(model, reference_wav: Path, text: str, item: dict, index: int, take: int, out_dir: Path):
    """Render a single take and write the FLAC file."""
    seed = BASE_SEED + 1000 * index + take
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    print(f"generating {item['id']} take {take} (seed {seed}) ...")
    wav_tensor = model.generate(
        text,
        audio_prompt_path=str(reference_wav),
        exaggeration=EXAGGERATION,
        cfg_weight=CFG_WEIGHT,
        temperature=TEMPERATURE,
    )
    wav = wav_tensor.squeeze(0).cpu().numpy().astype("float64")

    trimmed, _ = librosa.effects.trim(wav, top_db=TRIM_TOP_DB)
    if trimmed.size == 0:
        raise SystemExit(f"error: {item['id']} take {take} is silent after trimming")
    if len(trimmed) < int(0.3 * model.sr):
        raise SystemExit(f"error: {item['id']} take {take} is shorter than 0.3 s after trimming")

    resampled = librosa.resample(
        trimmed, orig_sr=model.sr, target_sr=OUTPUT_SAMPLE_RATE, res_type="soxr_hq"
    )

    rms = np.sqrt(np.mean(resampled**2))
    if rms == 0.0:
        raise SystemExit(f"error: {item['id']} take {take} has zero RMS")

    target_linear = 10 ** (TARGET_RMS_DBFS / 20.0)
    scaled = resampled * (target_linear / rms)

    peak = np.max(np.abs(scaled))
    if peak > 0.0:
        peak_dbfs = 20 * math.log10(peak)
        if peak_dbfs > PEAK_CEILING_DBFS:
            peak_target = 10 ** (PEAK_CEILING_DBFS / 20.0)
            scaled = scaled * (peak_target / peak)

    int16_wav = np.clip(np.round(scaled * 32767.0), -32768, 32767).astype(np.int16)

    out_path = out_dir / f"{item['id']}.t{take}.flac"
    soundfile.write(
        str(out_path), int16_wav, OUTPUT_SAMPLE_RATE, format="FLAC", subtype="PCM_16"
    )

    digest = file_sha256(out_path)
    size = out_path.stat().st_size
    frames = len(int16_wav)
    seconds = round(frames / OUTPUT_SAMPLE_RATE, 3)

    final_rms = np.sqrt(np.mean(scaled**2))
    final_rms_dbfs = 20 * math.log10(final_rms) if final_rms > 0.0 else -float("inf")

    return {
        "take": take,
        "file": out_path.name,
        "sha256": digest,
        "frames": frames,
        "seconds": seconds,
        "seed": seed,
        "rms_dbfs": round(final_rms_dbfs, 2),
    }, size


def reuse_existing_takes(existing_item: dict, out_dir: Path) -> list:
    """Verify existing take files and return their manifest entries unchanged."""
    verified = []
    for take in existing_item.get("takes", []):
        path = out_dir / take["file"]
        if not path.exists():
            raise SystemExit(
                f"error: existing take file missing for {existing_item['id']} take {take['take']}: {take['file']}"
            )
        if file_sha256(path) != take["sha256"]:
            raise SystemExit(
                f"error: existing take file hash mismatch for {existing_item['id']} take {take['take']}: {take['file']}"
            )
        verified.append(take)
    return verified


def verify_manifest(out_dir: Path) -> int:
    """Verify all files listed in the manifest. Return 0 on success, 1 on failure."""
    manifest = load_existing_manifest(out_dir)
    if manifest is None:
        print(f"error: no manifest.json found in {out_dir}", file=sys.stderr)
        return 1

    problems = []
    total_bytes = 0
    total_seconds = 0.0
    take_count = 0

    for item in manifest.get("items", []):
        for take in item.get("takes", []):
            take_count += 1
            path = out_dir / take["file"]
            if not path.exists():
                problems.append(f"missing file: {take['file']}")
                continue
            if file_sha256(path) != take["sha256"]:
                problems.append(f"hash mismatch: {take['file']}")
            else:
                total_bytes += path.stat().st_size
            total_seconds += take.get("seconds", 0.0)

    if problems:
        print("verification failed:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(
        f"verified {take_count} takes; {total_bytes} bytes, "
        f"{round(total_seconds, 3)} seconds"
    )
    return 0


def main() -> int:
    import argparse

    repo_root = Path(__file__).resolve().parents[2]

    parser = argparse.ArgumentParser(
        description="Generate the maternal-voice audio repertoire for KAINE."
    )
    parser.add_argument(
        "--texts",
        type=Path,
        default=repo_root / "kaine" / "modules" / "audition" / "maternal_voice" / "texts.toml",
        help="path to the texts TOML file (default: <repo>/kaine/modules/audition/maternal_voice/texts.toml)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=repo_root / "kaine" / "modules" / "audition" / "maternal_voice",
        help="output directory for FLAC files and manifest.json",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=Path.home() / ".cache" / "kaine" / "maternal-voice-reference",
        help="directory for reference WAV files (default: ~/.cache/kaine/maternal-voice-reference)",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        help="torch device for ChatterboxTTS (default: cuda)",
    )
    parser.add_argument(
        "--only",
        action="append",
        nargs="+",
        metavar="ID",
        help="render only these item ids (may be repeated; requires an existing manifest)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify the manifest and audio files instead of rendering",
    )
    args = parser.parse_args()

    if args.verify:
        return verify_manifest(args.out.expanduser())

    # Heavy imports are deferred until after argument parsing so --help is fast.
    # They are bound as module globals because the helpers above use them.
    global random, librosa, np, soundfile, torch, ChatterboxTTS, hf_hub_download
    import random

    import librosa
    import numpy as np
    import soundfile
    import torch
    from chatterbox.tts import ChatterboxTTS
    from huggingface_hub import hf_hub_download

    installed_version = package_version("chatterbox-tts")
    if installed_version != CHATTERBOX_VERSION:
        raise SystemExit(
            f"error: chatterbox-tts version mismatch (installed {installed_version}, expected {CHATTERBOX_VERSION})"
        )

    texts_path = args.texts
    out_dir = args.out.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    items, initial_unlocked, texts_sha256 = load_texts(texts_path)

    only_set = None
    if args.only:
        only_set = {id_ for group in args.only for id_ in group}
        missing = only_set - {it["id"] for it in items}
        if missing:
            raise SystemExit(f"error: --only ids not found in texts file: {', '.join(sorted(missing))}")

    existing_by_id = {}
    if only_set:
        existing_manifest = load_existing_manifest(out_dir)
        if existing_manifest is None:
            raise SystemExit("error: --only requires an existing manifest to reuse entries for other items")
        for it in existing_manifest.get("items", []):
            existing_by_id[it["id"]] = it

    ref_dir = args.reference_dir.expanduser()
    ensure_reference_files(ref_dir)
    reference_wav, reference_wav_sha256 = build_reference_wav(ref_dir)

    model = load_model(args.device)

    manifest_items = []
    total_bytes = 0
    total_seconds = 0.0
    take_count = 0

    for index, item in enumerate(items):
        text_bytes = item["text"].encode("utf-8")
        text_sha256 = hashlib.sha256(text_bytes).hexdigest()

        if only_set and item["id"] not in only_set:
            old_item = existing_by_id.get(item["id"])
            if old_item is None:
                raise SystemExit(
                    f"error: item {item['id']} is not in the existing manifest, cannot reuse"
                )
            verified_takes = reuse_existing_takes(old_item, out_dir)
            entry = {
                "id": item["id"],
                "kind": item["kind"],
                "index": index,
                "text_sha256": text_sha256,
                "takes": verified_takes,
            }
        else:
            takes = []
            for take in range(item["takes"]):
                take_entry, size = render_take(
                    model, reference_wav, item["text"], item, index, take, out_dir
                )
                takes.append(take_entry)
                print(
                    f"{item['id']} take {take}: {take_entry['seconds']:.3f} s, {size} bytes"
                )
            entry = {
                "id": item["id"],
                "kind": item["kind"],
                "index": index,
                "text_sha256": text_sha256,
                "takes": takes,
            }

        manifest_items.append(entry)
        for take in entry["takes"]:
            total_seconds += take["seconds"]
            take_count += 1

    # Total bytes over every take, rendered or reused.
    for entry in manifest_items:
        for take in entry["takes"]:
            path = out_dir / take["file"]
            total_bytes += path.stat().st_size

    manifest = {
        "format": 1,
        "sample_rate": OUTPUT_SAMPLE_RATE,
        "initial_unlocked": initial_unlocked,
        "texts_sha256": texts_sha256,
        "generator": {
            "tool": "tools/maintainer/generate_maternal_voice.py",
            "chatterbox_tts": CHATTERBOX_VERSION,
            "model_repo": MODEL_REPO,
            "model_revision": MODEL_REVISION,
            "base_seed": BASE_SEED,
            "exaggeration": EXAGGERATION,
            "cfg_weight": CFG_WEIGHT,
            "temperature": TEMPERATURE,
            "trim_top_db": TRIM_TOP_DB,
            "target_rms_dbfs": TARGET_RMS_DBFS,
            "peak_ceiling_dbfs": PEAK_CEILING_DBFS,
            "watermark": "Chatterbox applies its Perth implicit watermark (resemble-perth) to every output before post-processing",
        },
        "reference_voice": {
            "attribution": REFERENCE_ATTRIBUTION,
            "files": [{"file": name, "sha256": digest} for name, digest in REFERENCE_FILES],
            "reference_wav_sha256": reference_wav_sha256,
        },
        "items": manifest_items,
        "total_bytes": total_bytes,
        "total_seconds": round(total_seconds, 3),
    }

    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    print(
        f"summary: {take_count} takes, {total_bytes} bytes, "
        f"{round(total_seconds, 3)} seconds -> {out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
