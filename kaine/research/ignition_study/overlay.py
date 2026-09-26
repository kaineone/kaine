# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-line, per-step operator overlay generation."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import kaine.boot
from kaine.config import deep_merge


def build_overlay(
    plan: dict[str, Any],
    line: str,
    step_kind: str,
    viewing_index: int,
    repo_root: Path,
    base_config_path: Path,
    operator_config_path: Path,
) -> tuple[dict[str, Any], set[str], str]:
    """Return ``(overlay_dict, enabled_modules, models_dir)`` for one step.

    The overlay is the deep merge of the operator's own
    ``config/kaine.operator.toml`` (when present) with the study-required
    settings for the line and step.  Study settings always win so every other
    known module is disabled and every isolation key is line-specific.
    """
    base_config = _load_toml(base_config_path)
    operator_config = (
        _load_toml(operator_config_path) if operator_config_path.exists() else {}
    )

    all_modules = set(kaine.boot.known_module_names())
    enabled = set(plan["base_modules"])
    if step_kind == "viewing" and line == "main":
        enabled.update(plan["order"][:viewing_index])

    modules = {name: (name in enabled) for name in all_modules}

    perception: dict[str, Any] = {
        "mode": "womb" if step_kind == "gestation" else "playlist",
    }
    if step_kind == "viewing":
        perception["playlist_manifest"] = plan["programme"]["manifest"]

    # The operator's own value wins over the shipped one, as it does at boot.
    encoder_dir = _absolute_encoder_dir(repo_root, deep_merge(base_config, operator_config))
    models_dir = str((repo_root / "state" / "models").resolve())

    study_overlay: dict[str, Any] = {
        "modules": modules,
        "perception_feed": perception,
        "developmental_stage": {"enabled": True},
        "mnemos": {"collection_prefix": plan["collections"][line]},
        "empatheia": {"collection": plan["collections"][line]},
        "ignition_log": {"enabled": True},
        "research_event_log": {"enabled": True},
        "preservation": {
            "divergence_monitor": {"enabled": True},
            "welfare_response": {"enabled": True},
        },
        "phantasia": {"training_enabled": True, "persist_weights": True},
        "topos": {"encoder_local_dir": encoder_dir},
    }

    overlay = deep_merge(operator_config, study_overlay)
    return overlay, enabled, models_dir


def _load_toml(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _absolute_encoder_dir(repo_root: Path, base_config: dict[str, Any]) -> str:
    """Resolve ``[topos].encoder_local_dir`` absolutely against the repository."""
    topos = base_config.get("topos", {})
    value = topos.get("encoder_local_dir")
    if not value:
        target = repo_root / "state" / "models"
    else:
        p = Path(value)
        target = p if p.is_absolute() else repo_root / p
    return str(target.resolve())
