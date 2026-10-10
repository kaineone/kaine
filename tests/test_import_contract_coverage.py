# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-check that every top-level kaine package/module is covered by one of
the import-linter contracts (or is honestly exempt)."""

from __future__ import annotations

import pathlib
import tomllib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_KAINE_DIR = _ROOT / "kaine"
_PYPROJECT = _ROOT / "pyproject.toml"

CONTRACT_1_NAME = "Core must not import the evaluation sidecar (only the two __main__ seams)"
NEUTRAL_CONTRACT_NAME = (
    "Boundary-neutral shared homes depend on neither core-runtime nor evaluation"
)

EXEMPT: dict[str, str] = {
    "evaluation": "the forbidden evaluation sidecar is the target of contract 1, not a source",
}


def _top_level_kaine_names() -> list[str]:
    names: list[str] = []
    for path in _KAINE_DIR.iterdir():
        if path.name.startswith("__") or path.name.startswith(".") or path.name == "__pycache__":
            continue
        if path.is_file() and path.suffix == ".py":
            names.append(path.stem)
        elif path.is_dir() and (path / "__init__.py").exists():
            names.append(path.name)
    return sorted(names)


def _contract_source_modules(cfg: dict) -> tuple[set[str], set[str]]:
    contracts = cfg["tool"]["importlinter"]["contracts"]
    by_name = {c["name"]: c for c in contracts}
    core = set(by_name[CONTRACT_1_NAME].get("source_modules", []))
    neutral = set(by_name[NEUTRAL_CONTRACT_NAME].get("source_modules", []))
    return core, neutral


def test_every_top_level_kaine_module_is_classified():
    cfg = tomllib.loads(_PYPROJECT.read_text())
    core_sources, neutral_sources = _contract_source_modules(cfg)

    unclassified: list[str] = []
    for name in _top_level_kaine_names():
        candidates = {f"kaine.{name}"}
        if not (candidates & core_sources or candidates & neutral_sources or name in EXEMPT):
            unclassified.append(name)

    if unclassified:
        assert False, (
            f"Unclassified top-level kaine packages/modules: {sorted(unclassified)}. "
            "Add core-runtime sources to contract 1 ('Core must not import the evaluation "
            "sidecar...') source_modules, add boundary-neutral shared homes to the "
            "boundary-neutral contract source_modules, or add an honest EXEMPT entry in "
            "this test."
        )
