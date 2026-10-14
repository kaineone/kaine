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


def ensure_dashboard_token(
    secrets_path: Path,
    *,
    out: Callable[[str], Any],
    env: dict[str, str] | None = None,
) -> str:
    """Ensure a dashboard operator sign-in token exists.

    Without a token, the dashboard rejects every sign-in with 503. The environment
    variable ``KAINE_NEXUS_TOKEN`` takes precedence; otherwise the token is read
    from or written to ``[dashboard] operator_token`` in the secrets file.
    """
    env = os.environ if env is None else env
    out("\n")

    try:
        env_token = (legacy_aliases.getenv("KAINE_NEXUS_TOKEN", "", environ=env) or "").strip()
    except legacy_aliases.LegacyNameConflict as exc:
        out(f"Dashboard sign-in token: {exc}. Nothing written.\n")
        return "conflict"
    if env_token:
        if len(env_token) < _MIN_DASHBOARD_TOKEN_LEN:
            out(
                "Nexus sign-in token: KAINE_NEXUS_TOKEN is shorter than "
                f"{_MIN_DASHBOARD_TOKEN_LEN} characters, so Nexus will refuse it. "
                "Unset it or replace it with a longer one.\n"
            )
            return "too_short"
        out(
            "Nexus sign-in token: provided by KAINE_NEXUS_TOKEN; nothing written.\n"
        )
        return "env"

    try:
        existing = secrets_file.read_toml_field(
            secrets_path, "dashboard", "operator_token"
        )
    except tomllib.TOMLDecodeError:
        out(
            f"{secrets_path} is not valid TOML; the Nexus sign-in token was NOT "
            "generated. Fix the file, then re-run setup.\n"
        )
        return "malformed"
    except OSError as exc:
        out(
            f"{secrets_path} could not be read ({exc}); the Nexus sign-in token "
            "was NOT generated.\n"
        )
        return "error"

    if isinstance(existing, str) and existing.strip():
        # Never overwrite an operator's token, but say so when the dashboard would
        # refuse it rather than reporting it as fine.
        if len(existing.strip()) < _MIN_DASHBOARD_TOKEN_LEN:
            out(
                f"Nexus sign-in token in {secrets_path} [dashboard] operator_token is "
                f"shorter than {_MIN_DASHBOARD_TOKEN_LEN} characters, so Nexus will "
                "refuse it. Replace it, or delete that line and re-run setup to "
                "generate one.\n"
            )
            return "too_short"
        out(
            f"Nexus sign-in token: already set in {secrets_path} [dashboard] "
            "operator_token; kept.\n"
        )
        return "kept"

    token = secrets.token_urlsafe(32)
    try:
        secrets_file.upsert_toml_field(
            secrets_path, "dashboard", "operator_token", token
        )
    except (OSError, ValueError) as exc:
        out(
            f"Could not save Nexus sign-in token to {secrets_path} ({exc}).\n"
        )
        return "error"

    out(
        f"Nexus sign-in token: generated and saved to {secrets_path} under "
        "[dashboard] operator_token (mode 600). It is not shown here; open that file "
        "when Nexus asks for it.\n"
    )
    return "generated"
