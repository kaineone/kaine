# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Run manifest writer.

Writes the full ``RunContext`` once at boot to
``data/evaluation/runs/<run_id>/manifest.json`` with an atomic tmp + os.replace
so a partially-written manifest is never observed. The ``runs`` dir name is in
``METRICS_ONLY_DIRS`` (kaine/research/submission.py) so manifests ride the
existing metrics export — they hold only ids / seed / sha / model-ids /
config-digest, no entity interior.
"""
from __future__ import annotations

import os
from pathlib import Path

from kaine.experiment.run_context import RunContext
from kaine.state_io import write_json_atomic


def write_manifest(ctx: RunContext, root: str | os.PathLike[str] = "data/evaluation/runs") -> Path:
    """Atomically write ``ctx`` as JSON to ``<root>/<run_id>/manifest.json``.

    Returns the path to the manifest. The per-run directory is created if needed.
    """
    run_dir = Path(root) / ctx.run_id
    target = run_dir / "manifest.json"
    write_json_atomic(target, ctx.to_dict())
    return target


__all__ = ["write_manifest"]
