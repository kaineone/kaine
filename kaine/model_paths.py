# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Filesystem root for provisioned model WEIGHTS.

Model weights — the language-organ GGUF, the InternVideo-Next / DINOv2 vision
encoder, and the other setup-provisioned checkpoints — are a distinct concern
from the entity's STATE (forks, preservation bundles, world/self models, control
state, audit logs). On a plain checkout both live under ``state/`` so a bare
``git clone`` and local run need zero configuration.

The containerized deployment splits them onto two volumes (compose/kaine.yml,
design §6/§7): the read-mostly ``kaine-models`` volume holds the weights (shared,
provisioned once, mounted read-only into the running services) while the entity's
private ``kaine-state`` volume holds its life. The split is selected by pointing
``$KAINE_MODELS_DIR`` at ``/models``; the default preserves the historical
``state/models`` layout, so every weight subdirectory name is unchanged and an
existing local download is never orphaned.

Only the ROOT is redirected — the per-model subdirectory names (e.g.
``Qwen3.5-4B-abliterated-GGUF``) are appended by the callers, so a weight that
lived at ``state/models/<name>`` locally lives at ``/models/<name>`` in the
container, and the setup phase (which writes) and runtime (which reads) agree.
"""
from __future__ import annotations

import os
from pathlib import Path

# Historical default: model weights sit beside the entity's state on a local
# checkout. The container overrides this with KAINE_MODELS_DIR=/models so weights
# land on the shared read-mostly volume rather than the entity-state volume.
DEFAULT_MODELS_DIR = Path("state/models")

MODELS_DIR_ENV_VAR = "KAINE_MODELS_DIR"


def models_dir() -> Path:
    """Root directory for provisioned model weights.

    ``$KAINE_MODELS_DIR`` when set (the container points it at the ``kaine-models``
    volume mount, ``/models``); otherwise the historical ``state/models`` local
    layout. The value is read on each call so a process that sets the variable
    before importing the weight-path modules sees it — the container sets it in
    the service ``environment`` block, before the Python process starts.
    """
    override = os.environ.get(MODELS_DIR_ENV_VAR)
    return Path(override) if override else DEFAULT_MODELS_DIR
