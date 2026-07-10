# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Setup-phase model provisioning for the containerized deployment.

`python -m kaine.setup.provision` runs ONCE, before first boot, inside the
`--profile setup` one-shot service (compose/kaine.yml `kaine-provision`). It
downloads every model weight the stack needs into the shared ``HF_HOME`` model
volume so that runtime reaches NO network for models — honoring the load-bearing
all-local-at-runtime constraint (design.md §6). At runtime the services set
``HF_HUB_OFFLINE=1`` / ``TRANSFORMERS_OFFLINE=1``; only THIS phase fetches.

What it provisions:

  - the abliterated language organ (GGUF, reusing the existing
    ``kaine.setup.organ`` provisioning — a real ``hf download``),
  - the speech-to-text model (faster-distil-Whisper medium.en),
  - the emotion encoder (emotion2vec+),
  - the vision encoder — the shipped default ``[topos].encoder_backend =
    "internvideo_next"`` fetches the revision-pinned InternVideo-Next weights
    (reusing ``kaine.setup.internvideo_next``); only when the operator selects
    ``encoder_backend = "dinov2"`` is DINOv2-small fetched instead,
  - the memory embedder (all-MiniLM-L6-v2),
  - the text-to-speech model (Chatterbox).

Model ids are read from ``config/kaine.toml`` where a section exposes one, so
provisioning tracks the operator's configured models; otherwise the shipped
defaults below are used. Every download is a real ``hf download`` subprocess (the
``runner`` is injectable so tests never touch the network). Weights land in the
``kaine-models`` volume — never an image layer.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from kaine.setup.internvideo_next import (
    INTERNVIDEO_NEXT_REPO,
    internvideo_next_download_cmd,
    run_internvideo_next_download,
)
from kaine.setup.organ import (
    OrganDownloadResult,
    detect_organ_backend,
    plan_organ_download,
    run_organ_download,
)

# Shipped-default HF repo ids for the non-organ models. Kept in sync with
# config/kaine.toml (grep: dinov2-small, all-MiniLM-L6-v2, faster-distil-whisper,
# emotion2vec_plus_base) plus the Chatterbox TTS weights (kaine/setup/
# dependencies.py: resemble-ai/chatterbox).
DEFAULT_STT_REPO = "Systran/faster-distil-whisper-medium.en"
DEFAULT_EMOTION_REPO = "emotion2vec/emotion2vec_plus_base"
DEFAULT_VISION_REPO = "facebook/dinov2-small"
DEFAULT_EMBEDDER_REPO = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_TTS_REPO = "resemble-ai/chatterbox"

# Shipped-default Topos encoder backend. Kept in sync with
# kaine.modules.topos.encoder.DEFAULT_ENCODER_BACKEND and config/kaine.toml
# [topos].encoder_backend. Held as a bare string so the setup phase never pulls
# the heavy torch-bearing encoder module just to read a default.
DEFAULT_ENCODER_BACKEND = "internvideo_next"


def encoder_backend(config: Optional[dict[str, Any]] = None) -> str:
    """The configured Topos encoder backend, lower-cased; the shipped default
    (``internvideo_next``) when the operator sets none."""
    topos = (config or {}).get("topos") or {}
    val = topos.get("encoder_backend")
    return str(val).strip().lower() if val else DEFAULT_ENCODER_BACKEND


@dataclass(frozen=True)
class AuxModel:
    """One non-organ model to provision into the shared model volume."""

    repo: str
    purpose: str


@dataclass
class ProvisionResult:
    """Outcome of one non-organ ``hf download``."""

    repo: str
    purpose: str
    ok: bool
    detail: str = ""


@dataclass
class ProvisionPlan:
    """The full setup-phase download plan: the organ artifacts plus the aux
    models. Pure data — building it runs no download."""

    organ_commands: tuple[tuple[str, ...], ...] = ()
    aux_models: tuple[AuxModel, ...] = ()
    # The InternVideo-Next weights fetch argv, present ONLY when the configured
    # (or default) encoder backend is ``internvideo_next``. Empty otherwise (the
    # DINOv2 backend fetches its weights as a plain aux model instead).
    internvideo_command: tuple[str, ...] = ()
    _config: dict[str, Any] = field(default_factory=dict, repr=False)


def _cfg_repo(config: dict[str, Any], section: str, key: str, default: str) -> str:
    sect = config.get(section) or {}
    val = sect.get(key)
    return str(val) if val else default


def aux_models(config: Optional[dict[str, Any]] = None) -> tuple[AuxModel, ...]:
    """The non-organ models provisioned as a plain ``hf download <repo>``, reading
    configured ids where present.

    The vision encoder is backend-dependent and only DINOv2 is a plain repo
    download: it appears here ONLY when ``[topos].encoder_backend = "dinov2"``.
    The shipped default (``internvideo_next``) is a revision-pinned single-file
    fetch handled separately (see :func:`internvideo_next_fetch_cmd` and
    ``run_provision``), so it is deliberately NOT an ``AuxModel``."""
    cfg = config or {}
    models = [
        AuxModel(_cfg_repo(cfg, "audition", "stt_model_id", DEFAULT_STT_REPO),
                 "speech-to-text (faster-distil-Whisper)"),
        AuxModel(_cfg_repo(cfg, "audition", "model_id", DEFAULT_EMOTION_REPO),
                 "emotion encoder (emotion2vec+)"),
    ]
    if encoder_backend(cfg) == "dinov2":
        models.append(
            AuxModel(_cfg_repo(cfg, "topos", "encoder_model_id", DEFAULT_VISION_REPO),
                     "vision encoder (DINOv2-small)")
        )
    models.extend([
        AuxModel(_cfg_repo(cfg, "mnemos", "embedder_model_id", DEFAULT_EMBEDDER_REPO),
                 "memory embedder (all-MiniLM-L6-v2)"),
        AuxModel(DEFAULT_TTS_REPO, "text-to-speech (Chatterbox)"),
    ])
    return tuple(models)


def internvideo_next_fetch_cmd() -> tuple[str, ...]:
    """The revision-pinned ``hf download`` argv for the InternVideo-Next encoder
    weights (empty tuple is never returned — this is only consulted when the
    backend is ``internvideo_next``)."""
    return tuple(internvideo_next_download_cmd())


def plan_provision(config: dict[str, Any]) -> ProvisionPlan:
    """Build the full setup-phase plan. Pure: downloads nothing."""
    modules = config.get("modules") or {}
    backend = detect_organ_backend()
    organ_plan = plan_organ_download(modules, backend, config=config)
    organ_cmds = tuple(tuple(a.command) for a in organ_plan.artifacts)
    iv_cmd = (
        internvideo_next_fetch_cmd()
        if encoder_backend(config) == "internvideo_next"
        else ()
    )
    return ProvisionPlan(
        organ_commands=organ_cmds,
        aux_models=aux_models(config),
        internvideo_command=iv_cmd,
        _config=config,
    )


def _aux_download_cmd(repo: str) -> list[str]:
    """Real ``hf download <repo>`` argv into the ambient ``HF_HOME`` cache."""
    return ["hf", "download", repo]


def run_provision(
    config: dict[str, Any],
    *,
    consent: bool = True,
    runner: Optional[Callable[..., Any]] = None,
) -> tuple[list[OrganDownloadResult], list[ProvisionResult]]:
    """Provision every model weight. Real ``hf download`` per model.

    With ``consent=False`` nothing runs (returns empty lists). ``runner`` defaults
    to ``subprocess.run`` and is injectable so tests never hit the network. Never
    raises — a failed download is reported as ``ok=False``.
    """
    if not consent:
        return [], []

    run = runner if runner is not None else subprocess.run

    modules = config.get("modules") or {}
    backend = detect_organ_backend()
    organ_plan = plan_organ_download(modules, backend, config=config)
    organ_results = run_organ_download(organ_plan, consent=True, runner=run)

    have_hf = shutil.which("hf") is not None
    aux_results: list[ProvisionResult] = []

    # The shipped default vision backend (internvideo_next) is a revision-pinned
    # single-file fetch into the deterministic git-ignored weights dir — reuse the
    # dedicated fetcher so the download lands where the loader reads it. DINOv2, if
    # selected instead, is fetched below as a plain aux model.
    if encoder_backend(config) == "internvideo_next":
        iv = run_internvideo_next_download(consent=True, runner=run)
        aux_results.append(
            ProvisionResult(
                repo=INTERNVIDEO_NEXT_REPO,
                purpose="vision encoder (InternVideo-Next)",
                ok=iv.ok,
                detail=iv.detail,
            )
        )

    for model in aux_models(config):
        if not have_hf:
            aux_results.append(
                ProvisionResult(
                    repo=model.repo,
                    purpose=model.purpose,
                    ok=False,
                    detail=(
                        "the Hugging Face CLI (`hf`) is not on PATH — install it "
                        "(`pip install -U huggingface_hub`) then re-run provisioning"
                    ),
                )
            )
            continue
        try:
            run(_aux_download_cmd(model.repo), check=True)
            aux_results.append(
                ProvisionResult(repo=model.repo, purpose=model.purpose, ok=True)
            )
        except Exception as exc:  # noqa: BLE001 — report, never crash provisioning
            aux_results.append(
                ProvisionResult(
                    repo=model.repo,
                    purpose=model.purpose,
                    ok=False,
                    detail=f"hf download failed ({type(exc).__name__}: {exc})",
                )
            )
    return organ_results, aux_results


def _load_config() -> dict[str, Any]:
    from kaine.config import load_kaine_config

    return load_kaine_config()


def main(argv: Optional[list[str]] = None) -> int:
    organ_results, aux_results = run_provision(_load_config())
    ok = True
    for r in organ_results:
        status = "ok" if r.ok else "FAILED"
        print(f"[organ:{r.fmt}] {r.repo}: {status} {r.detail}".rstrip())
        ok = ok and r.ok
    for a in aux_results:
        status = "ok" if a.ok else "FAILED"
        print(f"[{a.purpose}] {a.repo}: {status} {a.detail}".rstrip())
        ok = ok and a.ok
    if not ok:
        print(
            "provisioning incomplete — resolve the failures above and re-run "
            "the setup profile before first boot.",
            file=sys.stderr,
        )
        return 1
    print("provisioning complete — all model weights are in the model volume.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
