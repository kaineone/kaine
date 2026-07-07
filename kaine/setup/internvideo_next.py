# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consented, setup-time fetch of the InternVideo-Next encoder weights.

Topos's temporally-native video encoder (topos-temporal-video-encoder change) is
the frozen InternVideo-Next base checkpoint. A fresh clone has NO weights: the
~182 MB fp16 ``model.safetensors`` is fetched ONCE at setup time into a
deterministic, git-ignored local dir under ``state/models/`` — mirroring the
language-organ GGUF fetch (:mod:`kaine.setup.organ`) — so runtime is fully local:
:mod:`kaine.modules.topos.internvideo_next_loader` loads only from this dir and
NEVER touches the network.

Only ``model.safetensors`` is fetched here — the modeling code
(``modeling_internvideo_next.py`` etc.) is VENDORED in ``external/internvideo_next/``
at the same pinned revision and loaded from there with ``trust_remote_code=False``,
so no Python is ever fetched or executed from the hub. The fetch is pinned to the
same commit SHA as the vendored code (``PINNED_REVISION``); the loader treats a
weights snapshot at any other revision as a load-time error.

No pretend processes: a fetch is a REAL ``hf download`` or it fails honestly; with
``consent=False`` nothing runs and the exact command is printed for the operator
to run themselves. ``HF_HUB_DISABLE_TELEMETRY=1`` is set before any hub call
(CAL no-outbound guarantee), matching the DINOv2 / organ loaders.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from kaine.modules.topos.internvideo_next_loader import (
    DEFAULT_WEIGHTS_DIR,
    PINNED_REVISION,
    WEIGHTS_FILENAME,
)

# The published HF model repo (MIT, OpenGVLab InternVideo-Next base).
INTERNVIDEO_NEXT_REPO = "revliter/internvideo_next_base_p14_res224_f16"

# Rough download size (GiB) for the operator-facing "bytes up front" message.
# Honest estimate; ``hf download`` reports the real bytes as it runs.
_WEIGHTS_SIZE_GB = 0.18


def internvideo_next_download_cmd(
    *,
    repo: str = INTERNVIDEO_NEXT_REPO,
    revision: str = PINNED_REVISION,
    local_dir: Path = DEFAULT_WEIGHTS_DIR,
    filename: str = WEIGHTS_FILENAME,
) -> list[str]:
    """The exact ``hf download`` argv: the single safetensors file, pinned to the
    vendored revision, into the deterministic git-ignored local dir.

    ``--local-dir`` makes the landing path known and stable (independent of the
    hub-cache snapshot layout) so the loader can point at it directly; ``--revision``
    pins the same commit SHA as the vendored modeling code."""
    return [
        "hf", "download", repo, filename,
        "--revision", revision,
        "--local-dir", str(local_dir),
    ]


@dataclass
class InternVideoNextFetchResult:
    """Outcome of the weights fetch. ``ok`` is honest — a real download succeeded,
    or it did not (never a faked success)."""

    ok: bool
    detail: str = ""
    path: Optional[Path] = None


def run_internvideo_next_download(
    *,
    consent: bool,
    revision: str = PINNED_REVISION,
    local_dir: Path = DEFAULT_WEIGHTS_DIR,
    runner: Any = None,
) -> InternVideoNextFetchResult:
    """Run the REAL ``hf download`` of the encoder weights, gated on ``consent``.

    With ``consent=False`` nothing runs and the operator is handed the exact command
    (``ok=False``, guide in ``detail``). The ``hf`` CLI must be on PATH; if it is
    absent this reports an honest failure (no faked success). Sets
    ``HF_HUB_DISABLE_TELEMETRY=1`` before the call. Never raises — a failed download
    is reported as ``ok=False``.

    ``runner`` defaults to ``subprocess.run`` (overridable in tests; the production
    path always invokes the real CLI)."""
    cmd = internvideo_next_download_cmd(revision=revision, local_dir=local_dir)
    if not consent:
        return InternVideoNextFetchResult(
            ok=False,
            detail="not consented; run the fetch yourself: " + " ".join(cmd),
        )
    if shutil.which("hf") is None:
        return InternVideoNextFetchResult(
            ok=False,
            detail=(
                "the Hugging Face CLI (`hf`) is not on PATH — install it "
                "(`pip install -U huggingface_hub`) then re-run: " + " ".join(cmd)
            ),
        )

    # CAL no-outbound guarantee: suppress HF telemetry before any hub call.
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    run = runner if runner is not None else subprocess.run
    try:
        run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or exc.stdout or "").strip().splitlines()
        reason = tail[-1] if tail else f"exit {exc.returncode}"
        return InternVideoNextFetchResult(
            ok=False, detail=f"download failed ({reason})"
        )
    except Exception as exc:  # OSError launching, etc.
        return InternVideoNextFetchResult(
            ok=False,
            detail=f"could not run hf download ({type(exc).__name__}: {exc})",
        )
    return InternVideoNextFetchResult(
        ok=True,
        detail=f"downloaded {WEIGHTS_FILENAME} (revision {revision})",
        path=Path(local_dir) / WEIGHTS_FILENAME,
    )


def acquisition_guide() -> list[str]:
    """Operator-facing lines: the repo, the size, and the exact command to run."""
    return [
        f"InternVideo-Next encoder weights ({INTERNVIDEO_NEXT_REPO}, MIT, "
        f"~{_WEIGHTS_SIZE_GB * 1024:.0f} MB, pinned {PINNED_REVISION[:12]}):",
        "  " + " ".join(internvideo_next_download_cmd()),
        "Runtime loads only from the local dir with trust_remote_code=False; no "
        "network access at load time.",
    ]


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.internvideo_next",
        description=(
            "Fetch the InternVideo-Next encoder weights once at setup into a "
            "git-ignored local dir (pinned revision). Runtime is fully local."
        ),
    )
    parser.add_argument(
        "--yes", action="store_true", help="consent to the real download"
    )
    args = parser.parse_args(argv)
    if not args.yes:
        for line in acquisition_guide():
            print(line)
        return 0
    result = run_internvideo_next_download(consent=True)
    print(result.detail)
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
