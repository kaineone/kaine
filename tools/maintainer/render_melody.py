#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Render the recurring melody of the KAINE developmental stimulus.

Offline maintainer script. It reads the note list in
``kaine/modules/audition/added_sounds_data/melody.toml`` and renders one take per
beat length: each note a harmonic tone (``partials`` partials with amplitude 1/k)
under a smooth envelope (raised-cosine attack, gentle decay, linear release), 8 kHz
mono 16-bit FLAC, normalised to -20 dBFS RMS with peaks at most -1 dBFS. It then
writes the ``melody`` section of ``manifest.json`` (each take's sha256, frame count
and settings), keeping the ``outside_voice`` section as it is. The runtime reads
only the files the manifest lists and never synthesizes the melody.

The rendering is deterministic: no random numbers are drawn. Which take a slot
plays and at what level is decided at runtime from the run seed and the slot.

Usage:
    python tools/maintainer/render_melody.py [--data DIR] [--verify]

The melody is the one Partanen et al. (2013) had mothers play in the last
trimester ("Twinkle, Twinkle, Little Star", G major), a traditional public-domain
tune.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tomllib
from pathlib import Path

OUTPUT_SAMPLE_RATE = 8000
TARGET_RMS_DBFS = -20.0
PEAK_CEILING_DBFS = -1.0
ATTACK_SECONDS = 0.02
RELEASE_SECONDS = 0.06
ARTICULATION_GAP_SECONDS = 0.04
MANIFEST_FORMAT = 1
TOOL = "tools/maintainer/render_melody.py"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1_048_576), b""):
            h.update(chunk)
    return h.hexdigest()


def load_melody(path: Path) -> dict:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    notes = data.get("notes")
    if not isinstance(notes, list) or not notes:
        raise SystemExit("error: melody.toml needs a non-empty 'notes' list")
    for i, note in enumerate(notes):
        if (
            not isinstance(note, list)
            or len(note) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in note)
            or note[1] < 1
        ):
            raise SystemExit(f"error: note {i} must be [MIDI number, beats >= 1]")
    beats = data.get("beat_seconds")
    if not isinstance(beats, list) or not beats or not all(isinstance(b, float) and 0.2 <= b <= 1.0 for b in beats):
        raise SystemExit("error: beat_seconds must be a non-empty list of floats in [0.2, 1.0]")
    partials = data.get("partials")
    if not isinstance(partials, int) or not 1 <= partials <= 16:
        raise SystemExit("error: partials must be an int in [1, 16]")
    return data


def midi_hz(m: int) -> float:
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def render_variant(np, notes: list, beat_seconds: float, partials: int, sr: int):
    """Return the float64 waveform of one take (not yet level-normalised)."""
    parts = []
    for midi, beats in notes:
        f0 = midi_hz(midi)
        slot = int(round(beats * beat_seconds * sr))
        n = slot - int(round(ARTICULATION_GAP_SECONDS * sr))
        t = np.arange(n, dtype=np.float64) / sr
        tone = np.zeros(n, dtype=np.float64)
        for k in range(1, partials + 1):
            if k * f0 < sr / 2.0:
                tone += np.sin(2.0 * math.pi * k * f0 * t) / k
        duration = n / sr
        env = np.exp(-t / (1.2 * duration + 0.2))
        a = int(round(ATTACK_SECONDS * sr))
        r = int(round(RELEASE_SECONDS * sr))
        env[:a] *= 0.5 - 0.5 * np.cos(math.pi * np.arange(a) / a)
        env[-r:] *= np.linspace(1.0, 0.0, r)
        parts.append(tone * env)
        parts.append(np.zeros(slot - n, dtype=np.float64))
    return np.concatenate(parts)


def normalise_to_int16(np, x):
    rms = float(np.sqrt(np.mean(x * x)))
    if rms == 0.0:
        raise SystemExit("error: silent melody take")
    y = x * (10 ** (TARGET_RMS_DBFS / 20.0) / rms)
    peak = float(np.max(np.abs(y)))
    ceiling = 10 ** (PEAK_CEILING_DBFS / 20.0)
    if peak > ceiling:
        y = y * (ceiling / peak)
    return np.clip(np.round(y * 32767.0), -32768, 32767).astype(np.int16)


def read_manifest(data_dir: Path) -> dict:
    path = data_dir / "manifest.json"
    if not path.exists():
        return {"format": MANIFEST_FORMAT, "sample_rate": OUTPUT_SAMPLE_RATE}
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(data_dir: Path, manifest: dict) -> None:
    path = data_dir / "manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


def verify(data_dir: Path) -> int:
    """Check every file the manifest lists (melody and outside voice). 0 on success."""
    path = data_dir / "manifest.json"
    if not path.exists():
        print(f"error: no manifest.json in {data_dir}", file=sys.stderr)
        return 1
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = list((manifest.get("melody") or {}).get("takes", []))
    for item in (manifest.get("outside_voice") or {}).get("items", []):
        entries.extend(item.get("takes", []))
    problems = []
    for entry in entries:
        f = data_dir / entry["file"]
        if not f.is_file():
            problems.append(f"missing file: {entry['file']}")
        elif file_sha256(f) != entry["sha256"]:
            problems.append(f"hash mismatch: {entry['file']}")
    if problems:
        print("verification failed:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"verified {len(entries)} takes in {data_dir}")
    return 0


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Render the developmental stimulus's recurring melody.")
    parser.add_argument(
        "--data",
        type=Path,
        default=repo_root / "kaine" / "modules" / "audition" / "added_sounds_data",
        help="the added-sounds data directory (melody.toml in, FLAC files and manifest.json out)",
    )
    parser.add_argument("--verify", action="store_true", help="verify the shipped files against the manifest")
    args = parser.parse_args()
    data_dir = args.data.expanduser()
    if args.verify:
        return verify(data_dir)

    import numpy as np
    import soundfile

    melody_path = data_dir / "melody.toml"
    melody = load_melody(melody_path)
    notes = melody["notes"]
    lo = min(midi_hz(m) for m, _ in notes)
    hi = max(midi_hz(m) for m, _ in notes)

    takes = []
    for index, beat in enumerate(melody["beat_seconds"]):
        x = render_variant(np, notes, beat, melody["partials"], OUTPUT_SAMPLE_RATE)
        pcm = normalise_to_int16(np, x)
        out = data_dir / f"melody.b{index}.flac"
        soundfile.write(str(out), pcm, OUTPUT_SAMPLE_RATE, format="FLAC", subtype="PCM_16")
        takes.append(
            {
                "take": index,
                "file": out.name,
                "sha256": file_sha256(out),
                "frames": int(pcm.size),
                "seconds": round(pcm.size / OUTPUT_SAMPLE_RATE, 3),
                "beat_seconds": beat,
            }
        )
        print(f"{out.name}: {pcm.size / OUTPUT_SAMPLE_RATE:.3f} s at {beat} s per beat")

    manifest = read_manifest(data_dir)
    if manifest.get("format") != MANIFEST_FORMAT or manifest.get("sample_rate") != OUTPUT_SAMPLE_RATE:
        raise SystemExit("error: existing manifest has another format or sample rate")
    manifest["melody"] = {
        "title": melody["title"],
        "key": melody["key"],
        "melody_toml_sha256": file_sha256(melody_path),
        "fundamental_range_hz": [round(lo, 2), round(hi, 2)],
        "generator": {
            "tool": TOOL,
            "partials": melody["partials"],
            "attack_seconds": ATTACK_SECONDS,
            "release_seconds": RELEASE_SECONDS,
            "articulation_gap_seconds": ARTICULATION_GAP_SECONDS,
            "target_rms_dbfs": TARGET_RMS_DBFS,
            "peak_ceiling_dbfs": PEAK_CEILING_DBFS,
        },
        "citation": "Partanen, Kujala, Tervaniemi and Huotilainen 2013, PLoS ONE 8(10): e78946",
        "takes": takes,
    }
    write_manifest(data_dir, manifest)
    print(f"wrote the melody section of {data_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
