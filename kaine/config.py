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

Deployment tiers (tier0..tier3) are applied as a separate layer between the
module-selection profile and the operator override, so recording a tier only
ever bounds backends and devices; it never replaces the selected module set.
Tier files carry an advisory ``[tier]`` table (``unsupported_modules``,
``oscillator_supported``); they are forbidden from containing a ``[modules]``
table or an ``[oscillator].enabled`` key, which would otherwise silently change
the module set.
"""
from __future__ import annotations

import logging
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

# Env var the operator sets to override a recorded tier, e.g. KAINE_TIER=tier1.
TIER_ENV_VAR = "KAINE_TIER"

# A profile/tier name is a filesystem-safe slug (no path traversal): lowercase
# letters, digits, and underscores only. The name is turned into
# ``config/profiles/<name>.toml`` — the slug guard keeps a hostile or fat-
# fingered value from escaping that directory.
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


log = logging.getLogger(__name__)


class ProfileError(ValueError):
    """Raised when a selected tier profile name is invalid or its file is absent.

    A profile the operator explicitly asked for that cannot be found is an error,
    not a silent fall-through to Tier 2 — silently ignoring the request would run
    the wrong deployment while looking like it honored the selection.
    """


class ConfigShapeError(ProfileError):
    """Raised when the merged configuration violates a runtime shape rule.

    Subclasses :class:`ProfileError` so the pre-boot check and the cycle
    report it as a configuration error without additional handlers.
    """


def resolve_profile_name(
    explicit: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> str | None:
    """Resolve the selected module profile name from explicit value or env var.

    Resolution order (later layers only consulted when earlier layers are unset):

    1. ``explicit`` value (e.g. from ``--profile``).
    2. ``KAINE_PROFILE`` environment variable (or the supplied ``env`` mapping).

    Returns ``None`` when neither is set. Validates the slug and raises
    :class:`ProfileError` on a malformed name.
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


def resolve_tier_name(
    *,
    env: dict[str, str] | None = None,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
    profiles_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Resolve the deployment tier name from env var or operator overlay.

    Resolution order:

    1. ``KAINE_TIER`` environment variable (or the supplied ``env`` mapping).
    2. ``[deployment].tier`` in the operator overlay at ``operator_path``
       (defaults to :data:`OPERATOR_CONFIG_PATH`).

    Returns ``None`` when neither is set, the overlay is missing, or the overlay
    is malformed. Validates the slug and raises :class:`ProfileError` when the
    name is malformed, its profile file does not exist, or the file is not a
    deployment tier (it lacks the advisory ``[tier]`` table).
    """
    source = os.environ if env is None else env
    name = str(source.get(TIER_ENV_VAR, "")).strip()
    if name:
        if not _PROFILE_NAME_RE.match(name):
            raise ProfileError(
                f"invalid tier name {name!r}: expected a slug of [a-z0-9_]"
            )
        _require_tier_profile(name, profiles_dir=profiles_dir)
        return name

    op_path = Path(operator_path)
    if not op_path.exists():
        return None
    try:
        with op_path.open("rb") as fh:
            overlay = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    deployment = overlay.get("deployment")
    if not isinstance(deployment, dict):
        return None
    name = str(deployment.get("tier", "")).strip()
    if not name:
        return None
    if not _PROFILE_NAME_RE.match(name):
        raise ProfileError(
            f"invalid tier name {name!r}: expected a slug of [a-z0-9_]"
        )
    _require_tier_profile(name, profiles_dir=profiles_dir)
    return name


def profile_path(name: str, *, profiles_dir: str | os.PathLike[str] | None = None) -> Path:
    """Return the overlay path for a validated profile ``name``.

    Raises :class:`ProfileError` on a malformed name (defence in depth against
    path traversal even if a caller skips :func:`resolve_profile_name` or
    :func:`resolve_tier_name`).
    """
    if profiles_dir is None:
        profiles_dir = PROFILES_DIR
    if not _PROFILE_NAME_RE.match(name or ""):
        raise ProfileError(f"invalid profile name {name!r}")
    return Path(profiles_dir) / f"{name}.toml"


def _require_tier_profile(
    name: str,
    *,
    profiles_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load and validate a deployment-tier profile file.

    Raises :class:`ProfileError` if the file is missing, malformed, or does
    not contain the advisory ``[tier]`` table.
    """
    tier_path = profile_path(name, profiles_dir=profiles_dir)
    if not tier_path.exists():
        raise ProfileError(
            f"tier {name!r} selected but {tier_path} does not exist"
        )
    try:
        with tier_path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"tier {name!r} is malformed TOML: {exc}") from exc
    if "tier" not in raw:
        raise ProfileError(
            f"{name} is not a deployment tier (no [tier] table); "
            "tiers are config/profiles/tier0..tier3"
        )
    return raw


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


def validate_config_shape(config: dict[str, Any]) -> None:
    """Validate the shape of sections the runtime relies on.

    Checks the merged configuration for the section/key types the runtime
    reads directly. Unknown sections and keys pass through untouched. A
    violation raises :class:`ConfigShapeError` naming the dotted key, the
    expected type and the actual type; the message never includes the
    offending value.
    """
    modules = config.get("modules")
    if modules is not None:
        if not isinstance(modules, dict):
            raise ConfigShapeError(
                f"modules expected table, got {type(modules).__name__}"
            )
        for key, value in modules.items():
            if not isinstance(value, bool):
                raise ConfigShapeError(
                    f"modules.{key} expected bool, got {type(value).__name__}"
                )

    tier = config.get("tier")
    if tier is not None:
        if not isinstance(tier, dict):
            raise ConfigShapeError(
                f"tier expected table, got {type(tier).__name__}"
            )
        name = tier.get("name")
        if name is not None and not isinstance(name, str):
            raise ConfigShapeError(
                f"tier.name expected string, got {type(name).__name__}"
            )
        unsupported = tier.get("unsupported_modules")
        if unsupported is not None:
            if not isinstance(unsupported, list):
                raise ConfigShapeError(
                    f"tier.unsupported_modules expected list, got {type(unsupported).__name__}"
                )
            for idx, item in enumerate(unsupported):
                if not isinstance(item, str):
                    raise ConfigShapeError(
                        f"tier.unsupported_modules[{idx}] expected string, got {type(item).__name__}"
                    )
        osc_supp = tier.get("oscillator_supported")
        if osc_supp is not None and not isinstance(osc_supp, bool):
            raise ConfigShapeError(
                f"tier.oscillator_supported expected bool, got {type(osc_supp).__name__}"
            )

    oscillator = config.get("oscillator")
    if oscillator is not None:
        if not isinstance(oscillator, dict):
            raise ConfigShapeError(
                f"oscillator expected table, got {type(oscillator).__name__}"
            )
        enabled = oscillator.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise ConfigShapeError(
                f"oscillator.enabled expected bool, got {type(enabled).__name__}"
            )

    deployment = config.get("deployment")
    if isinstance(deployment, dict):
        tier_name = deployment.get("tier")
        if tier_name is not None and not isinstance(tier_name, str):
            raise ConfigShapeError(
                f"deployment.tier expected string, got {type(tier_name).__name__}"
            )

    security = config.get("security")
    if isinstance(security, dict):
        state_encryption = security.get("state_encryption")
        if state_encryption is not None and not isinstance(state_encryption, dict):
            raise ConfigShapeError(
                f"security.state_encryption expected table, got {type(state_encryption).__name__}"
            )
        if isinstance(state_encryption, dict):
            enabled = state_encryption.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                raise ConfigShapeError(
                    f"security.state_encryption.enabled expected bool, got {type(enabled).__name__}"
                )


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
    profiles_dir: str | os.PathLike[str] | None = None,
    tier: str | None = None,
    strict_operator: bool = False,
) -> dict[str, Any]:
    """Load the layered KAINE config: shipped → profile → tier → operator override.

    Load order (each layer deep-merged over the last, later wins):

    1. the shipped ``config/kaine.toml`` (every module disabled by default);
    2. an optional selected module profile
       ``config/profiles/<profile>.toml`` (e.g. the base-thesis
       ``thesis_test`` profile);
    3. an optional deployment-tier profile
       ``config/profiles/<tier>.toml`` (bounds backends and devices; never
       changes which modules are enabled);
    4. an optional operator override at ``operator_path`` — the operator's local
       working config, which STILL WINS so their toggles and private voice are
       never overridden by a profile or tier.

    ``profile`` is the resolved module profile name (see
    :func:`resolve_profile_name`). ``tier`` is the resolved deployment tier name
    (see :func:`resolve_tier_name`). Either may be ``None`` to skip that layer.
    A selected profile or tier whose file is missing raises :class:`ProfileError`
    — an explicit selection is honored or reported, never silently ignored.

    A tier file must contain an advisory ``[tier]`` table; otherwise it is not a
    deployment tier and raises :class:`ProfileError`.

    A tier file that contains a ``[modules]`` table or an
    ``[oscillator].enabled`` key raises :class:`ProfileError` ("tier <name> may
    not set module toggles; tiers only bound backends and devices"), because a
    deployment tier must never silently change the enabled module set.

    A missing operator file is harmless; a malformed one is tolerated by
    default (falls back with a logged warning). When ``strict_operator`` is true,
    an existing but unreadable/unparsable operator file raises
    :class:`ProfileError`. Raises :class:`FileNotFoundError` if the shipped file
    is absent.

    After merging all layers, the result is validated with
    :func:`validate_config_shape`; shape violations raise
    :class:`ConfigShapeError`.
    """
    if profiles_dir is None:
        profiles_dir = PROFILES_DIR
    shipped_path = Path(path)
    if not shipped_path.exists():
        raise FileNotFoundError(f"config/kaine.toml not found at {shipped_path}")
    with shipped_path.open("rb") as fh:
        merged = tomllib.load(fh)

    # Layer 2: the selected module profile.
    if profile:
        prof_path = profile_path(profile, profiles_dir=profiles_dir)
        if not prof_path.exists():
            raise ProfileError(
                f"profile {profile!r} selected but {prof_path} does not exist"
            )
        with prof_path.open("rb") as fh:
            merged = deep_merge(merged, tomllib.load(fh))

    # Layer 3: the deployment tier overlay (between profile and operator).
    if tier:
        tier_raw = _require_tier_profile(tier, profiles_dir=profiles_dir)
        if tier != profile:
            if "modules" in tier_raw:
                raise ProfileError(
                    f"tier {tier!r} may not set module toggles; tiers only bound backends and devices"
                )
            osc = tier_raw.get("oscillator")
            if isinstance(osc, dict) and "enabled" in osc:
                raise ProfileError(
                    f"tier {tier!r} may not set module toggles; tiers only bound backends and devices"
                )
            merged = deep_merge(merged, tier_raw)

    # Layer 4: the operator's local working config (still wins over everything).
    op_path = Path(operator_path)
    if not op_path.exists():
        validate_config_shape(merged)
        return merged
    try:
        with op_path.open("rb") as fh:
            override = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        if strict_operator:
            raise ProfileError(
                f"operator config {op_path} could not be read or parsed: {type(exc).__name__}: {exc}"
            ) from exc
        log.warning(
            "operator config %s could not be read or parsed: %s: %s",
            op_path,
            type(exc).__name__,
            exc,
        )
        validate_config_shape(merged)
        return merged
    merged = deep_merge(merged, override)
    validate_config_shape(merged)
    return merged


def load_runtime_config(
    path: str | os.PathLike[str] = SHIPPED_CONFIG_PATH,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
    *,
    profile: str | None = None,
    env: dict[str, str] | None = None,
    profiles_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load the runtime configuration used by the cycle and the pre-boot check.

    Resolves the module-selection profile and the deployment-tier layer, then
    returns the merged dict from :func:`load_kaine_config`.

    Resolution:

    * ``profile`` (e.g. ``--profile``) wins, then ``KAINE_PROFILE`` in ``env``.
    * When neither profile argument is set and ``config/profiles/thesis_test.toml``
      exists, the base-thesis ``thesis_test`` profile is applied. This is the
      project's default entity configuration: a fresh install that boots the cycle
      with no explicit profile gets the five predictive-workspace processors,
      STT off, and the self-initiated voice.
    * The deployment tier is resolved by :func:`resolve_tier_name` (``KAINE_TIER``
      env, then ``[deployment].tier`` from the operator overlay) and layered on
      top of the module profile.

    The tier only bounds backends and devices for the host hardware; it never
    replaces the selected module set. An explicit profile selection is honored
    or reported, never silently ignored.

    This path is strict about the operator overlay: an operator file that exists
    but cannot be read or parsed raises :class:`ProfileError` rather than being
    skipped.
    """
    resolved_profile = resolve_profile_name(profile, env=env)
    if resolved_profile is None:
        thesis_path = profile_path("thesis_test", profiles_dir=profiles_dir)
        if thesis_path.exists():
            resolved_profile = "thesis_test"
    resolved_tier = resolve_tier_name(
        env=env, operator_path=operator_path, profiles_dir=profiles_dir
    )
    return load_kaine_config(
        path,
        operator_path,
        profile=resolved_profile,
        tier=resolved_tier,
        profiles_dir=profiles_dir,
        strict_operator=True,
    )
