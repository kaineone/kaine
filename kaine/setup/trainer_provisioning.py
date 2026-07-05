# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hardware-aware sleep-cycle voice-alignment trainer provisioning.

The voice-alignment trainer runs unsloth out-of-process in an operator-configured
interpreter (``[hypnos.voice_alignment].trainer_python``; see the
``external-unsloth-trainer`` change). Which unsloth a host needs is
hardware-dependent, per unsloth's documentation:

  - ``cuda`` (NVIDIA): **Unsloth Studio**, a self-contained external env;
  - ``rocm`` (AMD): **unsloth-core** in a separate env;
  - ``xpu``/``mps``/``cpu``: no GPU trainer — sleep-cycle voice-alignment training
    is unavailable on this host (the phase stays off; the
    consolidation-divergence metric still emits without training).

**Qwen3.5 requires transformers v5 in the trainer env.** Unsloth Studio ships
with transformers 4.x by default, which does not recognise the ``qwen3_5``
model type and has no ``trust_remote_code`` fallback (the repos ship no custom
modeling code). Before running a voice-alignment training cycle against a Qwen3.5
base model, upgrade the trainer env::

    pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo

This pulls transformers v5 as a dependency. Prefer this over the Studio's own
``unsloth studio update`` command because the latter re-triggers a buggy
llama.cpp prebuilt step (``--simple-policy`` arg error) that silently degrades
to a CPU-only fallback. The force-reinstall may shift torch from a cuXXX build
to a PyPI default build (e.g. cu130→cu128) — that is functional and
forward-compatible, not a problem.

**GGUFs must be exported with mainline llama.cpp, not Ollama's converter.**
Ollama's GGUF converter produces a non-standard ``qwen35.rope.dimension_sections``
layout that mainline llama.cpp and Unsloth Studio cannot load
(``rope.dimension_sections`` length mismatch). Export the Qwen3.5 HF weights
with ``convert_hf_to_gguf.py`` from the mainline `ggerganov/llama.cpp` repo.
GGUFs copied from Ollama's blob store will fail to load.

This module mirrors the detect-and-guide pattern in
:mod:`kaine.setup.dependencies`: it maps the detected GPU vendor
(``kaine.hardware.describe_host()["backend"]``) to honest guidance (a doc URL +
ordered steps) and runs a **real** detection probe — does the candidate
interpreter exist AND can it ``import unsloth``? — via an explicit-argv
subprocess with no shell and a timeout. It NEVER auto-installs the multi-GB
trainer environment and NEVER fakes a probe result. A probe that cannot run
reports not-found honestly rather than guessing.

Nothing here imports ``unsloth`` in the entity-runtime venv (it is not installed
there); the import check runs only inside the *candidate external interpreter*.
The transformers-version check runs the same way — in the candidate interpreter
only, never in this venv.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

#: The standard self-contained Unsloth Studio interpreter location for a CUDA
#: host. ``~``-relative (not a personal path); the wizard tries it when the
#: operator has not configured ``trainer_python``.
STUDIO_DEFAULT_INTERPRETER = (
    Path.home() / ".unsloth" / "studio" / "unsloth_studio" / "bin" / "python"
)

#: Wall-clock ceiling for the ``import unsloth`` probe (seconds). Importing the
#: heavy trainer stack is slow but bounded; a hung interpreter must not stall
#: setup.
PROBE_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class TrainerGuidance:
    """Vendor-appropriate guidance for the external voice-alignment trainer env.

    ``available`` is False on a host with no CUDA/ROCm GPU: there is no GPU
    trainer to provision, so the wizard reports training unavailable rather than
    pointing at an install that cannot work. When ``available`` is True, ``name``
    / ``guide_url`` / ``guide_steps`` describe the unsloth the hardware supports.
    """

    backend: str
    available: bool
    name: str
    summary: str
    guide_url: str = ""
    guide_steps: tuple[str, ...] = ()


# CUDA (NVIDIA) → Unsloth Studio; ROCm (AMD) → unsloth-core. Everything else has
# no GPU trainer.
_CUDA_GUIDANCE = TrainerGuidance(
    backend="cuda",
    available=True,
    name="Unsloth Studio",
    summary=(
        "NVIDIA/CUDA host — use Unsloth Studio, a self-contained external "
        "trainer environment."
    ),
    guide_url="https://docs.unsloth.ai/get-started/installing-+-updating",
    guide_steps=(
        "Install Unsloth Studio in its OWN environment (NOT the KAINE venv) "
        "following the docs above.",
        "It is a multi-GB stack (unsloth + torch + CUDA); the wizard never "
        "auto-installs it.",
        "Its interpreter typically lands at "
        "~/.unsloth/studio/unsloth_studio/bin/python.",
        "REQUIRED for Qwen3.5: upgrade transformers to v5 inside the Studio "
        "env before training — the shipped transformers 4.x does not recognise "
        "the qwen3_5 model type. Run inside the Studio env: "
        "pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo",
        "Point [hypnos.voice_alignment].trainer_python at that interpreter "
        "(the wizard offers to set it once detected).",
    ),
)

_ROCM_GUIDANCE = TrainerGuidance(
    backend="rocm",
    available=True,
    name="unsloth-core",
    summary=(
        "AMD/ROCm host — Unsloth Studio targets NVIDIA; per unsloth's docs AMD "
        "GPUs use unsloth-core in a separate environment."
    ),
    guide_url="https://docs.unsloth.ai/basics/amd-gpus",
    guide_steps=(
        "Create a separate environment with a ROCm torch build (NOT the KAINE "
        "venv).",
        "Install unsloth-core (the AMD-supported unsloth) into that env per the "
        "docs above; the wizard never auto-installs it.",
        "Point [hypnos.voice_alignment].trainer_python at that env's python "
        "(the wizard offers to set it once detected).",
    ),
)


def _unavailable_guidance(backend: str) -> TrainerGuidance:
    return TrainerGuidance(
        backend=backend,
        available=False,
        name="",
        summary=(
            "No CUDA/ROCm GPU detected — the sleep-cycle voice-alignment GPU "
            "trainer needs CUDA (NVIDIA) or ROCm (AMD), so voice-alignment "
            "training is unavailable on this host. The phase stays off; the "
            "consolidation-divergence metric still emits without training."
        ),
    )


def trainer_guidance(backend: str) -> TrainerGuidance:
    """Map a ``describe_host()["backend"]`` value to trainer guidance.

    ``cuda`` → Unsloth Studio, ``rocm`` → unsloth-core, anything else
    (``xpu``/``mps``/``cpu``/unknown) → an honest "training unavailable on this
    host" guidance object (not an error).
    """
    if backend == "cuda":
        return _CUDA_GUIDANCE
    if backend == "rocm":
        return _ROCM_GUIDANCE
    return _unavailable_guidance(backend)


def _candidate_interpreter(
    interpreter: Union[str, Path, None], backend: str
) -> Optional[Path]:
    """Resolve the interpreter path to probe.

    Uses the explicit ``interpreter`` when given; otherwise falls back to the
    known Studio default for a CUDA host. Returns None when there is no sensible
    candidate (e.g. ROCm with no configured path — unsloth-core has no fixed
    location).
    """
    if interpreter:
        return Path(interpreter)
    if backend == "cuda":
        return STUDIO_DEFAULT_INTERPRETER
    return None


def probe_trainer(
    interpreter: Union[str, Path, None],
    *,
    backend: str = "cuda",
    timeout_s: float = PROBE_TIMEOUT_S,
) -> tuple[bool, str]:
    """Real detection probe for a usable external unsloth trainer interpreter.

    Resolves the candidate interpreter (the given path, else the known Studio
    default for a CUDA host), and reports found iff that interpreter EXISTS and
    running ``<python> -c "import unsloth"`` with an explicit argv (no shell) and
    a timeout exits 0. Never imports unsloth in this (KAINE) venv; never raises —
    any failure to launch/run reports not-found with a reason.

    Returns ``(found, detail)`` where ``detail`` is the resolved path plus the
    reason it is or is not usable.
    """
    candidate = _candidate_interpreter(interpreter, backend)
    if candidate is None:
        return (
            False,
            "no candidate interpreter (set "
            "[hypnos.voice_alignment].trainer_python to the trainer env's python)",
        )
    if not candidate.is_file():
        return (False, f"{candidate}: interpreter not found")

    try:
        proc = subprocess.run(
            [str(candidate), "-c", "import unsloth"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (False, f"{candidate}: import unsloth timed out after {timeout_s:.0f}s")
    except OSError as exc:
        return (False, f"{candidate}: could not launch ({type(exc).__name__}: {exc})")

    if proc.returncode == 0:
        return (True, f"{candidate}: usable (import unsloth succeeded)")
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    reason = tail[-1] if tail else f"exit {proc.returncode}"
    return (False, f"{candidate}: cannot import unsloth ({reason})")


#: The minimum transformers major version required for Qwen3.5 support.
#: Unsloth Studio ships transformers 4.x; the qwen3_5 model type is only
#: recognised from v5 onwards.
TRANSFORMERS_MIN_MAJOR = 5

# Script fragment run inside the candidate interpreter to emit the installed
# transformers version (or "absent" if the package is missing).
_TRANSFORMERS_VERSION_SCRIPT = """\
import sys
try:
    import importlib.metadata as _m
    print(_m.version("transformers"))
except Exception:
    print("absent")
"""


def probe_transformers_version(
    interpreter: Union[str, Path, None],
    *,
    backend: str = "cuda",
    timeout_s: float = PROBE_TIMEOUT_S,
) -> tuple[bool, str]:
    """Probe whether the external trainer env has transformers >= v5.

    Resolves the candidate interpreter (same logic as :func:`probe_trainer`),
    then runs a tiny script inside that interpreter to read the installed
    transformers version. Returns ``(ok, detail)`` where ``ok`` is True iff
    the version is at least :data:`TRANSFORMERS_MIN_MAJOR`.

    Returns ``(False, reason)`` — never raises — when the interpreter cannot be
    resolved, is missing, fails to launch, or has no transformers installed.
    """
    candidate = _candidate_interpreter(interpreter, backend)
    if candidate is None:
        return (
            False,
            "no candidate interpreter (set "
            "[hypnos.voice_alignment].trainer_python to the trainer env's python)",
        )
    if not candidate.is_file():
        return (False, f"{candidate}: interpreter not found")

    try:
        proc = subprocess.run(
            [str(candidate), "-c", _TRANSFORMERS_VERSION_SCRIPT],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            f"{candidate}: transformers version probe timed out after {timeout_s:.0f}s",
        )
    except OSError as exc:
        return (False, f"{candidate}: could not launch ({type(exc).__name__}: {exc})")

    version_str = (proc.stdout or "").strip()
    if version_str == "absent" or not version_str:
        return (False, f"{candidate}: transformers not installed in this env")

    try:
        major = int(version_str.split(".")[0])
    except (ValueError, IndexError):
        return (
            False,
            f"{candidate}: could not parse transformers version {version_str!r}",
        )

    if major < TRANSFORMERS_MIN_MAJOR:
        return (
            False,
            f"{candidate}: transformers {version_str} is too old for Qwen3.5 "
            f"(need >= {TRANSFORMERS_MIN_MAJOR}.0); run: "
            "pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo",
        )
    return (True, f"{candidate}: transformers {version_str} (>= v{TRANSFORMERS_MIN_MAJOR} OK)")
