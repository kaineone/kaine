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

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# The published organ's repository ids (HF-repo-id-as-served-alias convention).
ORGAN_GGUF_REPO = "kaineone/Qwen3.5-4B-abliterated-GGUF"
ORGAN_SAFETENSORS_REPO = "kaineone/Qwen3.5-4B-abliterated"

# The single quantized GGUF file in the published GGUF repo, and the deterministic
# local directory it is downloaded into. The model server is launched with
# ``-m <served_gguf_path()>`` — llama-server's ``-m`` takes a real file PATH, not an
# HF repo id, so the download lands the file at a known path the launcher can point
# at directly (no dependence on the opaque hub-cache snapshot layout).
ORGAN_GGUF_FILE = "KAINE-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
ORGAN_GGUF_DIR = Path("state/models/Qwen3.5-4B-abliterated-GGUF")


def served_gguf_path() -> Path:
    """Deterministic local path of the downloaded GGUF the server serves with ``-m``."""
    return ORGAN_GGUF_DIR / ORGAN_GGUF_FILE

# Rough download sizes (GiB) for the operator-facing "bytes up front" message.
# The 4B GGUF (q4-ish) is a few GiB; the safetensors base is the full-precision
# checkpoint. Honest estimates, not promises — ``hf download`` reports the real
# bytes as it runs.
_GGUF_SIZE_GB = 3.0
_SAFETENSORS_SIZE_GB = 8.0

# Wall-clock ceiling for the served-alias probe (seconds).
PROBE_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class OrganBackend:
    """How the host should acquire/serve the organ, from the GPU vendor.

    ``available`` is False on a host with no CUDA/ROCm GPU: there is no supported
    accelerator toolchain to serve a GGUF, so the wizard guides rather than
    installing silently. ``path`` is the operator-facing direction name
    (``"studio"`` on NVIDIA, ``"core"`` on AMD) used to pick the serve path.
    """

    backend: str           # "cuda" | "rocm" | <other>
    available: bool
    path: str              # "studio" | "core" | ""
    summary: str


def detect_organ_backend(backend: Optional[str] = None) -> OrganBackend:
    """Map a ``describe_host()["backend"]`` value to an organ-acquisition path.

    Reuses the same vendor mapping as the trainer provisioning: ``cuda`` (NVIDIA)
    → the Unsloth Studio direction, ``rocm`` (AMD) → unsloth-core, anything else
    (``xpu``/``mps``/``cpu``/unknown) → guide-only (no supported accelerator
    toolchain to serve the GGUF). When ``backend`` is None it is read from a live
    hardware scan; never raises (a failed scan reports unavailable).
    """
    if backend is None:
        try:
            from kaine.hardware import describe_host

            backend = str(describe_host().get("backend") or "cpu")
        except Exception:
            backend = "cpu"
    if backend == "cuda":
        return OrganBackend(
            backend="cuda",
            available=True,
            path="studio",
            summary=(
                "NVIDIA/CUDA host — acquire and serve the organ via the Unsloth "
                "Studio direction (the main path for entities)."
            ),
        )
    if backend == "rocm":
        return OrganBackend(
            backend="rocm",
            available=True,
            path="core",
            summary=(
                "AMD/ROCm host — acquire and serve the organ via the unsloth-core "
                "direction (Studio targets NVIDIA)."
            ),
        )
    return OrganBackend(
        backend=backend,
        available=False,
        path="",
        summary=(
            "No CUDA/ROCm GPU detected — the OpenAI-compatible model server needs "
            "a supported accelerator toolchain. The wizard prints acquisition "
            "guidance rather than installing silently."
        ),
    )


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
    return [
        "hf", "download", ORGAN_GGUF_REPO, ORGAN_GGUF_FILE,
        "--local-dir", str(ORGAN_GGUF_DIR),
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


@dataclass(frozen=True)
class ServedAliasResult:
    """Whether the running server lists the configured organ alias."""

    listed: bool
    served: tuple[str, ...]
    detail: str


def verify_served_alias(
    chat_url: str,
    model_id: str,
    *,
    api_key: Optional[str] = None,
    timeout_s: float = PROBE_TIMEOUT_S,
    client: Any = None,
) -> ServedAliasResult:
    """Probe ``{chat_url}/models`` for the EXACT configured organ alias.

    Tolerates ``chat_url`` given as the server root or with a trailing ``/v1``
    (mirrors the cycle health probe). Returns whether ``model_id`` is among the
    served names plus the names seen, so the wizard can turn the boot-time 404
    failure mode ("server up, wrong name") into a pre-boot, actionable "served
    name X ≠ configured Y" message. Never raises — an unreachable server reports
    ``listed=False`` with a reason.

    ``client`` is an optional injected HTTP client (a callable
    ``get(url, *, headers, timeout) -> response`` with ``.status_code`` /
    ``.json()``) for tests; the production path uses ``httpx``.
    """
    base = chat_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    url = base + "/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None

    try:
        if client is not None:
            resp = client.get(url, headers=headers, timeout=timeout_s)
        else:
            import httpx

            resp = httpx.get(url, headers=headers, timeout=timeout_s)
    except Exception as exc:
        return ServedAliasResult(
            listed=False,
            served=(),
            detail=f"model server unreachable at {url} ({type(exc).__name__}: {exc})",
        )

    status = getattr(resp, "status_code", None)
    if status != 200:
        return ServedAliasResult(
            listed=False, served=(), detail=f"/v1/models returned HTTP {status}"
        )
    try:
        data = resp.json()
        served = tuple(
            str(m.get("id")) for m in (data.get("data") or []) if m.get("id")
        )
    except Exception:
        return ServedAliasResult(
            listed=False, served=(), detail="could not parse /v1/models response"
        )
    if model_id in served:
        return ServedAliasResult(
            listed=True, served=served, detail=f"served name '{model_id}' matches"
        )
    return ServedAliasResult(
        listed=False,
        served=served,
        detail=(
            f"served name(s) {list(served)} ≠ configured [lingua].model_id "
            f"'{model_id}' — launch the server with --alias '{model_id}'"
        ),
    )


# Wall-clock ceiling for the content probe. Unlike verify_served_alias (a cheap
# /models list), this runs a REAL generation, so it gets a more generous default.
CONTENT_PROBE_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class OrganContentResult:
    """Whether the served organ actually GENERATES non-empty content."""

    ok: bool
    detail: str
    sample: str = ""


async def verify_organ_generates(
    chat_url: str,
    model_id: str,
    *,
    api_key: Optional[str] = None,
    timeout_s: float = CONTENT_PROBE_TIMEOUT_S,
    client: Any = None,
) -> OrganContentResult:
    """Boot-time CONTENT gate: confirm the served organ returns NON-EMPTY text.

    ``verify_served_alias`` proves the server *lists* the right name; this proves
    the served model actually SPEAKS. A hybrid-thinking model whose chain-of-
    thought is not suppressed reasons to exhaustion and returns empty ``content``
    — it passes the alias check yet leaves the entity voiceless (the exact failure
    this gate exists to catch). So the gate sends one real completion through the
    production Lingua client (thinking suppressed by the organ default
    ``think=False``) and checks the visible text is non-empty.

    Never raises: an unreachable / erroring / mute organ returns ``ok=False`` with
    a remediation ``detail`` so the caller owns the boot policy. ``client`` is an
    optional injected chat client (duck-typed ``complete`` / ``aclose``) for tests.
    """
    from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient

    own_client = client is None
    if own_client:
        client = OpenAIChatClient(base_url=chat_url, api_key=api_key, timeout_s=timeout_s)
    try:
        resp = await client.complete(
            ChatRequest(
                prompt="Reply with a single short word.",
                model=model_id,
                max_tokens=64,
            )
        )
    except Exception as exc:  # report ANY failure as a gate miss, never propagate
        return OrganContentResult(
            ok=False,
            detail=(
                f"organ '{model_id}' did not respond at {chat_url} "
                f"({type(exc).__name__}: {exc})"
            ),
        )
    finally:
        if own_client:
            try:
                await client.aclose()
            except Exception:
                pass

    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        return OrganContentResult(
            ok=False,
            detail=(
                f"organ '{model_id}' is SERVED but MUTE — returned empty content. "
                "Most likely its chain-of-thought is not suppressed (the model "
                "reasons to exhaustion and emits no visible answer). Verify the "
                "Lingua client sends chat_template_kwargs.enable_thinking=false."
            ),
        )
    return OrganContentResult(
        ok=True,
        detail=(
            f"organ '{model_id}' generates content "
            f"({getattr(resp, 'completion_tokens', 0)} tok, "
            f"{round(getattr(resp, 'latency_ms', 0.0))}ms)"
        ),
        sample=text[:80],
    )


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


# Where the downloader records the resolved organ revision(s) so the cycle's
# run-manifest provenance path can pin the exact published snapshot. JSON map of
# ``<repo> -> <sha>``; optional/best-effort (a missing file never crashes boot).
ORGAN_REVISION_STATE_PATH = "state/model-server/organ_revisions.json"


def write_revision_state(
    results: list[OrganDownloadResult],
    *,
    path: Optional[str] = None,
) -> Optional[str]:
    """Persist resolved organ revision(s) to a small state file (best-effort).

    Returns the path written, or None if there was nothing to record / the write
    failed. Never raises."""
    from pathlib import Path

    revisions = revisions_from_results(results)
    if not revisions:
        return None
    target = Path(path or ORGAN_REVISION_STATE_PATH)
    try:
        from kaine.state_io import write_json_atomic

        write_json_atomic(target, revisions)
        return str(target)
    except OSError:
        return None


def read_revision_state(path: Optional[str] = None) -> dict[str, str]:
    """Read the resolved organ revision map for provenance. ``{}`` if absent."""
    from pathlib import Path

    target = Path(path or ORGAN_REVISION_STATE_PATH)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}
