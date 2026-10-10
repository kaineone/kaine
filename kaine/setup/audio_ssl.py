# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consented, setup-time fetch of the Dasheng / WavJEPA encoder weights.

Mirrors :mod:`kaine.setup.internvideo_next`: each encoder's
``model.safetensors`` is fetched ONCE into a deterministic local dir under the
shared model-weights root, pinned to the same revision as the vendored modeling
code. Runtime loads only from the local dir, offline and with
``trust_remote_code=False``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from kaine.model_paths import models_dir
from kaine.modules.audition.ssl_encoders import PINS, WEIGHTS_SHA256, _sha256_file
from kaine.storage import resolve

WEIGHTS_FILENAME = "model.safetensors"

# One pin table, owned by the encoders that load the weights.


def _resolve_dir(name: str, local_dir: Path | None = None) -> Path:
    if local_dir is not None:
        return resolve(local_dir)
    return resolve(models_dir() / PINS[name][2])


def audio_ssl_download_cmd(name: str, *, local_dir: Path | None = None) -> list[str]:
    """Return the exact ``hf download`` argv for ``name``."""
    repo, revision, _ = PINS[name]
    return [
        "hf",
        "download",
        repo,
        WEIGHTS_FILENAME,
        "--revision",
        revision,
        "--local-dir",
        str(_resolve_dir(name, local_dir)),
    ]


def run_audio_ssl_download(
    name: str,
    *,
    consent: bool,
    runner: Any = None,
    local_dir: Path | None = None,
) -> tuple[bool, str]:
    """Run the REAL ``hf download`` for one encoder, gated on ``consent``.

    Writes the pinned revision to ``REVISION`` only after a successful download.
    Never fakes success and never runs without consent.
    """
    cmd = audio_ssl_download_cmd(name, local_dir=local_dir)
    if not consent:
        return False, "not consented; run the fetch yourself: " + " ".join(cmd)

    if shutil.which("hf") is None:
        return (
            False,
            "the Hugging Face CLI (`hf`) is not on PATH — install it then re-run: "
            + " ".join(cmd),
        )

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    run = runner if runner is not None else subprocess.run
    try:
        run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or exc.stdout or "").strip().splitlines()
        reason = tail[-1] if tail else f"exit {exc.returncode}"
        return False, f"download failed ({reason})"
    except Exception as exc:
        return False, f"could not run hf download ({type(exc).__name__}: {exc})"

    target_dir = _resolve_dir(name, local_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    weights = target_dir / WEIGHTS_FILENAME
    if not weights.exists():
        return False, f"download reported success but {weights} is missing"
    actual = _sha256_file(weights)
    if actual != WEIGHTS_SHA256[name]:
        # Leave no REVISION behind: the encoder refuses weights without one.
        return False, (
            f"{weights} sha256 {actual} does not match the pinned "
            f"{WEIGHTS_SHA256[name]}; not recording it"
        )
    (target_dir / "REVISION").write_text(PINS[name][1])
    return True, f"downloaded {WEIGHTS_FILENAME} for {name} (revision {PINS[name][1][:12]})"


def acquisition_guide(name: str) -> list[str]:
    """Operator-facing lines for one encoder."""
    repo, revision, _ = PINS[name]
    return [
        f"{name} encoder weights ({repo}, pinned {revision[:12]}):",
        "  " + " ".join(audio_ssl_download_cmd(name)),
        "Runtime loads only from the local dir with trust_remote_code=False; "
        "no network access at load time.",
    ]


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m kaine.setup.audio_ssl",
        description=(
            "Fetch the Dasheng / WavJEPA encoder weights once at setup into a "
            "git-ignored local dir (pinned revision). Runtime is fully local."
        ),
    )
    parser.add_argument("encoder", choices=list(PINS), help="which encoder to fetch")
    parser.add_argument(
        "--yes", action="store_true", help="consent to the real download"
    )
    args = parser.parse_args(argv)
    if not args.yes:
        for line in acquisition_guide(args.encoder):
            print(line)
        return 0
    ok, detail = run_audio_ssl_download(args.encoder, consent=True)
    print(detail)
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
