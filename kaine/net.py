# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral local-service networking primitives.

Holds the two things the GPU preflight (``kaine.cycle.preflight``) and the
setup dependency probe (``kaine.setup.dependencies``) both need and had each
duplicated:

* :data:`SERVICE_PORTS` — KAINE's own GPU-using local services, by port. The
  preflight detects-and-preserves these; setup probes them for readiness.
* :func:`port_listening` — a tiny "is something accepting TCP on 127.0.0.1?"
  probe.

This module is stdlib-only and imports nothing from the rest of ``kaine`` so it
stays import-legal from both the cycle runtime and the setup tooling.

NOTE: the intentionally import-light standalone probes in ``scripts/`` and
``kaine.setup.__main__.probe_services`` are deliberate standalone
reimplementations and are left untouched. Per-module user-overridable
URL/port config defaults (e.g. ``kaine.modules.lingua.client``) are legitimate
separate config, not part of this registry.
"""
from __future__ import annotations

import socket

__all__ = ["SERVICE_PORTS", "port_listening"]

# KAINE's own GPU-using services, by local port.
#   model_server — the OpenAI-compatible inference server (Unsloth Studio /
#                  llama.cpp) that serves the language organ (lingua).
#   chatterbox   — text-to-speech (vox).
#   speaches     — speech-to-text (audition).
SERVICE_PORTS: dict[str, int] = {
    "model_server": 11434,
    "chatterbox": 8883,
    "speaches": 8000,
}


def port_listening(port: int, timeout_s: float = 1.0) -> bool:
    """Return True iff a TCP server is accepting on ``127.0.0.1:port``."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s):
            return True
    except OSError:
        return False
