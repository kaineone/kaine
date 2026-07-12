#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Build a KAINE playlist manifest (the reference stimulus corpus) from a media
source — a VLC ``.xspf`` playlist or a directory of media files.

The perception feed's playlist mode reads a manifest of ordered media items, each
pinned by sha256 (``kaine/modules/topos/feed.py``), and verifies files against it
fail-closed at open. This tool produces that manifest so a run's stimulus is
reproducible: anyone with the same publicly-archived media (identified by the
per-item sha256) can rebuild an identical manifest and drive the same stimulus.

Usage:
    python tools/build_playlist_manifest.py \\
        --xspf /path/to/Playlist.xspf \\
        --out  /path/to/reference-corpus.manifest.toml \\
        [--archive-id bbc-connections-1978]

    # or from a directory (sorted by filename):
    python tools/build_playlist_manifest.py --dir /path/to/media --out out.toml

Requires ``ffprobe`` (ffmpeg) on PATH to read each file's frame rate.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

_XSPF_NS = {"x": "http://xspf.org/ns/0/"}
_MEDIA_EXTS = {".mkv", ".mp4", ".webm", ".mov", ".avi", ".m4v"}


def _xspf_locations(xspf_path: Path) -> list[Path]:
    """Ordered local media paths from an XSPF ``<location>file://…</location>``."""
    root = ET.parse(xspf_path).getroot()
    out: list[Path] = []
    for loc in root.findall(".//x:track/x:location", _XSPF_NS):
        uri = (loc.text or "").strip()
        if not uri.startswith("file://"):
            continue
        # file:///home/... → /home/... , percent-decoded.
        local = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
        out.append(Path(local))
    return out


def _dir_media(dir_path: Path) -> list[Path]:
    return sorted(
        p for p in dir_path.rglob("*") if p.suffix.lower() in _MEDIA_EXTS
    )


def _sha256(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _fps(path: Path) -> float:
    """Average frame rate via ffprobe (falls back to 25.0 if unreadable)."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate",
                "-of", "default=nokey=1:noprint_wrappers=1", str(path),
            ],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        num, _, den = out.partition("/")
        fps = float(num) / float(den) if den and float(den) else float(num)
        return fps if fps > 0 else 25.0
    except Exception:
        return 25.0


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a KAINE playlist manifest.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--xspf", type=Path, help="VLC .xspf playlist to read order from.")
    src.add_argument("--dir", type=Path, help="Directory of media (sorted by name).")
    ap.add_argument("--out", type=Path, required=True, help="Manifest output path (.toml).")
    ap.add_argument("--archive-id", default="", help="Public archive identifier, recorded as a comment.")
    args = ap.parse_args(argv)

    items = _xspf_locations(args.xspf) if args.xspf else _dir_media(args.dir)
    if not items:
        print("no media found", file=sys.stderr)
        return 2

    lines = [
        "# KAINE reference stimulus corpus manifest (auto-generated).",
        "# Reproducibility is by per-item sha256: obtain the identical media and",
        "# the manifest verifies fail-closed at open.",
    ]
    if args.archive_id:
        lines.append(f"# archive-id: {args.archive_id}")
    lines.append("")

    for i, path in enumerate(items):
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            return 3
        print(f"[{i + 1}/{len(items)}] hashing {path.name} …", file=sys.stderr)
        sha = _sha256(path)
        fps = _fps(path)
        lines += [
            "[[item]]",
            f'path = "{_toml_escape(str(path))}"',
            f'sha256 = "{sha}"',
            f"fps = {fps:.6f}",
            f"order = {i}",
            "",
        ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(items)} items -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
