# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Praxis factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.errors import _require_keys
from kaine.bus.client import AsyncBus
from kaine.modules.base import BaseModule


def make_praxis(
    bus: AsyncBus, section: dict[str, Any], *, intent_secret: Optional[bytes] = None
) -> BaseModule:
    from kaine.modules.praxis.module import Praxis
    from kaine.modules.praxis.whitelist import CommandWhitelist, WhitelistEntry

    allowed = {
        "sandbox_path",
        "audit_log_path",
        "notification_command",
        "notification_fallback_log",
        "max_file_bytes",
        "baseline_salience",
        "alert_salience",
        "enabled_effectors",  # operator effector-enablement whitelist (empty = none)
        "shell_whitelist",  # nested table: {<command_name>: {arg_patterns, timeout_s, ...}}
    }
    _require_keys(section, allowed)
    whitelist_table = section.get("shell_whitelist") or {}
    entries: list[WhitelistEntry] = []
    for command_name, entry_cfg in whitelist_table.items():
        entries.append(
            WhitelistEntry(
                command=command_name,
                arg_patterns=tuple(entry_cfg.get("arg_patterns", ())),
                timeout_s=float(entry_cfg.get("timeout_s", 5.0)),
                cwd=entry_cfg.get("cwd"),
                description=entry_cfg.get("description", ""),
            )
        )
    # Effector-enablement whitelist: empty by default → no effector runs until the
    # operator names it here. The gate is enforced in Praxis.act for every effector.
    enabled_effectors = list(section.get("enabled_effectors", ()) or ())
    kwargs: dict[str, Any] = {
        "whitelist": CommandWhitelist(entries),
        "enabled_effectors": enabled_effectors,
    }
    # Per-boot act-intent provenance secret (Mechanism B). The cycle composition
    # root generates it and injects the SAME bytes into Volition (to sign) and
    # here (to verify). None only in headless/test construction, where the
    # fail-closed default in Praxis then refuses every act intent.
    if intent_secret is not None:
        kwargs["intent_secret"] = intent_secret
    for k in (
        "sandbox_path",
        "audit_log_path",
        "notification_command",
        "notification_fallback_log",
        "max_file_bytes",
        "baseline_salience",
        "alert_salience",
    ):
        if k in section:
            kwargs[k] = section[k]
    return Praxis(bus, **kwargs)
