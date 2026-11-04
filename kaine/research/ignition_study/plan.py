# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Study plan representation, validation, and directory layout."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kaine import legacy_aliases
from kaine.boot import known_module_names
from kaine.defaults import DEFAULT_MIN_FREE_GB

PLAN_FILE = "study.json"
STEPS_FILE = "steps.jsonl"
LOCK_FILE = ".lock"

DEFAULT_VIEWING_BUDGET_SECONDS = 6 * 60 * 60  # programme length + 2 h
DEFAULT_DEVELOPMENT_BUDGET_SECONDS = 96 * 60 * 60  # 24 h minimum + 72 h headroom


def generate_progressive_plan(
    module_order: list[str],
    base_modules: list[str],
    broadcast_capacity: int | None = None,
) -> list[dict[str, Any]]:
    """Generate a progressive step sequence from a module addition order.

    Returns a list of step dicts:
      step 0: kind="seed",        modules=base_modules, modules_added=[]
      step k: kind="progressive", modules=base+order[:k], modules_added=[order[k-1]]

    Each step also carries ``step_index`` and ``start_bundle`` (None for step 0,
    placeholder for later steps — the runner fills the real path at execution time).
    """
    known = set(known_module_names())
    for m in base_modules + module_order:
        if m not in known:
            raise ValueError(f"Unknown module name: {m}")
    if set(base_modules) & set(module_order):
        raise ValueError("base_modules and module_order must be disjoint")

    steps: list[dict[str, Any]] = []
    current = list(base_modules)

    steps.append({
        "kind": "seed",
        "step_index": 0,
        "modules": list(current),
        "modules_added": [],
        "start_bundle": None,
        "broadcast_capacity": broadcast_capacity,
    })

    for i, module in enumerate(module_order, start=1):
        current.append(module)
        steps.append({
            "kind": "progressive",
            "step_index": i,
            "modules": list(current),
            "modules_added": [module],
            "start_bundle": None,
            "broadcast_capacity": broadcast_capacity,
        })

    return steps


def programme_sha256(manifest_path: Path | str) -> str:
    """SHA-256 of the programme manifest file."""
    return hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a study plan dictionary.

    Supports both progressive plans (``protocol = "progressive"``) and legacy
    branching plans (no ``protocol`` field or ``protocol = "branching"``).
    """
    plan = dict(plan)
    protocol = plan.get("protocol", "branching")

    if protocol == "progressive":
        return _validate_progressive_plan(plan)
    return _validate_branching_plan(plan)


def _validate_progressive_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a progressive development-run plan."""
    required = (
        "study_id",
        "repo_root",
        "base_modules",
        "order",
        "programme",
        "redis",
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
    validate_progressive_redis_db(redis["db"])

    bc = plan.get("broadcast_capacity")
    if bc is not None:
        if isinstance(bc, bool) or not isinstance(bc, int) or bc < 1:
            raise ValueError("broadcast_capacity must be a positive integer or absent")

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
    plan.setdefault("development_budget_seconds", DEFAULT_DEVELOPMENT_BUDGET_SECONDS)
    for key in ("viewing_budget_seconds", "development_budget_seconds"):
        if not isinstance(plan[key], (int, float)) or plan[key] <= 0:
            raise ValueError(f"{key} must be positive")

    plan.setdefault("min_free_gb", DEFAULT_MIN_FREE_GB)
    if (
        isinstance(plan["min_free_gb"], bool)
        or not isinstance(plan["min_free_gb"], (int, float))
        or plan["min_free_gb"] < 0
    ):
        raise ValueError("min_free_gb must be a number >= 0")

    vas = plan.get("voice_alignment_steps")
    if vas is not None:
        _validate_progressive_voice_alignment_steps(vas, len(order))
    else:
        plan["voice_alignment_steps"] = [{"step_index": len(order)}]

    plan.setdefault("collection_prefix", "devrun")

    plan["steps"] = generate_progressive_plan(
        order, base, broadcast_capacity=bc,
    )
    plan["collections"] = {"progressive": plan["collection_prefix"] + "_"}

    return plan


def _validate_progressive_voice_alignment_steps(
    steps: Any, order_len: int,
) -> None:
    seen: set[int] = set()
    for entry in steps:
        if not isinstance(entry, dict) or "step_index" not in entry:
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        idx = entry["step_index"]
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        if not 1 <= idx <= order_len:
            raise ValueError(
                f"voice_alignment step_index {idx} out of range 1..{order_len}"
            )
        if idx in seen:
            raise ValueError(f"Duplicate voice_alignment_steps entry: {entry!r}")
        seen.add(idx)


# ---- Legacy branching plan validation (kept for existing study data) ---- #

LINES = ["development", "branch", "repeat", "accumulate"]


def voice_alignment_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Default pre-registered voice-alignment steps for a branching plan."""
    return [{"line": "accumulate", "k": len(plan["order"])}]


def _validate_branching_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a legacy branching study plan."""
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
    plan.setdefault("development_budget_seconds", DEFAULT_DEVELOPMENT_BUDGET_SECONDS)
    for key in ("viewing_budget_seconds", "development_budget_seconds"):
        if not isinstance(plan[key], (int, float)) or plan[key] <= 0:
            raise ValueError(f"{key} must be positive")

    plan.setdefault("min_free_gb", DEFAULT_MIN_FREE_GB)
    if (
        isinstance(plan["min_free_gb"], bool)
        or not isinstance(plan["min_free_gb"], (int, float))
        or plan["min_free_gb"] < 0
    ):
        raise ValueError("min_free_gb must be a number >= 0")

    plan.setdefault("voice_alignment_steps", voice_alignment_steps(plan))
    _validate_voice_alignment_steps(plan["voice_alignment_steps"], len(order))

    return plan


def _validate_voice_alignment_steps(steps: Any, order_len: int) -> None:
    seen: set[tuple[str, int]] = set()
    for entry in steps:
        if not isinstance(entry, dict) or set(entry.keys()) != {"line", "k"}:
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        line = entry["line"]
        k = entry["k"]
        if line not in LINES:
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        if line == "development":
            raise ValueError(f"development never trains the voice: {entry!r}")
        if isinstance(k, bool) or not isinstance(k, int):
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        if line == "branch" and not 0 <= k <= order_len:
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        if line == "repeat" and k != 0:
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        if line == "accumulate" and not 1 <= k <= order_len:
            raise ValueError(f"Invalid voice_alignment_steps entry: {entry!r}")
        key = (line, k)
        if key in seen:
            raise ValueError(f"Duplicate voice_alignment_steps entry: {entry!r}")
        seen.add(key)


# ---- Directory layout ---- #

def step_dir_name(plan: dict[str, Any], step_index: int) -> str:
    """Directory name for a step in a progressive plan."""
    if step_index == 0:
        return "seed"
    return f"step_{step_index}"


def collection_prefix_for_step(plan: dict[str, Any], step_index: int) -> str:
    """Derive the collection prefix for a progressive step."""
    base = plan.get("collection_prefix", "devrun")
    return f"{base}_step{step_index}_"


def init_study(
    study_dir: Path | str,
    plan: dict[str, Any],
    *,
    exist_ok: bool = False,
) -> dict[str, Any]:
    """Create a new study directory and its step subdirectories."""
    study_dir = Path(study_dir).resolve()
    plan_path = study_dir / PLAN_FILE

    if plan_path.exists() and not exist_ok:
        raise FileExistsError(f"Study already exists at {study_dir}")

    study_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True))

    repo_root = Path(plan["repo_root"])
    protocol = plan.get("protocol", "branching")

    if protocol == "progressive":
        n_steps = len(plan["order"]) + 1  # seed + one per module
        for i in range(n_steps):
            ensure_step_dir(study_dir, step_dir_name(plan, i), repo_root)
    else:
        for line in LINES:
            if line == "branch":
                for k in range(len(plan["order"]) + 1):
                    ensure_line_dir(study_dir, line, k, repo_root)
            else:
                ensure_line_dir(study_dir, line, 0, repo_root)

    return plan


def ensure_step_dir(
    study_dir: Path | str,
    name: str,
    repo_root: Path | str,
) -> Path:
    """Create a progressive step directory with config symlinks."""
    study_dir = Path(study_dir).resolve()
    repo_root = Path(repo_root).resolve()

    step_path = study_dir / name
    step_path.mkdir(parents=True, exist_ok=True)

    cfg_dir = step_path / "config"
    cfg_dir.mkdir(exist_ok=True)

    repo_config = repo_root / "config" / "kaine.toml"
    repo_profiles = repo_root / "config" / "profiles"
    _link(cfg_dir / "kaine.toml", repo_config, is_dir=False)
    is_dir = repo_profiles.exists() and repo_profiles.is_dir()
    _link(cfg_dir / "profiles", repo_profiles, is_dir=is_dir)

    return step_path


def ensure_line_dir(
    study_dir: Path | str,
    line: str,
    k: int,
    repo_root: Path | str,
) -> Path:
    """Create a legacy branching step directory with config symlinks."""
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
    if link.is_symlink():
        if os.readlink(link) == str(target):
            return
        link.unlink()
    elif link.exists():
        raise ValueError(f"{link} exists and is not a symlink; refusing to replace it")
    os.symlink(target, link, target_is_directory=is_dir)


# ---- Redis validation ---- #

def validate_redis_base_url(base_url: str) -> None:
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


def validate_progressive_redis_db(db: Any, operator_dbs: set[int] | None = None) -> None:
    """Validate a progressive plan's single Redis db number."""
    if isinstance(db, bool) or not isinstance(db, int) or not 1 <= db <= 15:
        raise ValueError(
            "redis.db must be an integer in 1..15 (0 is the operator's bus)"
        )
    if operator_dbs and db in operator_dbs:
        raise ValueError(
            f"redis.db {db} is the operator's bus database"
        )


def validate_redis_dbs(dbs: Any, operator_dbs: set[int] | None = None) -> None:
    """Validate legacy branching per-line bus database numbers."""
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
    return legacy_aliases.map_study_plan(json.loads(path.read_text()))
