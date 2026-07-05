# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Experiment foundation: run identity, global seeding, manifest, verdict schema.

This package is boundary-neutral. Like ``kaine/persistence/`` and
``kaine/security/`` it carries NO dependency on ``kaine.evaluation``, so both the
core cognitive cycle and the evaluation sidecar may import it without crossing
the sidecar privacy boundary. It depends only on the standard library, numpy, and
(optionally, best-effort) torch.

Pieces:

* :mod:`kaine.experiment.seeding` — ``set_global_seed`` pins the random/numpy/
  torch global RNGs from one integer.
* :mod:`kaine.experiment.run_context` — the per-process ``RunContext`` (run_id,
  seed, started_at, git_sha, model_ids, config_digest, kaine_version) plus a
  process-global accessor mirroring ``kaine.security.crypto.get_state_encryptor``.
* :mod:`kaine.experiment.manifest` — atomic write of a run manifest.
* :mod:`kaine.experiment.verdict` — the shared ``Outcome``/``Verdict`` schema the
  experiments report through.
* :mod:`kaine.experiment.run_records` — post-run loader that decrypts + parses
  every JSONL sink file and groups records by run/stream.
* :mod:`kaine.experiment.admissibility` — run completeness gate (tick/seq
  contiguity, expected streams) producing an ``AdmissibilityReport``.
* :mod:`kaine.experiment.log_schema` — declarative physical-range validation of
  logged numbers (``sweep_run`` → ``Violation`` list).
* :mod:`kaine.experiment.stability` — the multi-seed stability harness
  (``run_multi_seed`` / ``assert_stable`` → ``StabilityReport``): the longitudinal
  control that runs an experiment across several seeds and asserts the summary
  statistics (mean / std / CV / verdict distribution) are stable.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kaine.experiment.manifest import write_manifest
from kaine.experiment.run_records import RunRecords, load_run_records
from kaine.experiment.run_context import (
    RunContext,
    compute_config_digest,
    compute_git_sha,
    get_run_context,
    mint_run_context,
    set_run_context,
)
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.stability import (
    StabilityError,
    StabilityReport,
    assert_stable,
    run_multi_seed,
)
from kaine.experiment.verdict import Outcome, Verdict

if TYPE_CHECKING:  # for type checkers / IDEs; not imported at runtime
    from kaine.experiment.admissibility import AdmissibilityReport, scan_run
    from kaine.experiment.log_schema import Violation, sweep_run


# The admissibility / log_schema modules each carry a ``__main__`` CLI. Importing
# them eagerly here makes ``python -m kaine.experiment.admissibility`` re-import a
# module already present in ``sys.modules`` (a runpy RuntimeWarning). Expose their
# public symbols lazily so the package API is unchanged but the CLIs stay clean.
_LAZY = {
    "AdmissibilityReport": "kaine.experiment.admissibility",
    "scan_run": "kaine.experiment.admissibility",
    "Violation": "kaine.experiment.log_schema",
    "sweep_run": "kaine.experiment.log_schema",
}


def __getattr__(name: str) -> Any:
    module_path = _LAZY.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module_path), name)


__all__ = [
    "set_global_seed",
    "RunContext",
    "set_run_context",
    "get_run_context",
    "mint_run_context",
    "compute_git_sha",
    "compute_config_digest",
    "write_manifest",
    "Outcome",
    "Verdict",
    "StabilityReport",
    "StabilityError",
    "run_multi_seed",
    "assert_stable",
    "RunRecords",
    "load_run_records",
    "AdmissibilityReport",
    "scan_run",
    "Violation",
    "sweep_run",
]
