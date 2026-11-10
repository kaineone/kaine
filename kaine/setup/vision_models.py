# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consent-gated, pinned and verified fetcher for vision ONNX models.

Vision models are standalone ONNX files (not tar archives like the speech
models).  Each is pinned by URL, size and sha256, and is stored under
``models_dir() / "vision" / <filename>``.  A successful install writes a
``.verified`` marker beside the ONNX file.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from kaine.model_paths import models_dir, vision_model_path
from kaine.vision_manifest import (
    VISION_MANIFEST,
    VisionModel,
    _sha256_file,
    is_installed,
)


@dataclass(frozen=True)
class FetchResult:
    model_id: str
    ok: bool
    detail: str = ""
    path: Path | None = None


def describe(model_id: str) -> str:
    model = VISION_MANIFEST.get(model_id)
    if model is None:
        return f"{model_id}: unknown model"
    mb = model.size_bytes / 1_000_000
    return f"{model.id}: {model.title}, {mb:.1f} MB, {model.licence}"


def _default_downloader(
    url: str, dest_path: str, *, max_bytes: int | None = None
) -> None:
    total = 0
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest_path, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ValueError("download exceeded the pinned size")
            f.write(chunk)


def _write_verified_marker(model: VisionModel, onnx_path: Path) -> None:
    marker = {
        "model_id": model.id,
        "sha256": model.sha256,
        "size_bytes": model.size_bytes,
    }
    marker_path = onnx_path.with_suffix(".verified")
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2, sort_keys=True)


def fetch(
    model_id: str,
    *,
    root: Path | str | None = None,
    downloader: Callable[[str, str], None] | None = None,
) -> FetchResult:
    model = VISION_MANIFEST.get(model_id)
    if model is None:
        return FetchResult(model_id=model_id, ok=False, detail=f"unknown model id: {model_id}")

    if is_installed(model_id, root):
        target = vision_model_path(model_id, root)
        return FetchResult(model_id=model_id, ok=True, detail="already installed", path=target)

    root_path = Path(root) if root else models_dir()
    vision_dir = root_path / "vision"
    vision_dir.mkdir(parents=True, exist_ok=True)
    target = vision_dir / model.filename

    try:
        if downloader is None:
            _default_downloader(model.url, str(target), max_bytes=model.size_bytes)
        else:
            downloader(model.url, str(target))
    except Exception as exc:
        target.unlink(missing_ok=True)
        return FetchResult(model_id=model_id, ok=False, detail=f"download failed: {exc}")

    actual_size = target.stat().st_size
    if actual_size != model.size_bytes:
        target.unlink(missing_ok=True)
        return FetchResult(
            model_id=model_id,
            ok=False,
            detail=f"size mismatch: expected {model.size_bytes}, got {actual_size}",
        )

    actual_hash = _sha256_file(target)
    if actual_hash != model.sha256:
        target.unlink(missing_ok=True)
        return FetchResult(
            model_id=model_id,
            ok=False,
            detail=f"sha256 mismatch: expected {model.sha256}, got {actual_hash}",
        )

    _write_verified_marker(model, target)
    return FetchResult(model_id=model_id, ok=True, detail="installed", path=target)


def required_vision_models(config: dict) -> list[str]:
    """Return the vision model ids the config needs."""
    ids: list[str] = []
    vision = config.get("vision") or {}
    if bool(vision.get("face_detection_enabled", False)):
        ids.append("yunet")
        ids.append("sface")
    if bool(vision.get("face_expression_enabled", False)):
        ids.append("fer")
    if bool(vision.get("gaze_enabled", False)):
        backend = str(vision.get("gaze_backend", "landmark")).strip().lower()
        if backend == "learned":
            ids.append("gaze-mobilenetv2")
    return ids


def main(
    argv: list[str] | None = None,
    input_fn: Callable[[str], str] = input,
    downloader: Callable[[str, str], None] | None = None,
) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.vision_models",
        description="Fetch pinned vision ONNX model weights.",
    )
    parser.add_argument("--models", nargs="*", metavar="ID", help="model ids to fetch")
    parser.add_argument("--yes", action="store_true", help="skip confirmation")
    parser.add_argument("--root", metavar="DIR", default=None, help="models root directory")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else None
    selected = list(args.models) if args.models else list(VISION_MANIFEST.keys())

    for mid in selected:
        if mid not in VISION_MANIFEST:
            print(f"unknown vision model id: {mid}", file=sys.stderr)
            return 2

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
