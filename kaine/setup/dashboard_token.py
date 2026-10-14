# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Dashboard operator token helpers for setup."""
from __future__ import annotations

import os
import secrets
import tomllib
from pathlib import Path
from typing import Any, Callable

from kaine import legacy_aliases, secrets_file

# Where the dashboard reads its operator token (kaine.dashboard.config.load_dashboard_config).
DEFAULT_SECRETS_PATH = Path("config/secrets.toml")
# The dashboard rejects shorter operator tokens (kaine.dashboard.config.load_dashboard_config).
_MIN_DASHBOARD_TOKEN_LEN = 32


def _table_names(secrets_path: Path) -> set[str]:
    """Return the set of top-level table names in *secrets_path*.

    A missing or unreadable file is treated as empty.
    """
    try:
        with open(secrets_path, "rb") as fh:
            data = tomllib.load(fh)
    except (FileNotFoundError, OSError):
        return set()
    return set(data.keys())


def ensure_dashboard_token(
    secrets_path: Path,
    *,
    out: Callable[[str], Any],
    env: dict[str, str] | None = None,
) -> str:
    """Ensure a dashboard operator sign-in token exists.

    Without a token, the dashboard rejects every sign-in with 503. The environment
    variable ``KAINE_DASHBOARD_TOKEN`` takes precedence; otherwise the token is read
    from or written to ``[dashboard] operator_token`` in the secrets file.
    """
    env = os.environ if env is None else env
    out("\n")

    try:
        env_token = (legacy_aliases.getenv("KAINE_DASHBOARD_TOKEN", "", environ=env) or "").strip()
    except legacy_aliases.LegacyNameConflict as exc:
        out(f"Dashboard sign-in token: {exc}. Nothing written.\n")
        return "conflict"
    if env_token:
        if len(env_token) < _MIN_DASHBOARD_TOKEN_LEN:
            out(
                "Dashboard sign-in token: KAINE_DASHBOARD_TOKEN is shorter than "
                f"{_MIN_DASHBOARD_TOKEN_LEN} characters, so the dashboard will refuse it. "
                "Unset it or replace it with a longer one.\n"
            )
            return "too_short"
        out(
            "Dashboard sign-in token: provided by KAINE_DASHBOARD_TOKEN; nothing written.\n"
        )
        return "env"

    existing_table: str | None = None
    existing_value: Any = None
    try:
        for form in legacy_aliases.name_forms("dashboard"):
            try:
                value = secrets_file.read_toml_field(
                    secrets_path, form, "operator_token"
                )
            except KeyError:
                continue
            if value is not None:
                existing_table = form
                existing_value = value
                break
    except tomllib.TOMLDecodeError:
        out(
            f"{secrets_path} is not valid TOML; the Dashboard sign-in token was NOT "
            "generated. Fix the file, then re-run setup.\n"
        )
        return "malformed"
    except OSError as exc:
        out(
            f"{secrets_path} could not be read ({exc}); the Dashboard sign-in token "
            "was NOT generated.\n"
        )
        return "error"

    if existing_table is not None and isinstance(existing_value, str) and existing_value.strip():
        # Never overwrite an operator's token, but say so when the dashboard would
        # refuse it rather than reporting it as fine.
        token_str = existing_value.strip()
        if len(token_str) < _MIN_DASHBOARD_TOKEN_LEN:
            out(
                f"Dashboard sign-in token in {secrets_path} [{existing_table}] operator_token is "
                f"shorter than {_MIN_DASHBOARD_TOKEN_LEN} characters, so the dashboard will "
                "refuse it. Replace it, or delete that line and re-run setup to "
                "generate one.\n"
            )
            return "too_short"
        out(
            f"Dashboard sign-in token: already set in {secrets_path} [{existing_table}] "
            "operator_token; kept.\n"
        )
        if existing_table != "dashboard":
            out(
                "The old table name still works; you may rename it to [dashboard].\n"
            )
        return "kept"

    # If an old-named table exists without a usable token, do not write a new
    # [dashboard] table next to it: the dashboard refuses files with both names.
    tables = _table_names(secrets_path)
    for form in legacy_aliases.name_forms("dashboard"):
        if form != "dashboard" and form in tables:
            out(
                f"{secrets_path} has an old [{form}] table without an operator_token; "
                "add operator_token there or rename the table to [dashboard], then "
                "re-run setup. Nothing written.\n"
            )
            return "conflict"

    token = secrets.token_urlsafe(32)
    try:
        secrets_file.upsert_toml_field(
            secrets_path, "dashboard", "operator_token", token
        )
    except (OSError, ValueError) as exc:
        out(
            f"Could not save Dashboard sign-in token to {secrets_path} ({exc}).\n"
        )
        return "error"

    out(
        f"Dashboard sign-in token: generated and saved to {secrets_path} under "
        "[dashboard] operator_token (mode 600). It is not shown here; open that file "
        "when the dashboard asks for it.\n"
    )
    return "generated"
