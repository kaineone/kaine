# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consented, hardware-aware download of the published KAINE language organ.

The language organ is published under the project's own account — Apache-2.0,
honest model card:

  - ``kaineone/Qwen3.5-4B-abliterated-GGUF``   (GGUF, served by the
    OpenAI-compatible llama-server — the always-needed artifact)
  - ``kaineone/Qwen3.5-4B-abliterated``        (safetensors base — only needed as
    the Stage-2 voice-alignment trainer's ``base_model_path``)

A fresh clone has NO weights. This module gives the first-run wizard a real,
consented, hardware-aware acquisition of the organ so "clone → install → run"
resolves identical weights for every researcher, instead of a manual scavenger
hunt against a wrong default. It mirrors the detect-and-guide pattern in
:mod:`kaine.setup.dependencies` / :mod:`kaine.setup.trainer_provisioning`:

  - ``detect_organ_backend()`` reuses the GPU-vendor detection (CUDA → the
    Unsloth Studio direction, ROCm → unsloth-core, anything else → guide-only).
  - ``plan_organ_download()`` decides which repo(s)+format(s) are needed for the
    host's role (GGUF always; +safetensors iff Stage-2 training is enabled) and
    returns the EXACT command(s) plus a size estimate — nothing for a non-lingua
    install.
  - ``run_organ_download()`` runs a **real** ``hf download`` (real subprocess,
    real success/failure; never a faked/no-op "installed" result) and captures the
    resolved repo revision (commit sha) when the tool reports it.
  - ``verify_served_alias()`` probes ``{chat_url}/models`` for the exact configured
    alias, converting a boot-time 404 into a pre-boot, operator-facing message.

No pretend processes: a download is a real ``hf download`` or it fails honestly;
a probe that cannot run reports the gap rather than guessing.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Optional

from kaine.organ_probe import ORGAN_REVISION_STATE_PATH
from kaine.organ_server.served import (
    ORGAN_GGUF_FILE,
    ORGAN_GGUF_REPO,
    ORGAN_SAFETENSORS_REPO,
    OrganBackend,
    organ_gguf_dir,
)
from kaine.storage import resolve

# Rough download sizes (GiB) for the operator-facing "bytes up front" message.
# The 4B GGUF (q4-ish) is a few GiB; the safetensors base is the full-precision
# checkpoint. Honest estimates, not promises — ``hf download`` reports the real
# bytes as it runs.
_GGUF_SIZE_GB = 3.0
_SAFETENSORS_SIZE_GB = 8.0


@dataclass(frozen=True)
class OrganArtifact:
    """One repo+format the host needs, with its exact download command."""

    repo: str
    fmt: str               # "gguf" | "safetensors"
    reason: str
    size_gb: float
    command: list[str]     # exact argv (hf download ...)


@dataclass(frozen=True)
class OrganDownloadPlan:
    """The organ-acquisition plan for a host's chosen modules + backend.

    ``artifacts`` is empty when the organ is not needed (lingua disabled): the
    wizard then offers no download step at all.
    """

    needed: bool
    backend: OrganBackend
    artifacts: tuple[OrganArtifact, ...] = ()

    @property
    def total_size_gb(self) -> float:
        return round(sum(a.size_gb for a in self.artifacts), 1)


def _lingua_enabled(modules: dict[str, Any]) -> bool:
    return bool((modules or {}).get("lingua"))


def _stage2_enabled(config: dict[str, Any]) -> bool:
    """True iff on-device voice-alignment (Stage-2) training is enabled.

    Stage-2 needs the safetensors base as the trainer's ``base_model_path``; a
    serve-only host skips it. Gated on BOTH the hypnos module toggle and
    ``[hypnos.voice_alignment].enabled`` (the master gate)."""
    modules = config.get("modules") or {}
    if not modules.get("hypnos"):
        return False
    va = (config.get("hypnos") or {}).get("voice_alignment") or {}
    return bool(va.get("enabled"))


def _hf_download_cmd(repo: str) -> list[str]:
    """The real ``hf download <repo>`` argv (HF Hub CLI; resumes + verifies)."""
    return ["hf", "download", repo]


def _gguf_download_cmd() -> list[str]:
    """Real ``hf download`` of the single GGUF file into the deterministic local
    dir, so the server can be launched with ``-m <served_gguf_path()>`` (a real file
    path). ``--local-dir`` makes the landing path known and stable, independent of
    the hub-cache snapshot layout."""
    local_dir = organ_gguf_dir()
    return [
        "hf", "download", ORGAN_GGUF_REPO, ORGAN_GGUF_FILE,
        "--local-dir", str(local_dir),
    ]


def plan_organ_download(
    modules: dict[str, Any],
    backend: OrganBackend,
    *,
    config: Optional[dict[str, Any]] = None,
) -> OrganDownloadPlan:
    """Decide which repo(s)+format(s) the host needs and the exact command(s).

    GGUF is always required (what the OpenAI-compatible server serves);
    safetensors is added ONLY when Stage-2 voice-alignment training is enabled
    (the trainer's base model). Returns an empty plan (``needed=False``) when
    lingua is not enabled — the wizard then offers no organ step.

    ``config`` is the resolved config used to read the Stage-2 toggle; when None it
    is derived from ``modules`` alone (Stage-2 treated as off). Pure: builds the
    plan, runs nothing.
    """
    if not _lingua_enabled(modules):
        return OrganDownloadPlan(needed=False, backend=backend, artifacts=())

    cfg = config if config is not None else {"modules": modules}
    artifacts: list[OrganArtifact] = [
        OrganArtifact(
            repo=ORGAN_GGUF_REPO,
            fmt="gguf",
            reason="served by the OpenAI-compatible model server (always needed)",
            size_gb=_GGUF_SIZE_GB,
            command=_gguf_download_cmd(),
        )
    ]
    if _stage2_enabled(cfg):
        artifacts.append(
            OrganArtifact(
                repo=ORGAN_SAFETENSORS_REPO,
                fmt="safetensors",
                reason="Stage-2 voice-alignment trainer base_model_path",
                size_gb=_SAFETENSORS_SIZE_GB,
                command=_hf_download_cmd(ORGAN_SAFETENSORS_REPO),
            )
        )
    return OrganDownloadPlan(
        needed=True, backend=backend, artifacts=tuple(artifacts)
    )


@dataclass
class OrganDownloadResult:
    """Outcome of one artifact download. ``revision`` is the resolved commit sha
    when ``hf`` reported it (for the run-manifest covariate), else None."""

    repo: str
    fmt: str
    ok: bool
    revision: Optional[str] = None
    detail: str = ""


# `hf download` prints the local snapshot path, which embeds the resolved commit
# sha: .../snapshots/<40-hex-sha>/...  We capture that sha as the pinned revision.
_SNAPSHOT_SHA_RE = re.compile(r"/snapshots/([0-9a-f]{40})\b")


def _extract_revision(output: str) -> Optional[str]:
    m = _SNAPSHOT_SHA_RE.search(output or "")
    return m.group(1) if m else None


def run_organ_download(
    plan: OrganDownloadPlan,
    *,
    consent: bool,
    runner: Any = None,
) -> list[OrganDownloadResult]:
    """Run the planned organ download(s) — a REAL ``hf download`` per artifact.

    Runs ONLY on explicit ``consent``; with ``consent=False`` it runs nothing and
    returns ``[]`` (the wizard prints the guide instead). The ``hf`` CLI must be
    on PATH; if it is absent each artifact reports an honest failure (no faked
    success). Each ``hf download`` is a real subprocess (``check=True`` caught) and
    its output is scanned for the resolved snapshot sha, recorded as the pinned
    revision. Never raises — a failed download is reported as ``ok=False``.

    ``runner`` defaults to ``subprocess.run`` (overridable in tests with a mocked
    subprocess; the production path always invokes the real CLI).
    """
    if not consent or not plan.needed or not plan.artifacts:
        return []

    run = runner if runner is not None else subprocess.run
    have_hf = shutil.which("hf") is not None

    results: list[OrganDownloadResult] = []
    for art in plan.artifacts:
        if not have_hf:
            results.append(
                OrganDownloadResult(
                    repo=art.repo,
                    fmt=art.fmt,
                    ok=False,
                    detail=(
                        "the Hugging Face CLI (`hf`) is not on PATH — install it "
                        "(`pip install -U huggingface_hub`) then re-run: "
                        + " ".join(art.command)
                    ),
                )
            )
            continue
        try:
            proc = run(
                art.command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            tail = (exc.stderr or exc.stdout or "").strip().splitlines()
            reason = tail[-1] if tail else f"exit {exc.returncode}"
            results.append(
                OrganDownloadResult(
                    repo=art.repo, fmt=art.fmt, ok=False,
                    detail=f"download failed ({reason})",
                )
            )
            continue
        except Exception as exc:  # OSError launching, etc.
            results.append(
                OrganDownloadResult(
                    repo=art.repo, fmt=art.fmt, ok=False,
                    detail=f"could not run hf download ({type(exc).__name__}: {exc})",
                )
            )
            continue
        out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
        revision = _extract_revision(out)
        results.append(
            OrganDownloadResult(
                repo=art.repo,
                fmt=art.fmt,
                ok=True,
                revision=revision,
                detail=(
                    f"downloaded (revision {revision})"
                    if revision
                    else "downloaded"
                ),
            )
        )
    return results


def acquisition_guide(backend: OrganBackend, plan: OrganDownloadPlan) -> list[str]:
    """Operator-facing acquisition guidance lines (printed on decline / no GPU).

    Shows the published repos, the exact ``hf download`` command(s), and the
    hardware-appropriate serve direction — never an auto-install."""
    lines = [f"  {backend.summary}"]
    if plan.needed:
        for art in plan.artifacts:
            lines.append(
                f"    - {art.fmt}: huggingface.co/{art.repo} "
                f"(~{art.size_gb:.0f} GB; {art.reason})"
            )
            lines.append(f"        download: {' '.join(art.command)}")
        lines.append(
            "    Then serve the GGUF with the model server bootstrap: "
            "bash scripts/model-server-bootstrap.sh start"
        )
    return lines


def revisions_from_results(
    results: list[OrganDownloadResult],
) -> dict[str, str]:
    """Map ``<repo> -> <revision sha>`` for the resolved downloads.

    Used to persist provenance (the pinned published snapshot) for the run
    manifest. Only artifacts whose revision was resolved are included."""
    return {r.repo: r.revision for r in results if r.ok and r.revision}


def write_revision_state(
    results: list[OrganDownloadResult],
    *,
    path: Optional[str] = None,
) -> Optional[str]:
    """Persist resolved organ revision(s) to a small state file (best-effort).

    Returns the path written, or None if there was nothing to record / the write
    failed. Never raises."""
    revisions = revisions_from_results(results)
    if not revisions:
        return None
    target = resolve(path or ORGAN_REVISION_STATE_PATH)
    try:
        from kaine.state_io import write_json_atomic

        write_json_atomic(target, revisions)
        return str(target)
    except OSError:
        return None
