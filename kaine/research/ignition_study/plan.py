# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Study plan representation, validation, and directory layout."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kaine.boot import known_module_names

PLAN_FILE = "study.json"
STEPS_FILE = "steps.jsonl"
LOCK_FILE = ".lock"

LINES = ["gestation", "branch", "repeat", "accumulate"]

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

    redis = plan["redis"]
    if not isinstance(redis, dict) or "base_url" not in redis or "db" not in redis:
        raise ValueError("redis must contain base_url and db")

    validate_redis_base_url(redis["base_url"])

    validate_redis_dbs(redis["db"])

    collections = plan["collections"]
    if not isinstance(collections, dict) or set(collections.keys()) != set(LINES):
        raise ValueError(f"collections must contain exactly {LINES}")
    prefixes = [collections[line] for line in LINES]
    if any(not isinstance(p, str) or not p for p in prefixes):
        raise ValueError("collection prefixes must be non-empty strings")
    if len(set(prefixes)) != len(prefixes):
        raise ValueError("collection prefixes must be distinct")
    # A branch step's prefix is the branch prefix plus "<k>_", so a prefix that
    # starts another line's prefix could name that line's collections.
    for a in prefixes:
        for b in prefixes:
            if a != b and b.startswith(a):
                raise ValueError(
                    "collection prefixes must not start with one another"
                )

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

    Every step working directory (``gestation``, ``branch/<k>`` for k = 0..K,
    ``repeat`` and ``accumulate``) receives ``config/kaine.toml`` and
    ``config/profiles`` symlinks pointing into the repository configuration so
    the operator's base settings are shared but never edited inside the study.
    """
    study_dir = Path(study_dir).resolve()
    plan_path = study_dir / PLAN_FILE

    if plan_path.exists() and not exist_ok:
        raise FileExistsError(f"Study already exists at {study_dir}")

    study_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True))

    repo_root = Path(plan["repo_root"])
    for line in LINES:
        if line == "branch":
            for k in range(len(plan["order"]) + 1):
                ensure_line_dir(study_dir, line, k, repo_root)
        else:
            ensure_line_dir(study_dir, line, 0, repo_root)

    return plan


def ensure_line_dir(
    study_dir: Path | str,
    line: str,
    k: int,
    repo_root: Path | str,
) -> Path:
    """Create a step working directory and its config symlinks on demand.

    ``branch`` steps live under ``<study>/branch/<k>``; all other lines live
    under ``<study>/<line>``.  The directory receives ``config/kaine.toml``
    and ``config/profiles`` symlinks into the repository configuration.
    """
    study_dir = Path(study_dir).resolve()
    repo_root = Path(repo_root).resolve()

    if line == "branch":
        line_dir = study_dir / "branch" / str(k)
    else:
        line_dir = study_dir / line

    line_dir.mkdir(parents=True, exist_ok=True)

    cfg_dir = line_dir / "config"
    cfg_dir.mkdir(exist_ok=True)

    repo_config = repo_root / "config" / "kaine.toml"
    repo_profiles = repo_root / "config" / "profiles"
    _link(cfg_dir / "kaine.toml", repo_config, is_dir=False)
    is_dir = repo_profiles.exists() and repo_profiles.is_dir()
    _link(cfg_dir / "profiles", repo_profiles, is_dir=is_dir)

    return line_dir


def _link(link: Path, target: Path, *, is_dir: bool) -> None:
    """Point ``link`` at ``target``.  Only a symlink is ever replaced; a real
    file or directory in its place is refused, never deleted."""
    if link.is_symlink():
        if os.readlink(link) == str(target):
            return
        link.unlink()
    elif link.exists():
        raise ValueError(f"{link} exists and is not a symlink; refusing to replace it")
    os.symlink(target, link, target_is_directory=is_dir)


def validate_redis_base_url(base_url: str) -> None:
    """Validate that a Redis base URL contains no credentials, path, or bad scheme.

    Raises:
        ValueError: If the URL is malformed. The message never includes the URL text.
    """
    parsed = urlsplit(base_url)
    if parsed.username or parsed.password:
        raise ValueError(
            "redis.base_url must not contain credentials; the password comes from "
            "KAINE_REDIS_PASSWORD or config/secrets.toml"
        )
    if parsed.scheme not in ("redis", "rediss"):
        raise ValueError("redis.base_url scheme must be redis or rediss")
    if parsed.path not in ("", "/"):
        raise ValueError("redis.base_url path must be empty or '/'")


def validate_redis_dbs(dbs: Any, operator_dbs: set[int] | None = None) -> None:
    """Validate the study's per-line bus database numbers.

    Each line has its own database, an integer in 1..15; database 0 is the
    operator's live bus and is never the study's.  ``operator_dbs`` names any
    further database numbers the operator's configuration uses; the study may
    not share one, because the runner flushes every study database.
    """
    if not isinstance(dbs, dict) or set(dbs.keys()) != set(LINES):
        raise ValueError(f"redis.db must contain exactly {LINES}")
    numbers = [dbs[line] for line in LINES]
    if any(
        isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 15
        for n in numbers
    ):
        raise ValueError(
            "redis.db values must be integers in 1..15 (0 is the operator's bus)"
        )
    if len(set(numbers)) != len(numbers):
        raise ValueError("redis.db numbers must be distinct")
    shared = set(numbers) & set(operator_dbs or ())
    if shared:
        raise ValueError(
            f"redis.db numbers {sorted(shared)} are the operator's bus database"
        )


def load_plan(study_dir: Path | str) -> dict[str, Any]:
    """Load the plan from an existing study directory."""
    path = Path(study_dir) / PLAN_FILE
    if not path.exists():
        raise FileNotFoundError(f"No study plan found at {path}")
    return json.loads(path.read_text())
