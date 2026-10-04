# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Storage-root resolution for KAINE's growing data paths.

Every configured growing-data path can be resolved under an operator-chosen
``[storage].data_root`` (or the ``KAINE_DATA_ROOT`` environment variable).
Relative paths resolve under that root; absolute paths keep their value.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Mapping

from kaine.defaults import DEFAULT_MIN_FREE_GB  # noqa: F401

DATA_ROOT_ENV = "KAINE_DATA_ROOT"

GROWING_DATA_KEYS: tuple[tuple[str, ...], ...] = (
    ("lifecycle", "snapshots_path"),
    ("lifecycle", "adapter_merge", "output_dir"),
    ("preservation", "incident_path"),
    ("preservation", "divergence_monitor", "state_root"),
    ("preservation", "divergence_monitor", "eval_root"),
    ("preservation", "divergence_monitor", "out_root"),
    ("preservation", "welfare_response", "state_root"),
    ("preservation", "welfare_response", "eval_root"),
    ("preservation", "welfare_response", "out_root"),
    ("spot", "incident_log", "path"),
    ("eidolon", "persistence_path"),
    ("praxis", "sandbox_path"),
    ("praxis", "audit_log_path"),
    ("praxis", "notification_fallback_log"),
    ("lingua", "intent_log_path"),
    ("hypnos", "voice_alignment", "intent_log_path"),
    ("hypnos", "voice_alignment", "adapter_output_dir"),
    ("hypnos", "voice_alignment", "trainer_workdir"),
    ("phantasia", "checkpoint_path"),
    ("vox", "sink_path"),
    ("research_event_log", "log_dir"),
    ("research_event_log", "raw_archive", "archive_dir"),
    ("research_event_log", "external_utterances", "log_dir"),
    ("research_event_log", "nexus_record", "log_dir"),
    ("evaluation", "paths", "trajectory_dir"),
    ("evaluation", "paths", "evaluation_logs"),
    ("evaluation", "individuation", "output_dir"),
    ("ignition_log", "directory"),
    ("topos", "encoder_local_dir"),
    ("audition", "sherpa_model_dir"),
    ("vox", "sherpa_model_dir"),
    ("preboot", "state_root"),
    ("preboot", "data_root"),
    ("preboot", "extra_disk_paths"),
)


def configured_data_root(
    config: dict[str, Any], env: Mapping[str, str] | None = None
) -> Path | None:
    """Return the chosen data root, or ``None`` if none is configured.

    Priority:
    1. A non-empty ``KAINE_DATA_ROOT`` environment value.
    2. ``config["storage"]["data_root"]`` when it is a non-empty string.
    3. ``None``.
    """
    if env is None:
        env = os.environ

    env_value = env.get(DATA_ROOT_ENV)
    if env_value is not None and env_value.strip():
        return Path(env_value).expanduser().resolve()

    storage = config.get("storage")
    if isinstance(storage, dict):
        value = storage.get("data_root")
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser().resolve()

    return None


def resolve_under(root: Path | None, value: str) -> str:
    """Resolve *value* under *root* when appropriate.

    Returns *value* unchanged when *root* is ``None``, *value* is empty, or
    *value* expands to an absolute path. Otherwise returns ``root / value``.
    """
    if root is None or value == "":
        return value
    if Path(value).expanduser().is_absolute():
        return value
    return str(root / value)


def normalize_storage_paths(
    config: dict[str, Any], env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Rewrite all configured growing-data paths under the chosen data root.

    If no data root is configured, returns the original *config* object
    unchanged. Otherwise returns a deep copy in which present growing-data
    strings (and lists of strings) are resolved under the root, and
    ``storage.data_root`` is set to the absolute root path.
    """
    root = configured_data_root(config, env)
    if root is None:
        return config

    merged = copy.deepcopy(config)

    for key_path in GROWING_DATA_KEYS:
        parent: Any = merged
        for key in key_path[:-1]:
            child = parent.get(key)
            if not isinstance(child, dict):
                parent = None
                break
            parent = child
        if parent is None:
            continue

        leaf = key_path[-1]
        if leaf not in parent:
            continue
        value = parent[leaf]

        if isinstance(value, str):
            parent[leaf] = resolve_under(root, value)
        elif isinstance(value, list):
            parent[leaf] = [
                resolve_under(root, item) if isinstance(item, str) else item
                for item in value
            ]

    raw_env = (env if env is not None else os.environ).get(DATA_ROOT_ENV, "")
    if raw_env.strip() and "storage" not in merged:
        merged["storage"] = {}

    storage = merged.get("storage")
    if isinstance(storage, dict):
        storage["data_root"] = str(root)

    return merged


def storage_min_free_gb(config: dict[str, Any]) -> float:
    """Return the configured minimum free gigabytes for the data root."""
    storage = config.get("storage")
    if isinstance(storage, dict):
        value = storage.get("min_free_gb")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return DEFAULT_MIN_FREE_GB


_PROCESS_ROOT: Path | None = None


def set_data_root(root: Path | None) -> None:
    """Install *root* as the process-wide data root."""
    global _PROCESS_ROOT
    _PROCESS_ROOT = root.expanduser().resolve() if root is not None else root


def data_root() -> Path | None:
    """Return the currently installed process-wide data root, if any."""
    return _PROCESS_ROOT


def install_data_root(
    config: dict[str, Any], env: Mapping[str, str] | None = None
) -> Path | None:
    """Install the configured data root for this process.

    Call once at a process entry point after loading the config and before
    any file is read or written; never from a config loader.
    """
    root = configured_data_root(config, env)
    set_data_root(root)
    return root


def resolve(path: str | os.PathLike[str]) -> Path:
    """Resolve *path* under the installed process-wide data root.

    Relative paths resolve under the installed root; absolute paths are
    unchanged. When no root is installed the path is returned as given (a
    relative path therefore stays relative, preserving previous behaviour).
    """
    return Path(resolve_under(_PROCESS_ROOT, os.fspath(path)))
