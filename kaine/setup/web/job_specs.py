# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Job definitions for the browser setup server.

These specs are built from the saved operator configuration at the moment a job
is started.  The runnable commands (Redis/Qdrant bootstrap scripts and the model
server bootstrap) come from fixed constants in kaine.setup.dependencies; they are
never constructed from user input.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

from kaine import net
from kaine.setup.dependencies import DEPENDENCIES
from kaine.setup.web.jobs import JobSpec
from kaine.setup.wizard import implied_extras


def _module_enabled(modules: dict[str, Any], name: str) -> bool:
    return bool((modules or {}).get(name))


def _dependency_needed(spec, modules: dict[str, Any]) -> bool:
    if not spec.modules:
        return True
    return any(_module_enabled(modules, m) for m in spec.modules)


def build_job_specs(
    config: dict[str, Any],
    shipped: dict[str, Any],
    *,
    repo_root: Path,
    shipped_config_path: Path,
    operator_path: Path,
) -> list[JobSpec]:
    """Return the job specs offered for this saved operator configuration."""
    specs: list[JobSpec] = []
    modules = config.get("modules") or {}

    extras = implied_extras(modules, shipped)
    if extras:
        argv = (
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            f".[{','.join(extras)}]",
        )
        specs.append(
            JobSpec(
                name="extras",
                title="Install optional extras",
                argv=argv,
                details=" ".join(argv),
            )
        )

    if _module_enabled(modules, "lingua"):
        argv = (
            sys.executable,
            "-m",
            "kaine.setup.organ",
            "download",
            "--yes",
            "--config",
            str(shipped_config_path),
            "--operator-config",
            str(operator_path),
        )
        specs.append(
            JobSpec(
                name="organ_download",
                title="Download the language organ",
                argv=argv,
                details=" ".join(argv),
            )
        )

    for dep in DEPENDENCIES:
        if dep.kind != "command":
            continue
        if not _dependency_needed(dep, modules):
            continue
        argv = tuple(shlex.split(dep.command))
        specs.append(
            JobSpec(
                name=dep.name,
                title=dep.role,
                argv=argv,
                details=dep.command,
            )
        )

    try:
        from kaine.nexus.config import NexusConfigError, load_nexus_config

        nexus_cfg = load_nexus_config(repo_root / "config" / "kaine.toml")
        nexus_port = nexus_cfg.port
    except NexusConfigError:
        # Nexus configuration is unsafe/invalid; do not offer the start job.
        return specs

    specs.append(
        JobSpec(
            name="nexus",
            title="Start Nexus",
            argv=(sys.executable, "-m", "kaine.nexus"),
            detach=True,
            ready_probe=lambda port=nexus_port: net.port_listening(port),
            details=f"{sys.executable} -m kaine.nexus (port {nexus_port})",
        )
    )

    return specs
