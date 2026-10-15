# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared KAINE configuration loader with an operator override layer.

KAINE ships a single committed ``config/kaine.toml`` with every module
disabled (a guard test pins it all-off at HEAD). Operators must not edit that
file's toggles, because their local choices would either be committed by
accident or trip the guard. Instead, the first-run wizard
(``python -m kaine.setup``) writes a gitignored ``config/kaine.operator.toml``
that this loader deep-merges over the shipped file — operator values win.

The cognitive cycle entrypoint and the dashboard route through
:func:`load_kaine_config`, so an operator override applies wherever the
configuration is consumed. The dashboard's own ``[dashboard]`` section is the exception:
:mod:`kaine.dashboard.config` reads it from ``config/kaine.toml``,
``config/kaine.operator.toml`` and ``config/secrets.toml`` directly.

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

from kaine import legacy_aliases, legacy_names
from kaine.storage import normalize_storage_paths

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

# Study configurations: overlays a study run selects, applied over the operator config.
STUDIES_DIR = Path("config/studies")

# e.g. KAINE_STUDY=workspace_mediation_matched.
STUDY_ENV_VAR = "KAINE_STUDY"

# The only tables a study configuration may set; anything else (the module set,
# preservation, the coherence layer) stays the operator's.
STUDY_ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "language",
        "workspace",
        "experiment",
        "individuation",
        "planned_test",
        "positive_control",
        "audition",
    }
)

# Tables a study may set only partly, and the keys it may set in them.
STUDY_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "audition": frozenset({"tone_rule"}),
}

# A profile/tier name is a filesystem-safe slug (no path traversal): lowercase
# letters, digits, and underscores only. The name is turned into
# ``config/profiles/<name>.toml`` — the slug guard keeps a hostile or fat-
# fingered value from escaping that directory.
_PROFILE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


log = logging.getLogger(__name__)

# The module profile applied when none is selected.
DEFAULT_PROFILE = "first_configuration"

# Old profile names are read until legacy_names.ALIAS_LAST_RELEASE.
PROFILE_ALIASES: dict[str, str] = {"thesis_test": "first_configuration"}

_profile_alias_warned: set[str] = set()


def canonical_profile_name(name: str) -> str:
    """Return the canonical profile name, mapping deprecated aliases to their new names."""
    new = PROFILE_ALIASES.get(name, name)
    if new != name and name not in _profile_alias_warned:
        _profile_alias_warned.add(name)
        log.warning(
            "profile %s is deprecated, use %s; it is read until %s",
            name,
            new,
            legacy_names.ALIAS_LAST_RELEASE,
        )
    return new


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
    :class:`ProfileError` on a malformed name. An old profile name in
    PROFILE_ALIASES resolves to its new name with a deprecation warning.
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
    return canonical_profile_name(name)


def resolve_study_name(
    explicit: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> str | None:
    """Resolve the selected study configuration name from explicit value or env var.

    Resolution order (later layers only consulted when earlier layers are unset):

    1. ``explicit`` value.
    2. ``KAINE_STUDY`` environment variable (or the supplied ``env`` mapping).

    Returns ``None`` when neither is set. Validates the slug and raises
    :class:`ProfileError` on a malformed name.
    """
    source = os.environ if env is None else env
    name = (explicit if explicit is not None else source.get(STUDY_ENV_VAR)) or ""
    name = name.strip()
    if not name:
        return None
    if not _PROFILE_NAME_RE.match(name):
        raise ProfileError(
            f"invalid study name {name!r}: expected a slug of [a-z0-9_]"
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


def study_path(name: str, *, studies_dir: str | os.PathLike[str] | None = None) -> Path:
    """Return the overlay path for a validated study ``name``.

    Raises :class:`ProfileError` on a malformed name (defence in depth against
    path traversal even if a caller skips :func:`resolve_study_name`).
    """
    if studies_dir is None:
        studies_dir = STUDIES_DIR
    if not _PROFILE_NAME_RE.match(name or ""):
        raise ProfileError(f"invalid study name {name!r}")
    return Path(studies_dir) / f"{name}.toml"


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
    embedding = config.get("embedding")
    if embedding is not None:
        if not isinstance(embedding, dict):
            raise ConfigShapeError(
                f"embedding expected table, got {type(embedding).__name__}"
            )
        for key in ("backend", "model_id", "device", "model_path"):
            value = embedding.get(key)
            if value is not None and not isinstance(value, str):
                raise ConfigShapeError(
                    f"embedding.{key} expected string, got {type(value).__name__}"
                )

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

    social_cognition = config.get("social_cognition")
    if isinstance(social_cognition, dict):
        operator_sources = social_cognition.get("operator_sources")
        if operator_sources is not None:
            if not isinstance(operator_sources, list):
                raise ConfigShapeError(
                    f"social_cognition.operator_sources expected list of strings, got {type(operator_sources).__name__}"
                )
            for idx, item in enumerate(operator_sources):
                if not isinstance(item, str):
                    raise ConfigShapeError(
                        f"social_cognition.operator_sources[{idx}] expected string, got {type(item).__name__}"
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

    plugins = config.get("plugins")
    if plugins is not None:
        if not isinstance(plugins, dict):
            raise ConfigShapeError(
                f"plugins expected table, got {type(plugins).__name__}"
            )
        enabled = plugins.get("enabled")
        if enabled is not None:
            if not isinstance(enabled, list):
                raise ConfigShapeError(
                    f"plugins.enabled expected list, got {type(enabled).__name__}"
                )
            for idx, item in enumerate(enabled):
                if not isinstance(item, str):
                    raise ConfigShapeError(
                        f"plugins.enabled[{idx}] expected string, got {type(item).__name__}"
                    )
        for key, value in plugins.items():
            if key == "enabled":
                continue
            if not isinstance(value, dict):
                raise ConfigShapeError(
                    f"plugins.{key} expected table, got {type(value).__name__}"
                )

    security = config.get("security")
    if security is not None:
        if not isinstance(security, dict):
            raise ConfigShapeError(
                f"security expected table, got {type(security).__name__}"
            )
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

    deployment = config.get("deployment")
    if deployment is not None:
        if not isinstance(deployment, dict):
            raise ConfigShapeError(
                f"deployment expected table, got {type(deployment).__name__}"
            )
        tier_name = deployment.get("tier")
        if tier_name is not None and not isinstance(tier_name, str):
            raise ConfigShapeError(
                f"deployment.tier expected string, got {type(tier_name).__name__}"
            )

    hardware = config.get("hardware")
    if hardware is not None:
        if not isinstance(hardware, dict):
            raise ConfigShapeError(
                f"hardware expected table, got {type(hardware).__name__}"
            )
        allowed = hardware.get("allowed_devices")
        if allowed is not None:
            if not isinstance(allowed, list) or not allowed:
                raise ConfigShapeError(
                    "hardware.allowed_devices expected a non-empty list"
                )
            for idx, entry in enumerate(allowed):
                if not isinstance(entry, str):
                    raise ConfigShapeError(
                        f"hardware.allowed_devices[{idx}] expected string, got {type(entry).__name__}"
                    )
        cpu_threads = hardware.get("cpu_threads")
        if cpu_threads is not None:
            if (
                not isinstance(cpu_threads, int)
                or isinstance(cpu_threads, bool)
                or cpu_threads < 1
            ):
                raise ConfigShapeError(
                    f"hardware.cpu_threads expected integer >= 1, got {type(cpu_threads).__name__}"
                )

    storage = config.get("storage")
    if storage is not None:
        if not isinstance(storage, dict):
            raise ConfigShapeError(
                f"storage expected table, got {type(storage).__name__}"
            )
        data_root = storage.get("data_root")
        if data_root is not None:
            if not isinstance(data_root, str) or data_root == "":
                raise ConfigShapeError(
                    f"storage.data_root expected non-empty string, got {type(data_root).__name__}"
                )
        min_free_gb = storage.get("min_free_gb")
        if min_free_gb is not None:
            if isinstance(min_free_gb, bool) or not isinstance(
                min_free_gb, (int, float)
            ):
                raise ConfigShapeError(
                    f"storage.min_free_gb expected number >= 0, got {type(min_free_gb).__name__}"
                )
            if min_free_gb < 0:
                raise ConfigShapeError(
                    f"storage.min_free_gb expected number >= 0, got {type(min_free_gb).__name__}"
                )

    services = config.get("services")
    if services is not None:
        if not isinstance(services, dict):
            raise ConfigShapeError(
                f"services expected table, got {type(services).__name__}"
            )
        for name, table in services.items():
            if not isinstance(table, dict):
                raise ConfigShapeError(
                    f"services.{name} expected table, got {type(table).__name__}"
                )
            shared = table.get("shared")
            if shared is not None and not isinstance(shared, bool):
                raise ConfigShapeError(
                    f"services.{name}.shared expected bool, got {type(shared).__name__}"
                )
            process_names = table.get("process_names")
            if process_names is not None:
                if not isinstance(process_names, list):
                    raise ConfigShapeError(
                        f"services.{name}.process_names expected list, got {type(process_names).__name__}"
                    )
                for idx, pn in enumerate(process_names):
                    if not isinstance(pn, str):
                        raise ConfigShapeError(
                            f"services.{name}.process_names[{idx}] expected string"
                        )

def require_known_keys(
    section: dict[str, Any], allowed: set[str], table_name: str = ""
) -> None:
    """Raise ``ValueError`` if ``section`` carries keys outside ``allowed``.

    Shared unknown-config-key guard for every ``from_section``-style loader so
    a typo'd TOML key fails loudly and consistently instead of being silently
    swallowed. ``table_name`` is the TOML table name woven into the message
    (e.g. ``"[supervisor]"`` or ``"[gpu_preflight]"``); pass ``""`` for an
    un-named section, which yields the bare ``"unknown config keys: ..."``.
    """
    extra = set(section) - allowed
    if extra:
        label = f"{table_name} " if table_name else ""
        raise ValueError(
            f"unknown {label}config keys: {sorted(extra)} "
            f"(allowed: {sorted(allowed)})"
        )


def _normalize_layer(layer: dict[str, Any], source: Path | str) -> dict[str, Any]:
    """Map deprecated table, key and value names in one parsed layer (task 5.1)."""
    try:
        return legacy_aliases.normalize_config_layer(layer, str(source))
    except legacy_aliases.LegacyNameConflict as exc:
        raise ProfileError(str(exc)) from exc


def _load_merged_config(
    path: str | os.PathLike[str] = SHIPPED_CONFIG_PATH,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
    *,
    profile: str | None = None,
    profiles_dir: str | os.PathLike[str] | None = None,
    tier: str | None = None,
    strict_operator: bool = False,
    study: str | None = None,
    studies_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load and merge layered KAINE configuration files (internal helper)."""
    if profiles_dir is None:
        profiles_dir = PROFILES_DIR
    if studies_dir is None:
        studies_dir = STUDIES_DIR
    shipped_path = Path(path)
    if not shipped_path.exists():
        raise FileNotFoundError(f"config/kaine.toml not found at {shipped_path}")
    with shipped_path.open("rb") as fh:
        merged = _normalize_layer(tomllib.load(fh), shipped_path)

    # Layer 2: the selected module profile.
    if profile:
        profile = canonical_profile_name(profile)
        prof_path = profile_path(profile, profiles_dir=profiles_dir)
        if not prof_path.exists():
            raise ProfileError(
                f"profile {profile!r} selected but {prof_path} does not exist"
            )
        with prof_path.open("rb") as fh:
            profile_layer = _normalize_layer(tomllib.load(fh), prof_path)
        merged = deep_merge(merged, profile_layer)

    # Layer 3: the deployment tier overlay (between profile and operator).
    if tier:
        tier_path = profile_path(tier, profiles_dir=profiles_dir)
        tier_raw = _normalize_layer(
            _require_tier_profile(tier, profiles_dir=profiles_dir), tier_path
        )
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

    # Layer 4: the operator's local working config.
    op_path = Path(operator_path)
    if op_path.exists():
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
        else:
            merged = deep_merge(merged, _normalize_layer(override, op_path))

    # Layer 5: the selected study overlay (applied last, after operator).
    if study:
        study_cfg_path = study_path(study, studies_dir=studies_dir)
        if not study_cfg_path.exists():
            raise ProfileError(
                f"study {study!r} selected but {study_cfg_path} does not exist"
            )
        with study_cfg_path.open("rb") as fh:
            study_raw = _normalize_layer(tomllib.load(fh), study_cfg_path)
        extra = sorted(set(study_raw) - STUDY_ALLOWED_TABLES)
        if extra:
            raise ProfileError(
                f"study {study!r} may set only the tables "
                f"{', '.join(sorted(STUDY_ALLOWED_TABLES))}; it also sets {', '.join(extra)}"
            )
        for table, keys in STUDY_ALLOWED_KEYS.items():
            if table in study_raw:
                section = study_raw[table]
                if not isinstance(section, dict):
                    raise ProfileError(
                        f"study {study!r} table [{table}] must be a dict, got {type(section).__name__}"
                    )
                bad = sorted(set(section) - keys)
                if bad:
                    raise ProfileError(
                        f"study {study!r} may set only {', '.join(sorted(keys))} in [{table}]; it also sets {', '.join(bad)}"
                    )
        merged = deep_merge(merged, study_raw)

    validate_config_shape(merged)
    return merged


def load_kaine_config(
    path: str | os.PathLike[str] = SHIPPED_CONFIG_PATH,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
    *,
    profile: str | None = None,
    profiles_dir: str | os.PathLike[str] | None = None,
    tier: str | None = None,
    strict_operator: bool = False,
    study: str | None = None,
    studies_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load the layered KAINE config: shipped → profile → tier → operator override → study overlay.

    Load order (each layer deep-merged over the last, later wins):

    1. the shipped ``config/kaine.toml`` (every module disabled by default);
    2. an optional selected module profile
       ``config/profiles/<profile>.toml`` (e.g. the first_configuration profile);
    3. an optional deployment-tier profile
       ``config/profiles/<tier>.toml`` (bounds backends and devices; never
       changes which modules are enabled);
    4. an optional operator override at ``operator_path`` — the operator's local
       working config, which STILL WINS so their toggles and private voice are
       never overridden by a profile or tier;
    5. an optional study configuration ``config/studies/<study>.toml``, which
       wins over the operator override, so a study run cannot be changed by the
       operator's local file.

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

    A study file may set only the ``[language]``, ``[workspace]``,
    ``[experiment]``, ``[individuation]``, ``[planned_test]``,
    ``[positive_control]`` and ``[audition]`` tables; any other table,
    ``[modules]`` included, raises :class:`ProfileError`. A study may also set
    ``[audition].tone_rule`` and no other ``[audition]`` key.

    A missing operator file is harmless; a malformed one is tolerated by
    default (falls back with a logged warning). When ``strict_operator`` is true,
    an existing but unreadable/unparsable operator file raises
    :class:`ProfileError`. Raises :class:`FileNotFoundError` if the shipped file
    is absent.

    After merging all layers, the result is validated with
    :func:`validate_config_shape`; shape violations raise
    :class:`ConfigShapeError`.

    Growing-data paths are then resolved under ``[storage].data_root`` /
    ``KAINE_DATA_ROOT`` by :func:`kaine.storage.normalize_storage_paths`.
    """
    return normalize_storage_paths(
        _load_merged_config(
            path=path,
            operator_path=operator_path,
            profile=profile,
            profiles_dir=profiles_dir,
            tier=tier,
            strict_operator=strict_operator,
            study=study,
            studies_dir=studies_dir,
        )
    )


def load_runtime_config(
    path: str | os.PathLike[str] = SHIPPED_CONFIG_PATH,
    operator_path: str | os.PathLike[str] = OPERATOR_CONFIG_PATH,
    *,
    profile: str | None = None,
    study: str | None = None,
    env: dict[str, str] | None = None,
    profiles_dir: str | os.PathLike[str] | None = None,
    studies_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load the runtime configuration used by the cycle and the pre-boot check.

    Resolves the module-selection profile and the deployment-tier layer, then
    returns the merged dict from :func:`load_kaine_config`.

    Resolution:

    * ``profile`` (e.g. ``--profile``) wins, then ``KAINE_PROFILE`` in ``env``.
    * When neither profile argument is set and ``config/profiles/first_configuration.toml``
      exists, the ``first_configuration`` profile is applied. This is the
      project's default entity configuration: a fresh install that boots the cycle
      with no explicit profile gets the first-configuration module set (the interoception, sequence,
      vision, audition, language, affect and sleep modules), STT off, and the self-initiated
      voice. The profile is the single definition of that set; the operator
      overlay carries host-local values and deliberate deviations only. The old
      name ``thesis_test`` still resolves to the first configuration with a
      warning.
    * The deployment tier is resolved by :func:`resolve_tier_name` (``KAINE_TIER``
      env, then ``[deployment].tier`` from the operator overlay) and layered on
      top of the module profile.
    * The study configuration is resolved from ``study``, then ``KAINE_STUDY``,
      and applied last.

    The tier only bounds backends and devices for the host hardware; it never
    replaces the selected module set. An explicit profile selection is honored
    or reported, never silently ignored.

    This path is strict about the operator overlay: an operator file that exists
    but cannot be read or parsed raises :class:`ProfileError` rather than being
    skipped.
    """
    resolved_profile = resolve_profile_name(profile, env=env)
    if resolved_profile is None:
        default_path = profile_path(DEFAULT_PROFILE, profiles_dir=profiles_dir)
        if default_path.exists():
            resolved_profile = DEFAULT_PROFILE
    resolved_tier = resolve_tier_name(
        env=env, operator_path=operator_path, profiles_dir=profiles_dir
    )
    resolved_study = resolve_study_name(study, env=env)
    return load_kaine_config(
        path,
        operator_path,
        profile=resolved_profile,
        tier=resolved_tier,
        profiles_dir=profiles_dir,
        strict_operator=True,
        study=resolved_study,
        studies_dir=studies_dir,
    )
