# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Reaching the never-persisted instance from the host.

``kaine-redis-volatile`` has no host port: only containers on the compose
network reach it. Host-run tools (decommission, the preboot) therefore cannot
open a client, and must not mistake that for "there is no instance". This
module asks Docker about the compose container and runs ``redis-cli`` inside
it (``docker exec``), with the password read from the container's own
environment, never passed on a command line.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable, Optional

#: The compose service and container name of the never-persisted instance.
VOLATILE_CONTAINER = "kaine-redis-volatile"

#: ``absent``: no such container on this host (no compose install of it);
#: ``stopped``: the container exists and is not running (with no persistence
#: and a tmpfs ``/data`` it holds nothing); ``running``; ``unknown``: Docker is
#: installed but could not say.
ABSENT, STOPPED, RUNNING, UNKNOWN = "absent", "stopped", "running", "unknown"

Runner = Callable[..., subprocess.CompletedProcess]


def container_state(run: Optional[Runner] = None, docker: Optional[str] = None) -> str:
    """The state of the compose volatile container on this host."""
    docker = docker if docker is not None else shutil.which("docker")
    if not docker:
        return ABSENT
    run = run or subprocess.run
    try:
        result = run(
            [docker, "inspect", "-f", "{{.State.Running}}", VOLATILE_CONTAINER],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return UNKNOWN
    if result.returncode != 0:
        err = (result.stderr or "").lower()
        if "no such object" in err or "no such container" in err:
            return ABSENT
        return UNKNOWN
    return RUNNING if result.stdout.strip() == "true" else STOPPED


def redis_cli(
    *args: str, run: Optional[Runner] = None, docker: Optional[str] = None
) -> tuple[bool, str]:
    """Run ``redis-cli <args>`` inside the volatile container; ``(ok, output)``.
    The password comes from the container's environment (``REDISCLI_AUTH``)."""
    docker = docker if docker is not None else shutil.which("docker")
    if not docker:
        return False, ""
    run = run or subprocess.run
    quoted = " ".join("'" + a.replace("'", "'\\''") + "'" for a in args)
    try:
        result = run(
            [
                docker, "exec", VOLATILE_CONTAINER, "sh", "-c",
                'REDISCLI_AUTH="$KAINE_REDIS_VOLATILE_PASSWORD" redis-cli --no-auth-warning ' + quoted,
            ],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return False, ""
    return result.returncode == 0, (result.stdout or "").strip()
