# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Structural import-boundary contracts, run as a fast pytest gate.

This shells out to ``lint-imports`` (import-linter) and asserts every
contract in ``[tool.importlinter]`` (pyproject.toml) is kept. It is the
in-suite mirror of the pre-commit hook and the dedicated CI job: a boundary
violation fails here in seconds instead of being discovered only by the full
~8-minute run.

Select it on its own with::

    .venv/bin/pytest -k import_boundary

The load-bearing contract is the sidecar boundary — kaine.evaluation is the
observe-only research subsystem and core runtime must run with it absent (only
the two ``__main__`` seams may wire it in). See docs/architecture-boundaries.md.

If import-linter is not installed (a minimal install without the ``test``
extra) this test skips cleanly rather than failing — the contract is still
enforced wherever the dev/CI tooling is present.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _lint_imports_cmd() -> list[str] | None:
    """Resolve the lint-imports entrypoint, preferring the project venv."""
    venv_bin = REPO_ROOT / ".venv" / "bin" / "lint-imports"
    if venv_bin.exists():
        return [str(venv_bin)]
    found = shutil.which("lint-imports")
    if found:
        return [found]
    # Fall back to the module form if the import-linter package is importable.
    try:
        import importlinter  # noqa: F401
    except ImportError:
        return None
    return ["python", "-m", "importlinter"]


def test_import_boundary_contracts_kept():
    cmd = _lint_imports_cmd()
    if cmd is None:
        pytest.skip("import-linter not installed (install the .[test] extra)")

    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        "import-boundary contracts BROKEN — a structural architecture "
        "boundary was violated. See docs/architecture-boundaries.md.\n\n"
        f"{output}"
    )
    # Belt-and-suspenders: confirm we actually ran contracts (guards against a
    # misconfiguration that exits 0 without checking anything).
    assert "Contracts:" in output and "0 broken" in output, output


def test_external_train_script_not_imported_by_kaine():
    """The out-of-process trainer entry script lives OUTSIDE the kaine package
    and runs in a separate (external) interpreter. It must never appear in the
    kaine import graph — otherwise the runtime venv would try to import the
    heavy unsloth stack, defeating the whole out-of-process design and breaking
    the sidecar/import boundary.

    A static check: no first-party module under kaine/ may reference the script
    via an import statement. (import-linter already guards the kaine graph; this
    pins the specific external-script invariant in a fast, dependency-free way.)
    """
    kaine_pkg = REPO_ROOT / "kaine"
    offenders: list[str] = []
    for py_file in kaine_pkg.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        # The script is invoked by *path* (subprocess argv), never imported.
        # Catch both an accidental module import and a stray `import` of it.
        if "import hypnos_external_train" in text or "from hypnos_external_train" in text:
            offenders.append(str(py_file.relative_to(REPO_ROOT)))
    assert not offenders, (
        "scripts/hypnos_external_train.py must never be imported by kaine "
        f"(it runs in the external trainer env). Offenders: {offenders}"
    )

