# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The organ's identity and the served-model checks the runtime uses.

Which published organ KAINE serves, where its GGUF lives, which server backend the host can run, and whether the running server answers to the expected alias. Install-time download and planning stay in ``kaine.setup.organ``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from kaine.model_paths import models_dir

# The published organ's repository ids (HF-repo-id-as-served-alias convention).
ORGAN_GGUF_REPO = "kaineone/Qwen3.5-4B-abliterated-GGUF"
ORGAN_SAFETENSORS_REPO = "kaineone/Qwen3.5-4B-abliterated"

# The single quantized GGUF file in the published GGUF repo, and the deterministic
# local directory it is downloaded into. The model server is launched with
# ``-m <served_gguf_path()>`` — llama-server's ``-m`` takes a real file PATH, not an
# HF repo id, so the download lands the file at a known path the launcher can point
# at directly (no dependence on the opaque hub-cache snapshot layout). The parent
# is the shared model-weights root (``state/models`` locally, ``/models`` in the
# container — see kaine.model_paths); the subdirectory name is stable so the
# provision step and the model server agree on the served path.
ORGAN_GGUF_FILE = "KAINE-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
ORGAN_GGUF_DIR = models_dir() / "Qwen3.5-4B-abliterated-GGUF"


def organ_gguf_dir() -> Path:
    """Call-time model-weights subdirectory for the organ GGUF.

    The import-time ``ORGAN_GGUF_DIR`` constant is kept for callers that import
    it, but any code that actually accesses the directory must resolve it at
    use time so ``KAINE_MODELS_DIR`` and the process data root take effect.
    """
    return models_dir() / "Qwen3.5-4B-abliterated-GGUF"


def served_gguf_path() -> Path:
    """Deterministic local path of the downloaded GGUF the server serves with ``-m``."""
    return organ_gguf_dir() / ORGAN_GGUF_FILE

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

            resp = httpx.get(url, headers=headers, timeout=timeout_s, trust_env=False)
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
