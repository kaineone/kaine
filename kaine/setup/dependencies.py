# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""External service dependency detection + honest provisioning for the wizard.

The first-run wizard needs to tell an operator which external services the
modules they enabled require, which are missing, and how to get them — without
pretending. Two honest provisioning kinds:

  - ``command``: a real, shown command the wizard runs ONLY on explicit consent
    (in-repo bootstrap scripts for Redis/Qdrant). The command is always printed
    first; nothing runs silently.
  - ``guide``: heavy GPU Python services (the OpenAI-compatible model server via
    the Unsloth toolchain, Speaches STT, Chatterbox TTS) are a clone + venv +
    multi-GB model download — not a one-liner. Claiming to "install" them would
    be a lie, so the wizard prints the real setup steps and a doc link and runs
    nothing.

Detection is real (``shutil.which`` for binaries, a TCP connect for running
services). Nothing here is simulated; a probe that cannot run reports the gap
honestly rather than guessing.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any, Optional

from kaine.net import SERVICE_PORTS, port_listening


@dataclass(frozen=True)
class DepSpec:
    """One external dependency the wizard can detect and help provision."""

    name: str
    role: str
    # Modules whose enablement requires this dep. Empty tuple = always required.
    modules: tuple[str, ...]
    # Executable name to look for on PATH (None = not a CLI binary).
    binary: Optional[str]
    # TCP port the running service listens on (None = no port check).
    port: Optional[int]
    # "command" (runnable on consent) or "guide" (printed instructions only).
    kind: str
    # The exact command for kind="command" (shown before running).
    command: str = ""
    note: str = ""
    # For kind="guide": a doc URL and ordered setup steps.
    guide_url: str = ""
    guide_steps: tuple[str, ...] = ()


# The dependency registry. Redis/Qdrant use the repo's own vetted bootstrap
# scripts; the model server (Unsloth toolchain) and Speaches/Chatterbox are
# heavy GPU services and are guide-only.
DEPENDENCIES: tuple[DepSpec, ...] = (
    DepSpec(
        name="redis",
        role="event bus",
        modules=(),  # always required
        binary=None,
        port=6479,
        kind="command",
        command="bash scripts/redis-bootstrap.sh",
        note="starts the KAINE-owned Redis container (compose/redis.yml).",
    ),
    DepSpec(
        name="model_server",
        role="language organ (lingua) — OpenAI-compatible model server",
        modules=("lingua",),
        binary=None,
        port=SERVICE_PORTS["model_server"],
        kind="command",
        command="bash scripts/model-server-bootstrap.sh start",
        note=(
            "launches + supervises the OpenAI-compatible model server against the "
            "downloaded organ GGUF (huggingface.co/kaineone/Qwen3.5-4B-abliterated-GGUF) "
            "under the exact [lingua].model_id alias. Locates the hardware-appropriate "
            "server binary (Unsloth Studio's llama-server on NVIDIA, the unsloth-core "
            "build on AMD; honors KAINE_MODEL_SERVER_BIN); it NEVER silently installs "
            "the multi-GB server toolchain — if the binary is absent it prints install "
            "guidance and fails. Download the organ first with the wizard's organ step "
            "(or hf download kaineone/Qwen3.5-4B-abliterated-GGUF)."
        ),
    ),
    DepSpec(
        name="qdrant",
        role="vector memory (mnemos, empatheia)",
        modules=("mnemos", "empatheia"),
        binary="qdrant",
        port=6333,
        kind="command",
        command="bash scripts/qdrant-bootstrap.sh",
        note="starts the KAINE-owned Qdrant container.",
    ),
    DepSpec(
        name="speaches",
        role="speech-to-text (audition)",
        modules=("audition",),
        binary=None,
        port=SERVICE_PORTS["speaches"],
        kind="guide",
        guide_url="https://github.com/speaches-ai/speaches",
        guide_steps=(
            "Clone speaches and create its own venv (it is a separate GPU service).",
            "Run it on CPU with the medium.en model (GPU cuDNN can crash the loop).",
            "Confirm it serves on http://127.0.0.1:8000/v1/models.",
        ),
        note="heavy GPU Python service — provisioned separately, not auto-installed.",
    ),
    DepSpec(
        name="chatterbox",
        role="text-to-speech (vox)",
        modules=("vox",),
        binary=None,
        port=SERVICE_PORTS["chatterbox"],
        kind="guide",
        guide_url="https://github.com/resemble-ai/chatterbox",
        guide_steps=(
            "Clone Chatterbox and create its own venv (separate GPU service).",
            "Start its server (downloads the TTS model on first run).",
            "Confirm it serves on http://127.0.0.1:8883.",
        ),
        note="heavy GPU Python service — provisioned separately, not auto-installed.",
    ),
)


@dataclass
class DepStatus:
    spec: DepSpec
    installed: bool  # binary present (True when the dep has no binary check)
    running: bool    # TCP port accepting connections (False when no port)

    @property
    def satisfied(self) -> bool:
        # A running service is satisfied regardless of a local binary (it may run
        # in a container or on another host the operator pointed us at).
        return self.running


def _binary_present(binary: Optional[str]) -> bool:
    if not binary:
        return True
    return shutil.which(binary) is not None


def _port_listening(port: Optional[int], *, timeout_s: float = 1.0) -> bool:
    # Wraps the shared probe with a None-guard: a DepSpec without a port
    # (port=None) is treated as "not listening" rather than probed.
    if not port:
        return False
    return port_listening(port, timeout_s=timeout_s)


def _needed(spec: DepSpec, modules_enabled: dict[str, bool]) -> bool:
    if not spec.modules:
        return True
    return any(modules_enabled.get(m) for m in spec.modules)


def implied_external_deps(
    modules_enabled: dict[str, bool], *, specs: tuple[DepSpec, ...] = DEPENDENCIES
) -> list[str]:
    """Names of the external service deps the enabled modules require."""
    return [s.name for s in specs if _needed(s, modules_enabled)]


def detect_dependencies(
    modules_enabled: dict[str, bool],
    *,
    specs: tuple[DepSpec, ...] = DEPENDENCIES,
    redis_port: Optional[int] = None,
) -> list[DepStatus]:
    """Detect, for each NEEDED dependency, whether it is installed and running.

    ``redis_port`` overrides the Redis port (the shipped config uses 6479).
    Real probes only: PATH lookup + TCP connect. Never raises.
    """
    out: list[DepStatus] = []
    for spec in specs:
        if not _needed(spec, modules_enabled):
            continue
        port = spec.port
        if spec.name == "redis" and redis_port:
            port = redis_port
        out.append(
            DepStatus(
                spec=spec,
                installed=_binary_present(spec.binary),
                running=_port_listening(port),
            )
        )
    return out
