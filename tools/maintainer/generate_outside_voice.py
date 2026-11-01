#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Generate the outside voice of the KAINE developmental stimulus.

Offline maintainer script on the maternal-voice tool's pattern
(``generate_maternal_voice.py``): the same Chatterbox TTS version, model revision
and generation settings, a male reference speaker, original texts. It renders
every take of every item in ``kaine/modules/audition/added_sounds_data/texts.toml``,
writes trimmed, level-normalised, peak-limited 8 kHz mono FLAC files, and writes
the ``outside_voice`` section of ``manifest.json`` (each take's sha256, frame
count and seed, the settings and the reference attribution), keeping the
``melody`` section as it is. Run it in a GPU window with no entity running; it
also runs on the CPU (``--device cpu``), more slowly.

Usage:
    python tools/maintainer/generate_outside_voice.py [--data DIR]
        [--reference-dir DIR] [--device DEVICE] [--verify]

The rendered voice is not a recording of a real person. It is a neural TTS
rendering conditioned on the CMU ARCTIC "rms" speaker, a male US English speaker
recorded at Carnegie Mellon University for building speech-synthesis voices
(Kominek and Black 2003), from the same database and under the same notice as
the maternal voice's ``slt``. Of the database's male speakers rms has the lowest
fundamental (about 90 to 100 Hz in his recordings), so the rendering's lies below
stage 1's lower edge (about 158 Hz) and arrives with the 100 Hz step. Chatterbox applies its Perth implicit watermark
(resemble-perth) to every raw output before the post-processing here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from importlib.metadata import version as package_version
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, where Chatterbox 0.1.6 environments often live
    import tomli as tomllib

_HERE = Path(__file__).resolve().parent


def _maternal_tool():
    """The maternal-voice tool, for its pinned versions, settings and helpers."""
    spec = importlib.util.spec_from_file_location("generate_maternal_voice", _HERE / "generate_maternal_voice.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MV = _maternal_tool()
CHATTERBOX_VERSION = MV.CHATTERBOX_VERSION
MODEL_REPO = MV.MODEL_REPO
MODEL_REVISION = MV.MODEL_REVISION
MODEL_FILES = MV.MODEL_FILES
EXAGGERATION = MV.EXAGGERATION
CFG_WEIGHT = MV.CFG_WEIGHT
TEMPERATURE = MV.TEMPERATURE
TRIM_TOP_DB = MV.TRIM_TOP_DB
TARGET_RMS_DBFS = MV.TARGET_RMS_DBFS
PEAK_CEILING_DBFS = MV.PEAK_CEILING_DBFS
OUTPUT_SAMPLE_RATE = MV.OUTPUT_SAMPLE_RATE
BASE_SEED = 20261031
MAX_TAKE_SECONDS = 20.0
MANIFEST_FORMAT = 1
TOOL = "tools/maintainer/generate_outside_voice.py"
REFERENCE_BASE_URL = "http://festvox.org/cmu_arctic/cmu_arctic/cmu_us_rms_arctic/wav/"
REFERENCE_FILES = (
    ("arctic_a0001.wav", "728ae021d1f21042abe3cde8c9c100fd2ade82a5a5db56ae412b9c7d99355aa9"),
    ("arctic_a0003.wav", "c99fc0cd44894394e3c5f206928e5271e02162f55eca89e913a3e8baf94f15f3"),
    ("arctic_a0004.wav", "5b038c0b4acf5b5193e97274ac547f03ee399c2bd65cc08a29df80f263fedfa3"),
    ("arctic_a0005.wav", "3b6d28a4eb6b0feb56fb0f4f6eaca1e714d69119a824918c716620912ce011ea"),
    ("arctic_a0006.wav", "3a95b89e009f1d12d22a5cae34334298538312077e1f3feb2e32398a5838ab2d"),
    ("arctic_a0007.wav", "fbae396e0d4551972bc323f63d735a740414a29bf724d392a6a56be09fe78029"),
    ("arctic_a0008.wav", "afea5b1d2e7eaec58669972cfea04b306495ad7f7833ee419bb7f9859ed6db1b"),
)
REFERENCE_ATTRIBUTION = (
    "CMU ARCTIC speaker rms (Kominek and Black 2003), "
    "Carnegie Mellon University, http://www.festvox.org/cmu_arctic/"
)
_ID_RE = re.compile(r"^x[0-9]{2}-[a-z0-9-]+$")


def load_texts(path: Path):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    raw = data.get("item")
    if not isinstance(raw, list) or not raw:
        raise SystemExit("error: texts.toml must contain an array of tables named 'item'")
    seen, items = set(), []
    for idx, it in enumerate(raw):
        if not isinstance(it, dict) or set(it) != {"id", "takes", "text"}:
            raise SystemExit(f"error: item {idx} must have exactly id, takes and text")
        if not isinstance(it["id"], str) or not _ID_RE.fullmatch(it["id"]) or it["id"] in seen:
            raise SystemExit(f"error: item {idx} id must match ^x[0-9]{{2}}-[a-z0-9-]+$ and be unique")
        if not isinstance(it["takes"], int) or it["takes"] < 1:
            raise SystemExit(f"error: item {it['id']} takes must be an integer >= 1")
        if not isinstance(it["text"], str) or not it["text"] or "—" in it["text"] or "–" in it["text"]:
            raise SystemExit(f"error: item {it['id']} text must be non-empty with no dash characters")
        seen.add(it["id"])
        items.append(it)
    return items, MV.file_sha256(path)


def ensure_reference_files(ref_dir: Path) -> None:
    ref_dir.mkdir(parents=True, exist_ok=True)
    for name, expected in REFERENCE_FILES:
        path = ref_dir / name
        if path.exists():
            if MV.file_sha256(path) == expected:
                continue
            raise SystemExit(f"error: reference file {name} exists but its hash does not match; remove it manually")
        print(f"downloading reference {name} ...")
        MV.download_file(REFERENCE_BASE_URL + name, path)
        if MV.file_sha256(path) != expected:
            path.unlink(missing_ok=True)
            raise SystemExit(f"error: downloaded reference file {name} hash mismatch (expected {expected})")


def build_reference_wav(ref_dir: Path, librosa, np, soundfile):
    segments, sr = [], None
    for name, _ in REFERENCE_FILES:
        y, file_sr = librosa.load(str(ref_dir / name), sr=None, mono=True)
        if sr is None:
            sr = file_sr
        elif file_sr != sr:
            raise SystemExit(f"error: reference file {name} sample rate {file_sr} differs from {sr}")
        segments += [y, np.zeros(int(sr * 0.3), dtype=y.dtype)]
    segments.pop()
    out = ref_dir / "rms-reference.wav"
    soundfile.write(str(out), np.concatenate(segments), sr, subtype="PCM_16")
    return out, MV.file_sha256(out)


def render_take(model, reference_wav: Path, item: dict, index: int, take: int, out_dir: Path, mods):
    random, np, torch, librosa, soundfile = mods
    seed = BASE_SEED + 1000 * index + take
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    print(f"generating {item['id']} take {take} (seed {seed}) ...")
    wav = model.generate(
        item["text"],
        audio_prompt_path=str(reference_wav),
        exaggeration=EXAGGERATION,
        cfg_weight=CFG_WEIGHT,
        temperature=TEMPERATURE,
    ).squeeze(0).cpu().numpy().astype("float64")
    trimmed, _ = librosa.effects.trim(wav, top_db=TRIM_TOP_DB)
    if trimmed.size < int(0.3 * model.sr):
        raise SystemExit(f"error: {item['id']} take {take} is shorter than 0.3 s after trimming")
    resampled = librosa.resample(trimmed, orig_sr=model.sr, target_sr=OUTPUT_SAMPLE_RATE, res_type="soxr_hq")
    seconds = resampled.size / OUTPUT_SAMPLE_RATE
    if seconds > MAX_TAKE_SECONDS:
        raise SystemExit(f"error: {item['id']} take {take} is {seconds:.1f} s, above {MAX_TAKE_SECONDS} s")
    rms = float(np.sqrt(np.mean(resampled**2)))
    if rms == 0.0:
        raise SystemExit(f"error: {item['id']} take {take} has zero RMS")
    scaled = resampled * (10 ** (TARGET_RMS_DBFS / 20.0) / rms)
    peak = float(np.max(np.abs(scaled)))
    if peak > 0.0 and 20 * math.log10(peak) > PEAK_CEILING_DBFS:
        scaled = scaled * (10 ** (PEAK_CEILING_DBFS / 20.0) / peak)
    pcm = np.clip(np.round(scaled * 32767.0), -32768, 32767).astype(np.int16)
    out = out_dir / f"{item['id']}.t{take}.flac"
    soundfile.write(str(out), pcm, OUTPUT_SAMPLE_RATE, format="FLAC", subtype="PCM_16")
    final_rms = float(np.sqrt(np.mean((pcm / 32767.0) ** 2)))
    return {
        "take": take,
        "file": out.name,
        "sha256": MV.file_sha256(out),
        "frames": int(pcm.size),
        "seconds": round(pcm.size / OUTPUT_SAMPLE_RATE, 3),
        "seed": seed,
        "rms_dbfs": round(20 * math.log10(final_rms), 2) if final_rms > 0 else None,
    }


def verify(data_dir: Path) -> int:
    path = data_dir / "manifest.json"
    if not path.exists():
        print(f"error: no manifest.json in {data_dir}", file=sys.stderr)
        return 1
    manifest = json.loads(path.read_text(encoding="utf-8"))
    section = manifest.get("outside_voice")
    if not isinstance(section, dict):
        print("error: the manifest has no outside_voice section; render it first", file=sys.stderr)
        return 1
    problems, n = [], 0
    for item in section.get("items", []):
        for take in item.get("takes", []):
            n += 1
            f = data_dir / take["file"]
            if not f.is_file():
                problems.append(f"missing file: {take['file']}")
            elif MV.file_sha256(f) != take["sha256"]:
                problems.append(f"hash mismatch: {take['file']}")
    if problems:
        print("verification failed:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"verified {n} outside-voice takes in {data_dir}")
    return 0


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Generate the developmental stimulus's outside voice.")
    parser.add_argument(
        "--data", type=Path, default=repo_root / "kaine" / "modules" / "audition" / "added_sounds_data",
        help="the added-sounds data directory (texts.toml in, FLAC files and manifest.json out)",
    )
    parser.add_argument(
        "--reference-dir", type=Path, default=Path.home() / ".cache" / "kaine" / "outside-voice-reference",
        help="directory for the reference WAV files (default: ~/.cache/kaine/outside-voice-reference)",
    )
    parser.add_argument("--device", default="cuda", help="torch device for ChatterboxTTS (default: cuda)")
    parser.add_argument("--verify", action="store_true", help="verify the shipped takes against the manifest")
    args = parser.parse_args()
    data_dir = args.data.expanduser()
    if args.verify:
        return verify(data_dir)

    import random

    import librosa
    import numpy as np
    import soundfile
    import torch
    from chatterbox.tts import ChatterboxTTS
    from huggingface_hub import hf_hub_download

    installed = package_version("chatterbox-tts")
    if installed != CHATTERBOX_VERSION:
        raise SystemExit(f"error: chatterbox-tts {installed} installed, {CHATTERBOX_VERSION} expected")

    texts_path = data_dir / "texts.toml"
    items, texts_sha256 = load_texts(texts_path)
    ref_dir = args.reference_dir.expanduser()
    ensure_reference_files(ref_dir)
    reference_wav, reference_sha256 = build_reference_wav(ref_dir, librosa, np, soundfile)

    paths = [hf_hub_download(repo_id=MODEL_REPO, filename=f, revision=MODEL_REVISION) for f in MODEL_FILES]
    print(f"loading ChatterboxTTS from {Path(paths[0]).parent} on {args.device} ...")
    model = ChatterboxTTS.from_local(str(Path(paths[0]).parent), args.device)

    mods = (random, np, torch, librosa, soundfile)
    manifest_items = []
    for index, item in enumerate(items):
        takes = [render_take(model, reference_wav, item, index, t, data_dir, mods) for t in range(item["takes"])]
        for t in takes:
            print(f"{item['id']} take {t['take']}: {t['seconds']:.3f} s")
        manifest_items.append(
            {
                "id": item["id"],
                "index": index,
                "text_sha256": hashlib.sha256(item["text"].encode("utf-8")).hexdigest(),
                "takes": takes,
            }
        )

    manifest_path = data_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"format": MANIFEST_FORMAT, "sample_rate": OUTPUT_SAMPLE_RATE}
    if manifest.get("format") != MANIFEST_FORMAT or manifest.get("sample_rate") != OUTPUT_SAMPLE_RATE:
        raise SystemExit("error: existing manifest has another format or sample rate")
    manifest["outside_voice"] = {
        "texts_sha256": texts_sha256,
        "generator": {
            "tool": TOOL,
            "chatterbox_tts": CHATTERBOX_VERSION,
            "model_repo": MODEL_REPO,
            "model_revision": MODEL_REVISION,
            "base_seed": BASE_SEED,
            "device": args.device,
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
            "files": [{"file": n, "sha256": d} for n, d in REFERENCE_FILES],
            "reference_wav_sha256": reference_sha256,
        },
        "citation": "Querleu, Renard, Versyp, Paris-Delrue and Crepin 1988, Eur J Obstet Gynecol Reprod Biol 28(3): 191-212",
        "items": manifest_items,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    total = sum(t["seconds"] for it in manifest_items for t in it["takes"])
    print(f"summary: {sum(len(it['takes']) for it in manifest_items)} takes, {total:.1f} s -> {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
