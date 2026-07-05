# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Single global-seed entry point for a run.

``set_global_seed(seed)`` pins the legacy global RNGs (Python ``random`` and
numpy's legacy global) and, best-effort, the torch RNG. Per-experiment code
keeps using ``np.random.default_rng(seed)`` for local streams; this only pins
the legacy globals + torch so nothing on the cycle path is silently
nondeterministic. The torch step is wrapped so a torch-absent or CPU-only
install never fails.

GPU / cuDNN determinism (opt-in)
--------------------------------
Pinning the seed is *not* enough for reproducible CUDA ops: cuDNN autotunes
kernels and several ops have nondeterministic GPU implementations by default.
Passing ``deterministic=True`` additionally sets
``torch.use_deterministic_algorithms(True)``, ``cudnn.deterministic=True`` and
``cudnn.benchmark=False`` (and the ``CUBLAS_WORKSPACE_CONFIG`` env var some CUDA
matmuls require), so seeded CUDA ops on the offline/deterministic experiment path
are reproducible.

This is **opt-in** because it carries a real cost: it disables cuDNN benchmark
autotuning and forces deterministic (sometimes slower, occasionally
unsupported) kernels, which slows and can constrain the live cycle. So the live
cycle leaves it off; only the deterministic/offline experiment runners request
it. The flag is only ever *set*, never *unset* — a deterministic offline run
inside a process does not silently re-enable nondeterminism for later code.
"""
from __future__ import annotations

import os
import random

import numpy as np


def set_global_seed(seed: int, *, deterministic: bool = False) -> int:
    """Seed the global ``random`` and numpy RNGs and, best-effort, torch.

    Parameters
    ----------
    seed:
        The integer seed. Returned so the caller records exactly what was set.
    deterministic:
        When True, also enable torch's GPU/cuDNN determinism flags (see the
        module docstring). Opt-in for the offline/deterministic experiment path;
        the live cycle leaves it off to keep cuDNN autotuning and the faster
        (nondeterministic) kernels. Best-effort: never raises when torch is
        absent or CPU-only.

    Returns the seed used. Never raises on account of torch being absent or
    CPU-only.
    """
    seed = int(seed)
    random.seed(seed)
    np.random.seed(seed)  # legacy global; default_rng(seed) used per-experiment
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():  # pragma: no cover - host-dependent
            torch.cuda.manual_seed_all(seed)
        if deterministic:
            # Some cuBLAS matmuls raise under use_deterministic_algorithms unless
            # this workspace config is set; set it before flipping the flag.
            os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
            torch.use_deterministic_algorithms(True)
            if hasattr(torch.backends, "cudnn"):
                torch.backends.cudnn.deterministic = True
                torch.backends.cudnn.benchmark = False
    except Exception:
        # torch absent / CPU-only / any init issue: seeding it is best-effort.
        pass
    return seed


__all__ = ["set_global_seed"]
