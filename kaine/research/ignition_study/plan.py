# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Study plan representation, validation, and directory layout."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from kaine.boot import known_module_names

PLAN_FILE = "study.json"
STEPS_FILE = "steps.jsonl"
LOCK_FILE = ".lock"

LINES = ["gestation", "main", "control"]

DEFAULT_VIEWING_BUDGET_SECONDS = 6 * 60 * 60  # programme length + 2 h
DEFAULT_GESTATION_BUDGET_SECONDS = 96 * 60 * 60  # 24 h minimum + 72 h headroom


def programme_sha256(manifest_path: Path | str) -> str:
    """SHA-256 of the programme manifest file."""
    return hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a study plan dictionary."""
    plan = dict(plan)

    required = (
        "study_id",
        "repo_root",
        "base_modules",
        "order",
        "programme",
        "redis",
        "collections",
        "viewings_per_line",
    )
    for field in required:
        if field not in plan:
            raise ValueError(f"Missing required plan field: {field}")

    if not isinstance(plan["study_id"], str) or not plan["study_id"]:
        raise ValueError("study_id must be a non-empty string")

    repo_root = Path(plan["repo_root"]).resolve()
    plan["repo_root"] = str(repo_root)

    known = set(known_module_names())
    base = list(plan["base_modules"])
    order = list(plan["order"])

    for module in base + order:
        if module not in known:
            raise ValueError(f"Unknown module name: {module}")

    if len(set(base)) != len(base):
        raise ValueError("Duplicate module in base_modules")
    if len(set(order)) != len(order):
        raise ValueError("Duplicate module in order")
    if set(base) & set(order):
        raise ValueError("base_modules and order must be disjoint")

    vpl = plan["viewings_per_line"]
    if not isinstance(vpl, int) or vpl < 1:
        raise ValueError("viewings_per_line must be a positive integer")

    redis = plan["redis"]
    if not isinstance(redis, dict) or "base_url" not in redis or "db" not in redis:
        raise ValueError("redis must contain base_url and db")
    dbs = redis["db"]
    if not isinstance(dbs, dict) or set(dbs.keys()) != set(LINES):
        raise ValueError(f"redis.db must contain exactly {LINES}")
    db_numbers = [dbs[line] for line in LINES]
    if any(not isinstance(n, int) for n in db_numbers):
        raise ValueError("redis.db values must be integers")
    if len(set(db_numbers)) != len(db_numbers):
        raise ValueError("redis.db numbers must be distinct")

    collections = plan["collections"]
    if not isinstance(collections, dict) or set(collections.keys()) != set(LINES):
        raise ValueError(f"collections must contain exactly {LINES}")
    prefixes = [collections[line] for line in LINES]
    if len(set(prefixes)) != len(prefixes):
        raise ValueError("collection prefixes must be distinct")

    programme = plan["programme"]
    manifest = Path(programme.get("manifest", ""))
    if not manifest.is_file():
        raise ValueError(f"Programme manifest not found: {manifest}")
    expected_sha = programme.get("sha256")
    if not isinstance(expected_sha, str) or not expected_sha:
        raise ValueError("programme.sha256 must be a non-empty string")
    actual_sha = programme_sha256(manifest)
    if actual_sha != expected_sha:
        raise ValueError(
            f"Programme sha256 mismatch: expected {expected_sha}, got {actual_sha}"
        )

    plan.setdefault("viewing_budget_seconds", DEFAULT_VIEWING_BUDGET_SECONDS)
    plan.setdefault("gestation_budget_seconds", DEFAULT_GESTATION_BUDGET_SECONDS)
    for key in ("viewing_budget_seconds", "gestation_budget_seconds"):
        if not isinstance(plan[key], (int, float)) or plan[key] <= 0:
            raise ValueError(f"{key} must be positive")

    return plan


def init_study(
    study_dir: Path | str,
    plan: dict[str, Any],
    *,
    exist_ok: bool = False,
) -> dict[str, Any]:
    """Create a new study directory and its line subdirectories.

    Each line directory receives ``config/kaine.toml`` and ``config/profiles``
    symlinks pointing into the repository configuration so the operator's base
    settings are shared but never edited inside the study.
    """
    study_dir = Path(study_dir).resolve()
    plan_path = study_dir / PLAN_FILE

    if plan_path.exists() and not exist_ok:
        raise FileExistsError(f"Study already exists at {study_dir}")

    study_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True))

    repo_root = Path(plan["repo_root"])
    repo_config = repo_root / "config" / "kaine.toml"
    repo_profiles = repo_root / "config" / "profiles"

    for line in LINES:
        line_dir = study_dir / line
        line_dir.mkdir(exist_ok=True)

        cfg_dir = line_dir / "config"
        cfg_dir.mkdir(exist_ok=True)

        config_link = cfg_dir / "kaine.toml"
        if config_link.exists() or config_link.is_symlink():
            config_link.unlink()
        os.symlink(repo_config, config_link)

        profiles_link = cfg_dir / "profiles"
        if profiles_link.exists() or profiles_link.is_symlink():
            profiles_link.unlink()
        is_dir = repo_profiles.exists() and repo_profiles.is_dir()
        os.symlink(repo_profiles, profiles_link, target_is_directory=is_dir)

    return plan


def load_plan(study_dir: Path | str) -> dict[str, Any]:
    """Load the plan from an existing study directory."""
    path = Path(study_dir) / PLAN_FILE
    if not path.exists():
        raise FileNotFoundError(f"No study plan found at {path}")
    return json.loads(path.read_text())
