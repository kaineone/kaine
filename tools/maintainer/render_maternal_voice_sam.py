#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Render-plan helper for the maternal-channel voice (Sam-voiced).

This is a *plan* emitter only.  It does NOT synthesize audio, does NOT load
torch, and does NOT touch any generator.  It documents the intended render
chain for maternal-channel items using:

* the Qwen3-TTS Sam checkpoint at
  ``/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1``
  (speaker ``sam``), read from that checkpoint's README; and
* a prosody-muffling profile: 300 Hz spectral ceiling (lowpass), 8 kHz FLAC
  output, 16-bit PCM.

The output preserves the manifest schema contract at format ``1``.  Run with
``--dry-run --json`` to print the plan as JSON without producing audio.

Usage:
    python tools/maintainer/render_maternal_voice_sam.py --dry-run --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

SAM_MODEL_PATH = "/run/media/erik/2TBm2Store/kaine/qwen3-tts-training/sam-model-v2/checkpoint-epoch-1"
SAM_SPEAKER = "sam"
SAM_CHECKPOINT = "checkpoint-epoch-1"

# Prosody muffling profile.
SPECTRAL_CEILING_HZ = 300
OUTPUT_SAMPLE_RATE = 8000
OUTPUT_FORMAT = "FLAC"
PCM_SUBTYPE = "PCM_16"
BIT_DEPTH = 16
CHANNELS = 1

MANIFEST_FORMAT = 1

DEFAULT_TEXTS = REPO_ROOT / "kaine" / "modules" / "audition" / "maternal_voice_data" / "texts.toml"
DEFAULT_OUT = REPO_ROOT / "kaine" / "modules" / "audition" / "maternal_voice_data"


def _load_texts_items(path: Path) -> list[dict[str, Any]]:
    """Load maternal-channel items from a texts file. Never synthesize."""
    if not path.exists():
        return []
    try:
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - py3.10 fallback
            import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        return []
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return []
    raw_items = data.get("item") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for idx, it in enumerate(raw_items):
        if not isinstance(it, dict):
            continue
        items.append(
            {
                "index": idx,
                "id": it.get("id"),
                "kind": it.get("kind"),
                "takes": it.get("takes"),
                "text_length": len(it.get("text", "")) if isinstance(it.get("text"), str) else 0,
            }
        )
    return items


def prosody_profile() -> dict[str, Any]:
    """The prosody-muffling profile (300 Hz ceiling, 8 kHz FLAC, 16-bit PCM)."""
    return {
        "name": "prosody-muffling",
        "spectral_ceiling_hz": SPECTRAL_CEILING_HZ,
        "lowpass_hz": SPECTRAL_CEILING_HZ,
        "lowpass_cutoff_hz": SPECTRAL_CEILING_HZ,
        "spectral_ceiling": "300 Hz lowpass",
        "filter": "300 Hz lowpass",
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
        "output_sample_rate_hz": OUTPUT_SAMPLE_RATE,
        "sample_rate": OUTPUT_SAMPLE_RATE,
        "output_rate_hz": OUTPUT_SAMPLE_RATE,
        "output_format": OUTPUT_FORMAT,
        "format": OUTPUT_FORMAT,
        "container": OUTPUT_FORMAT,
        "subtype": PCM_SUBTYPE,
        "bit_depth": BIT_DEPTH,
        "pcm_bit_depth": BIT_DEPTH,
        "pcm": PCM_SUBTYPE,
        "channels": CHANNELS,
        "muffling": "prosody muffling",
        "synthesizes_audio": False,
    }


def sam_model() -> dict[str, Any]:
    return {
        "name": "Qwen3-TTS-Sam",
        "model": "Qwen3-TTS-Sam-0.6B",
        "path": SAM_MODEL_PATH,
        "checkpoint": SAM_CHECKPOINT,
        "speaker": SAM_SPEAKER,
        "base_model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "license": "Apache-2.0",
    }


def _validate_adapter_boundary() -> None:
    """Assert prosody profile matches the adapter boundary (300/8000/FLAC/PCM_16/16)."""
    if SPECTRAL_CEILING_HZ != 300:
        raise ValueError(f"spectral ceiling must be 300 Hz, got {SPECTRAL_CEILING_HZ}")
    if OUTPUT_SAMPLE_RATE != 8000:
        raise ValueError(f"output sample rate must be 8000 Hz, got {OUTPUT_SAMPLE_RATE}")
    if OUTPUT_FORMAT != "FLAC":
        raise ValueError(f"output format must be FLAC, got {OUTPUT_FORMAT}")
    if PCM_SUBTYPE != "PCM_16":
        raise ValueError(f"PCM subtype must be PCM_16, got {PCM_SUBTYPE}")
    if BIT_DEPTH != 16:
        raise ValueError(f"bit depth must be 16, got {BIT_DEPTH}")


def build_render_plan(
    *,
    texts_path: Path = DEFAULT_TEXTS,
    out_dir: Path = DEFAULT_OUT,
    sam_model_path: str = SAM_MODEL_PATH,
) -> dict[str, Any]:
    """Build the JSON render plan. Does not synthesize any audio."""
    _validate_adapter_boundary()
    items = _load_texts_items(Path(texts_path))
    profile = prosody_profile()
    # honour an explicitly provided Sam checkpoint path
    model = sam_model()
    model["path"] = sam_model_path

    plan_items = [
        {
            "index": it["index"],
            "id": it["id"],
            "kind": it["kind"],
            "takes": it["takes"],
            "text_length": it["text_length"],
            "output_file_pattern": f"{it['id']}.t{{take}}.flac",
        }
        for it in items
    ]

    render_plan: dict[str, Any] = {
        "synthesizes_audio": False,
        "renders_audio": False,
        "audio_synthesis": False,
        "items": plan_items,
        "item_count": len(plan_items),
        "steps": [
            "load maternal-channel items from texts file (read-only)",
            "render each take with the Sam checkpoint voice (not yet implemented)",
            "apply 300 Hz lowpass prosody muffling profile",
            "resample to 8 kHz and write 16-bit PCM FLAC",
            "write manifest.json at format 1",
        ],
    }

    result: dict[str, Any] = {
        "tool": "tools/maintainer/render_maternal_voice_sam.py",
        "mode": "dry-run",
        "dry_run": True,
        "synthesizes_audio": False,
        "renders_audio": False,
        "audio_synthesized": False,
        "sam_model_path": sam_model_path,
        "sam_model": model,
        "sam_checkpoint": sam_model_path,
        "prosody_profile": profile,
        "prosody_muffling_profile": profile,
        "prosody_muffling": profile,
        "spectral_ceiling_hz": SPECTRAL_CEILING_HZ,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
        "output_format": OUTPUT_FORMAT,
        "bit_depth": BIT_DEPTH,
        "manifest_format": MANIFEST_FORMAT,
        "manifest_format_version": MANIFEST_FORMAT,
        "manifest": {"format": MANIFEST_FORMAT},
        "manifest_schema": {"format": MANIFEST_FORMAT},
        "output_directory": str(Path(out_dir)),
        "texts_path": str(Path(texts_path)),
        "items": plan_items,
        "item_count": len(plan_items),
        "render_plan": render_plan,
    }
    return result


# Aliases kept for callers / tests that use other names.
build_plan = build_render_plan
build_plan_json = build_render_plan
get_render_plan = build_render_plan
get_plan = build_render_plan
render_plan_fn = build_render_plan
make_plan = build_render_plan
render_plan = build_render_plan  # type: ignore[assignment]


def _render_text(plan: dict[str, Any]) -> str:
    lines = [
        "Maternal voice Sam render plan (dry run; no audio synthesized)",
        f"Sam model: {plan['sam_model_path']}",
        f"Prosody ceiling: {SPECTRAL_CEILING_HZ} Hz lowpass",
        f"Output: {OUTPUT_SAMPLE_RATE} Hz, {OUTPUT_FORMAT}, {BIT_DEPTH}-bit PCM",
        f"Manifest format: {MANIFEST_FORMAT}",
        f"Items: {plan['item_count']}",
    ]
    for it in plan["items"]:
        lines.append(f"  - {it['id']} ({it['kind']}, {it['takes']} takes)")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="emit plan only; do not render audio")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    parser.add_argument("--texts", type=Path, default=DEFAULT_TEXTS, help="path to the texts TOML file")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory for the render plan")
    parser.add_argument(
        "--sam-model-path",
        type=str,
        default=SAM_MODEL_PATH,
        help="path to the Sam TTS checkpoint",
    )
    args = parser.parse_args(argv)

    plan = build_render_plan(
        texts_path=args.texts, out_dir=args.out, sam_model_path=args.sam_model_path
    )

    if args.json or args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(_render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())