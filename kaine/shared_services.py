# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared-service detection for operator-declared external services.

A service marked ``[services.<name>].shared = true`` is owned by the operator's
other applications.  KAINE records its process-name patterns so that gates and
setup commands can avoid stopping, restarting or evicting it.
"""

from typing import Any

KNOWN_PROCESS_NAMES: dict[str, tuple[str, ...]] = {
    "model_server": ("llama-server",),
    "chatterbox": ("chatterbox",),
    "speaches": ("speaches",),
}


def shared_services(config: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """Return a mapping from shared service name to its process-name patterns."""
    services = config.get("services")
    if not isinstance(services, dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for name, table in services.items():
        if not isinstance(table, dict):
            continue
        if table.get("shared") is True:
            process_names = table.get("process_names")
            if (
                isinstance(process_names, list)
                and process_names
                and all(isinstance(p, str) and p for p in process_names)
            ):
                result[name] = tuple(process_names)
            else:
                result[name] = KNOWN_PROCESS_NAMES.get(name, (name,))
    return result


def is_shared(config: dict[str, Any], name: str) -> bool:
    """Return True if ``name`` is declared as a shared service."""
    return name in shared_services(config)


def match_shared_service(
    process_name: str, shared: dict[str, tuple[str, ...]]
) -> str | None:
    """Return the first shared service whose pattern occurs in ``process_name``."""
    lowered = process_name.lower()
    for service_name, patterns in shared.items():
        for pattern in patterns:
            if pattern.lower() in lowered:
                return service_name
    return None
