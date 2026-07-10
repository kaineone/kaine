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
import re
import tomllib
from pathlib import Path
from typing import Any

# Canonical paths (relative to the working directory, as the rest of the
# codebase already assumes for config/kaine.toml).
SHIPPED_CONFIG_PATH = Path("config/kaine.toml")
OPERATOR_CONFIG_PATH = Path("config/kaine.operator.toml")

# Named deployment-tier profiles (openspec deployment-tiers) live here as TOML
# overlays applied BETWEEN the shipped defaults and the operator's local working
# config, so an operator override still wins. Tier 2 is the default; selecting no
# profile behaves exactly like the current workstation deployment.
PROFILES_DIR = Path("config/profiles")

# Env var the operator sets to pick a profile, e.g. KAINE_PROFILE=tier1.
PROFILE_ENV_VAR = "KAINE_PROFILE"

# A profile name is a filesystem-safe slug (no path traversal): lowercase
# letters, digits, and underscores only. The name is turned into
# ``config/profiles/<name>.toml`` — the slug guard keeps a hostile or fat-
# fingered value from escaping that directory.
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


class ProfileError(ValueError):
    """Raised when a selected tier profile name is invalid or its file is absent.

    A profile the operator explicitly asked for that cannot be found is an error,
    not a silent fall-through to Tier 2 — silently ignoring the request would run
    the wrong deployment while looking like it honored the selection.
    """


def resolve_profile_name(
    explicit: str | None = None, *, env: dict[str, str] | None = None
) -> str | None:
    """Resolve the selected profile name from an explicit value or the env var.

    An explicit value (e.g. from ``--profile``) wins over ``KAINE_PROFILE``.
    Returns ``None`` when neither is set (→ Tier 2 default). Validates the slug
    and raises :class:`ProfileError` on a malformed name.
    """
    source = os.environ if env is None else env
    name = (explicit if explicit is not None else source.get(PROFILE_ENV_VAR)) or ""
    name = name.strip()
    if not name:
        return None
    if not _PROFILE_NAME_RE.match(name):
        raise ProfileError(
            f"invalid profile name {name!r}: expected a slug of [a-z0-9_]"
        )
    return name


def profile_path(name: str, *, profiles_dir: str | os.PathLike[str] = PROFILES_DIR) -> Path:
    """Return the overlay path for a validated profile ``name``.

    Raises :class:`ProfileError` on a malformed name (defence in depth against
    path traversal even if a caller skips :func:`resolve_profile_name`).
    """
    if not _PROFILE_NAME_RE.match(name or ""):
        raise ProfileError(f"invalid profile name {name!r}")
    return Path(profiles_dir) / f"{name}.toml"


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
    *,
    profile: str | None = None,
    profiles_dir: str | os.PathLike[str] = PROFILES_DIR,
) -> dict[str, Any]:
    """Load the layered KAINE config: shipped → tier profile → operator override.

    Load order (each layer deep-merged over the last, later wins):

    1. the shipped ``config/kaine.toml`` (Tier-2 workstation defaults);
    2. an optional selected tier profile ``config/profiles/<profile>.toml``
       (module toggles + backends + device/cycle-rate hints for a host class);
    3. an optional operator override at ``operator_path`` — the operator's local
       working config, which STILL WINS so their toggles and private voice are
       never overridden by a profile.

    ``profile`` is the resolved profile name (see :func:`resolve_profile_name`),
    or ``None`` for the Tier-2 default (no overlay → behaviour identical to
    today). A selected profile whose file is missing raises :class:`ProfileError`
    — an explicit selection is honored or reported, never silently ignored.

    A missing operator file is harmless; a malformed one is tolerated (falls back
    without it). Raises :class:`FileNotFoundError` if the shipped file is absent.
    """
    shipped_path = Path(path)
    if not shipped_path.exists():
        raise FileNotFoundError(f"config/kaine.toml not found at {shipped_path}")
    with shipped_path.open("rb") as fh:
        merged = tomllib.load(fh)

    # Layer 2: the selected tier profile (between shipped and operator).
    if profile:
        prof_path = profile_path(profile, profiles_dir=profiles_dir)
        if not prof_path.exists():
            raise ProfileError(
                f"profile {profile!r} selected but {prof_path} does not exist"
            )
        with prof_path.open("rb") as fh:
            merged = deep_merge(merged, tomllib.load(fh))

    # Layer 3: the operator's local working config (still wins over the profile).
    op_path = Path(operator_path)
    if not op_path.exists():
        return merged
    try:
        with op_path.open("rb") as fh:
            override = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        # A malformed or unreadable operator file must never break boot; fall
        # back to the shipped+profile configuration.
        return merged
    return deep_merge(merged, override)
