# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared KAINE configuration loader with an operator override layer.

KAINE ships a single committed ``config/kaine.toml`` with every module
disabled (a guard test pins it all-off at HEAD). Operators must not edit that
file's toggles, because their local choices would either be committed by
accident or trip the guard. Instead, the first-run wizard
(``python -m kaine.setup``) writes a gitignored ``config/kaine.operator.toml``
that this loader deep-merges over the shipped file — operator values win.

Both the cognitive cycle entrypoint and the Nexus config readers route through
:func:`load_kaine_config` so an operator override applies uniformly everywhere
the configuration is consumed.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

# Canonical paths (relative to the working directory, as the rest of the
# codebase already assumes for config/kaine.toml).
SHIPPED_CONFIG_PATH = Path("config/kaine.toml")
OPERATOR_CONFIG_PATH = Path("config/kaine.operator.toml")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base``, returning a NEW dict.

    - Nested dicts merge key-by-key (so an override that sets one key in a
      table preserves the table's other keys).
    - Scalars and lists from ``override`` replace the corresponding value in
      ``base`` outright.
    - Neither input is mutated.
    """
    result: dict[str, Any] = dict(base)
    for key, ov in override.items():
        bv = result.get(key)
        if isinstance(bv, dict) and isinstance(ov, dict):
            result[key] = deep_merge(bv, ov)
        elif isinstance(ov, dict):
            # Override introduces a table where base had none (or a scalar).
            result[key] = deep_merge({}, ov)
        else:
            result[key] = ov
    return result


def require_known_keys(
    section: dict[str, Any], allowed: set[str], table_name: str = ""
) -> None:
    """Raise ``ValueError`` if ``section`` carries keys outside ``allowed``.

    Shared unknown-config-key guard for every ``from_section``-style loader so
    a typo'd TOML key fails loudly and consistently instead of being silently
    swallowed. ``table_name`` is the TOML table name woven into the message
    (e.g. ``"[spot]"`` or ``"[gpu_preflight]"``); pass ``""`` for an
    un-named section, which yields the bare ``"unknown config keys: ..."``.
    """
    extra = set(section) - allowed
    if extra:
        label = f"{table_name} " if table_name else ""
        raise ValueError(
            f"unknown {label}config keys: {sorted(extra)} "
            f"(allowed: {sorted(allowed)})"
        )


def load_kaine_config(
    path: str | os.PathLike[str] = SHIPPED_CONFIG_PATH,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
) -> dict[str, Any]:
    """Load the shipped config and deep-merge an optional operator override.

    The shipped file at ``path`` is parsed with :mod:`tomllib`. If an operator
    override exists at ``operator_path`` it is parsed and deep-merged on top
    (operator values win). A missing operator file is harmless — the shipped
    configuration is returned unchanged. This never raises on a missing
    operator file; it does raise :class:`FileNotFoundError` if the shipped
    file itself is absent (the caller is expected to handle that the same way
    it always has).
    """
    shipped_path = Path(path)
    if not shipped_path.exists():
        raise FileNotFoundError(f"config/kaine.toml not found at {shipped_path}")
    with shipped_path.open("rb") as fh:
        shipped = tomllib.load(fh)

    op_path = Path(operator_path)
    if not op_path.exists():
        return shipped
    try:
        with op_path.open("rb") as fh:
            override = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        # A malformed or unreadable operator file must never break boot; fall
        # back to the shipped configuration.
        return shipped
    return deep_merge(shipped, override)
