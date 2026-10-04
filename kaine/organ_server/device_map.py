# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Device-map helpers shared by the wizard, compose env writer, and pre-boot checks."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

ROLES = ("organ", "vision")
ENV_OF_ROLE = {"organ": "KAINE_ORGAN_GPU", "vision": "KAINE_VISION_GPU"}
KEY_OF_ROLE = {
    "organ": "hypnos.voice_alignment.training_device",
    "vision": "topos.device",
}


def device_map(config: dict[str, Any]) -> dict[str, str] | None:
    """Return the role -> device map from ``[hardware.devices]`` if it exists.

    Unknown roles are dropped.  Returns ``None`` when the section is missing or
    not a table.
    """
    devices = config.get("hardware", {}).get("devices")
    if not isinstance(devices, dict):
        return None
    return {role: device for role, device in devices.items() if role in ROLES}


def cuda_index(device: str) -> int | None:
    """Return the numeric CUDA index for ``"cuda:N"``, else ``None``."""
    if not isinstance(device, str):
        return None
    match = re.fullmatch(r"cuda:(\d+)", device)
    if not match:
        return None
    return int(match.group(1))


def compose_gpu_env(devmap: dict[str, str]) -> dict[str, str]:
    """Map CUDA roles to the compose GPU variables used by ``compose/kaine.yml``."""
    result: dict[str, str] = {}
    for role, device in devmap.items():
        n = cuda_index(device)
        if n is None:
            continue
        env_var = ENV_OF_ROLE.get(role)
        if env_var:
            result[env_var] = str(n)
    return result


def native_organ_env(devmap: dict[str, str]) -> dict[str, str]:
    """Return ``CUDA_VISIBLE_DEVICES`` for the native organ launcher."""
    if not devmap:
        return {}
    n = cuda_index(devmap.get("organ", ""))
    if n is None:
        return {}
    return {"CUDA_VISIBLE_DEVICES": str(n)}


def _line_ending(line: str) -> str:
    """Preserve the trailing ``\\n`` or ``\\r\\n`` of a line."""
    stripped = line.rstrip("\r\n")
    return line[len(stripped) :]


def read_env_values(
    path: Path, keys: set[str] | tuple[str, ...] | list[str]
) -> dict[str, str]:
    """Read the requested ``KEY=value`` lines from ``path``.

    Comments and blank lines are ignored.  Values are stripped of surrounding
    quotes.  Returns an empty dict when the file is missing.
    """
    keys = set(keys)
    result: dict[str, str] = {}
    if not path.exists():
        return result
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key not in keys:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value
    return result


def write_env_values(path: Path, values: dict[str, str]) -> None:
    """Update ``values`` in ``path`` while preserving every other byte.

    The first ``KEY=value`` occurrence for each key is rewritten in place,
    missing keys are appended with a trailing newline, and the original file
    mode is kept.
    """
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        text = path.read_text(encoding="utf-8")
    else:
        mode = 0o600
        text = ""

    lines = text.splitlines(keepends=True)
    found: set[str] = set()
    for key, value in values.items():
        pattern = re.compile(rf"^{re.escape(key)}\s*=\s*")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}{_line_ending(line)}"
                found.add(key)
                break

    if lines and not lines[-1].endswith("\n"):
        lines.append("\n")
    for key, value in values.items():
        if key not in found:
            lines.append(f"{key}={value}\n")

    tmp_fd, tmp_path_str = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="") as f:
            f.write("".join(lines))
        os.chmod(tmp_path_str, mode)
        os.replace(tmp_path_str, path)
    except Exception:
        try:
            os.unlink(tmp_path_str)
        except OSError:
            # Best-effort cleanup of the temporary file; the original error
            # is re-raised below.
            pass
        raise


def _dotted_get(config: dict[str, Any], key: str) -> Any:
    """Return the value at a dotted path, or ``None`` if any part is absent."""
    cur: Any = config
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def check_agreement(config: dict[str, Any], *, env_path: Path) -> tuple[str, str]:
    """Check that compose and the cycle's device keys agree with the device map.

    Returns ``("skip"|"pass"|"fail", detail)``.
    """
    devmap = device_map(config)
    if devmap is None:
        return ("skip", "no [hardware.devices] device map")

    problems: list[str] = []
    env_values = (
        read_env_values(env_path, ENV_OF_ROLE.values()) if env_path.exists() else {}
    )

    for role, device in devmap.items():
        n = cuda_index(device)
        if n is None:
            continue
        var = ENV_OF_ROLE.get(role)
        if var and var in env_values and env_values[var] != str(n):
            problems.append(
                f"{var}={env_values[var]} in {env_path.name} "
                f"but [hardware.devices].{role} = {device}"
            )

    for role, device in devmap.items():
        key = KEY_OF_ROLE.get(role)
        if not key:
            continue
        value = _dotted_get(config, key)
        if value is not None and value != device:
            problems.append(
                f"{key} = {value} but [hardware.devices].{role} = {device}"
            )

    if problems:
        return ("fail", "; ".join(problems))
    return ("pass", "device map agrees with compose and the cycle's device keys")
