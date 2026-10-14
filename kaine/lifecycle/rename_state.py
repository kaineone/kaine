# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Migrate a KAINE state tree from old module names to new functional names.

Safe to interrupt and re-run; ``--revert`` restores the original tree.
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from kaine import legacy_names
from kaine.state_io import write_json_atomic

log = logging.getLogger(__name__)

def _mountinfo_points() -> set[str]:
    """Mount points of this process's mount namespace, from /proc/self/mountinfo.

    Field 5 of each line is the mount point, with spaces, tabs, newlines and
    backslashes written as octal escapes.
    """
    points: set[str] = set()
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as fh:
            for line in fh:
                fields = line.split(" ")
                if len(fields) > 4:
                    raw = fields[4]
                    for code, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
                        raw = raw.replace(code, char)
                    points.add(raw)
    except OSError:
        # No mount table (not Linux, or /proc unavailable): os.path.ismount alone
        # decides, which is the caller's other check.
        log.debug("rename_state: /proc/self/mountinfo unreadable", exc_info=True)
    return points


def _detect_mount(path) -> bool:
    """Whether ``path`` is a mount point.

    ``os.path.ismount`` misses a bind mount from the same filesystem, which is
    how container runtimes mount named volumes, so the mount table is read too.
    """
    path = Path(path)
    try:
        if os.path.ismount(path):
            return True
        resolved = str(path.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return resolved in _mountinfo_points()


# The mount check every rule calls; tests monkeypatch it to simulate mount points.
_is_mount = _detect_mount

MANIFEST_DIR = ".rename_state"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1

STAGE_PATH = "lifecycle/stage.json"

SQLITE_MAGIC = b"SQLite format 3\x00"


class RenameStateError(RuntimeError):
    """Raised when a rename cannot proceed safely."""


@dataclass(frozen=True)
class RenameResult:
    status: str
    steps: tuple[dict, ...]


class QdrantAliases(Protocol):
    """Protocol for managing Qdrant collection aliases."""

    def collections(self) -> list[str]:
        """Names of the existing collections."""

    def aliases(self) -> dict[str, str]:
        """Map of alias name to the collection it points at."""

    def create_alias(self, alias: str, collection: str) -> None:
        """Point ``alias`` at ``collection``."""

    def delete_alias(self, alias: str) -> None:
        """Remove ``alias``."""


class QdrantClientAliases:
    """Adapter from a ``qdrant_client.QdrantClient`` to ``QdrantAliases``."""

    def __init__(self, client) -> None:
        self._client = client

    def collections(self) -> list[str]:
        return [c.name for c in self._client.get_collections().collections]

    def aliases(self) -> dict[str, str]:
        return {a.alias_name: a.collection_name for a in self._client.get_aliases().aliases}

    def create_alias(self, alias: str, collection: str) -> None:
        from qdrant_client import models

        self._client.update_collection_aliases(
            change_aliases_operations=[
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(collection_name=collection, alias_name=alias)
                )
            ]
        )

    def delete_alias(self, alias: str) -> None:
        from qdrant_client import models

        self._client.update_collection_aliases(
            change_aliases_operations=[
                models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
            ]
        )


def _table() -> Any:
    """Return the legacy-name table module so tests can monkeypatch it."""
    return legacy_names


def _scope_done(scope: str) -> bool:
    """Return whether a rename scope is marked done."""
    return _table().SCOPE_STATUS.get(scope) == "done"


def _active(entries: tuple[dict, ...]) -> list[dict]:
    """Filter table entries whose scope is done."""
    return [e for e in entries if _scope_done(e.get("scope", "persisted"))]


def _module_moves() -> list[tuple[str, str]]:
    """List active module directory renames."""
    if not _scope_done("persisted"):
        return []
    moves: list[tuple[str, str]] = []
    for old_key, info in _table().MODULES.items():
        new_key = info["new_key"]
        if new_key != old_key:
            moves.append((old_key, new_key))
    return moves


def _sha256(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _safe_path(root: Path, rel: object, *, what: str) -> Path:
    """Return ``root / rel`` after validating that ``rel`` stays under ``root``.

    ``rel`` must be a non-empty relative POSIX path with no ``.`` or ``..``
    parts.  Any symlink in an existing parent directory is resolved so the
    resulting path cannot escape the resolved root.
    """
    if not isinstance(rel, str) or not rel:
        raise RenameStateError(f"rename_state: unsafe {what} path {rel!r} in the manifest")
    if rel.startswith("/") or "\\" in rel:
        raise RenameStateError(f"rename_state: unsafe {what} path {rel!r} in the manifest")
    if any(part in ("", ".", "..") for part in rel.split("/")):
        raise RenameStateError(f"rename_state: unsafe {what} path {rel!r} in the manifest")

    base = Path(root).resolve()
    candidate = base / rel
    parent = candidate.parent.resolve(strict=False)
    final = parent / candidate.name
    if not final.is_relative_to(base):
        raise RenameStateError(f"rename_state: unsafe {what} path {rel!r} in the manifest")
    return base / rel


def _refuse_symlink(path: Path, *, what: str) -> None:
    """Raise if ``path`` exists and is a symbolic link."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(st.st_mode):
        raise RenameStateError(
            f"rename_state: {what} {path} is a symbolic link; resolve it by hand and re-run"
        )


def _empty_dir(path: Path) -> bool:
    """Whether ``path`` is a real directory with no entries at all."""
    try:
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode):
            return False
        with os.scandir(path) as it:
            return next(it, None) is None
    except (OSError, ValueError):
        return False


def _vacant_tree(path: Path, *, mount_with_data_ok: bool) -> bool:
    """Whether ``path`` holds no data of the state tree.

    A real directory is vacant when every entry is itself vacant; a file, a
    symlink or any other entry is data. A mount point is never descended into:
    on the new side (``mount_with_data_ok``) the runtime's mount counts as vacant
    whatever it holds, because its content belongs to its volume (the compose
    trainer-jobs volume); on the old side a mount is vacant only when it is
    empty, so a mount holding data is never mistaken for an empty leftover.
    """
    path = Path(path)
    if _is_mount(path):
        return True if mount_with_data_ok else _empty_dir(path)
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return False
    if not stat.S_ISDIR(st.st_mode):
        return False
    try:
        with os.scandir(path) as it:
            for entry in it:
                if not _vacant_tree(Path(entry.path), mount_with_data_ok=mount_with_data_ok):
                    return False
    except OSError:
        return False
    return True


def _vacant_old(path: Path) -> bool:
    """Old side: only empty directories and empty mount points."""
    return _vacant_tree(path, mount_with_data_ok=False)


def _vacant_new(path: Path) -> bool:
    """New side: empty directories and the runtime's mount points."""
    return _vacant_tree(path, mount_with_data_ok=True)


def _nested_mount_with_data(path: Path) -> Path | None:
    """The first mount point below ``path`` that holds data, or None.

    Mount points are not descended into, and symlinks are not followed.
    """
    try:
        with os.scandir(path) as it:
            entries = [Path(e.path) for e in it]
    except OSError:
        return None
    for child in sorted(entries):
        if _is_mount(child):
            if not _empty_dir(child):
                return child
            continue
        try:
            st = os.lstat(child)
        except OSError:
            continue
        if stat.S_ISDIR(st.st_mode):
            found = _nested_mount_with_data(child)
            if found is not None:
                return found
    return None


def _refuse_mount_with_data(root: Path, old_rel: str, new_rel: str) -> None:
    raise RenameStateError(
        f"rename_state: {old_rel} under {root} is a mount holding data; mount it at "
        f"{new_rel} instead and re-run"
    )


def _removable(path: Path) -> bool:
    """Return True when ``path`` is not a mount point and its parent is writable."""
    path = Path(path)
    return not _is_mount(path) and os.access(path.parent, os.W_OK)


def _remove_vacant_step(rel: str) -> dict:
    """Build a pending remove_vacant step dict."""
    return {"kind": "remove_vacant", "path": rel, "status": "pending"}


def _validate_steps(root: Path, steps: object) -> None:
    """Validate the whole step list before anything is touched on disk."""
    if not isinstance(steps, list):
        raise RenameStateError("rename_state: the manifest steps are not a list")

    allowed_statuses = {"pending", "done", "reverted"}

    def _check_keys(step: dict, index: int, kind: str, keys: tuple[str, ...]) -> None:
        for key in keys:
            if key not in step:
                raise RenameStateError(f"rename_state: {kind} step {index} is missing key {key!r}")

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise RenameStateError(f"rename_state: step {index} is not a dict")

        kind = step.get("kind")
        if kind == "move":
            _check_keys(step, index, "move", ("src", "dst", "created_dirs", "status"))
            src = step["src"]
            dst = step["dst"]
            created_dirs = step["created_dirs"]
            status = step["status"]
            companion = step.get("companion", False)
            if (
                not isinstance(src, str)
                or not isinstance(dst, str)
                or not isinstance(status, str)
                or not isinstance(created_dirs, list)
                or not all(isinstance(d, str) for d in created_dirs)
                or not isinstance(companion, bool)
            ):
                raise RenameStateError(f"rename_state: move step {index} has an invalid field type")
            _refuse_symlink(_safe_path(root, src, what="move src"), what="move src")
            _refuse_symlink(_safe_path(root, dst, what="move dst"), what="move dst")
            for rel in created_dirs:
                p = _safe_path(root, rel, what="created dir")
                _refuse_symlink(p, what="created dir")
                if not dst.startswith(rel + "/"):
                    raise RenameStateError(
                        f"rename_state: created dir {rel!r} of move step {index} is not a parent of its destination"
                    )

        elif kind == "stage":
            _check_keys(
                step, index, "stage", ("path", "before_sha256", "after_sha256", "backup", "status")
            )
            path = step["path"]
            backup = step["backup"]
            status = step["status"]
            if (
                not isinstance(path, str)
                or not isinstance(step["before_sha256"], str)
                or not isinstance(step["after_sha256"], str)
                or (backup is not None and not isinstance(backup, str))
                or not isinstance(status, str)
            ):
                raise RenameStateError(
                    f"rename_state: stage step {index} has an invalid field type"
                )
            _refuse_symlink(_safe_path(root, path, what="stage"), what="stage")
            if backup is not None:
                if not backup.startswith(MANIFEST_DIR + "/"):
                    raise RenameStateError(
                        f"rename_state: stage backup {backup!r} of step {index} is outside {MANIFEST_DIR}"
                    )
                _refuse_symlink(_safe_path(root, backup, what="stage backup"), what="stage backup")

        elif kind == "sqlite":
            _check_keys(step, index, "sqlite", ("path", "pairs", "vec", "status"))
            path = step["path"]
            pairs = step["pairs"]
            vec = step["vec"]
            status = step["status"]
            if (
                not isinstance(path, str)
                or not isinstance(pairs, list)
                or not isinstance(vec, bool)
                or not isinstance(status, str)
            ):
                raise RenameStateError(
                    f"rename_state: sqlite step {index} has an invalid field type"
                )
            for pair in pairs:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or not all(isinstance(x, str) for x in pair)
                ):
                    raise RenameStateError(
                        f"rename_state: sqlite step {index} pairs must be 2-item string lists"
                    )
            _refuse_symlink(_safe_path(root, path, what="sqlite"), what="sqlite")

        elif kind == "qdrant_alias":
            _check_keys(step, index, "qdrant_alias", ("alias", "collection", "status"))
            if not all(isinstance(step[k], str) for k in ("alias", "collection", "status")):
                raise RenameStateError(
                    f"rename_state: qdrant_alias step {index} has an invalid field type"
                )

        elif kind == "remove_vacant":
            _check_keys(step, index, "remove_vacant", ("path", "status"))
            path = step["path"]
            status = step["status"]
            if not isinstance(path, str) or not isinstance(status, str):
                raise RenameStateError(
                    f"rename_state: remove_vacant step {index} has an invalid field type"
                )
            _refuse_symlink(
                _safe_path(root, path, what="remove_vacant"), what="remove_vacant"
            )
            removed = step.get("removed", [])
            if not isinstance(removed, list) or not all(isinstance(r, str) for r in removed):
                raise RenameStateError(
                    f"rename_state: remove_vacant step {index} has an invalid field type"
                )
            for rel in removed:
                if rel != path and not rel.startswith(path + "/"):
                    raise RenameStateError(
                        f"rename_state: remove_vacant step {index} removed {rel!r} outside {path!r}"
                    )
                _safe_path(root, rel, what="remove_vacant")

        else:
            raise RenameStateError(f"rename_state: unknown step kind {kind!r} at step {index}")

        if step["status"] not in allowed_statuses:
            raise RenameStateError(
                f"rename_state: invalid status {step['status']!r} at step {index}"
            )


def _validate_manifest(root: Path, manifest: object) -> list[dict]:
    """Validate a manifest dict and return its steps list.

    Raises RenameStateError for structural problems; callers handle JSON
    decoding errors.
    """
    if not isinstance(manifest, dict):
        raise RenameStateError("rename_state: the manifest is not valid")
    if manifest.get("version") != MANIFEST_VERSION:
        raise RenameStateError(
            f"rename_state: manifest version {manifest.get('version')!r} is not supported"
        )
    if manifest.get("status") not in ("in_progress", "complete", "reverting"):
        raise RenameStateError(
            f"rename_state: manifest status {manifest.get('status')!r} is not valid"
        )
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        raise RenameStateError("rename_state: the manifest steps are not a list")
    _validate_steps(root, steps)
    return steps


def _move_step(src: str, dst: str, created_dirs: list[str], *, companion: bool = False) -> dict:
    """Build a pending move step dict."""
    return {
        "kind": "move",
        "src": src,
        "dst": dst,
        "created_dirs": created_dirs,
        "companion": companion,
        "status": "pending",
    }


def _translate_path(path: str, module_map: dict[str, str]) -> str:
    """Apply module renames to the first segment of ``path``."""
    parts = path.split("/")
    if parts[0] in module_map:
        return "/".join([module_map[parts[0]]] + parts[1:])
    return path


def _map_collection(name: str, active_collections: list[dict]) -> str | None:
    """Map a collection name through active rename entries."""
    for entry in active_collections:
        old = entry["old"]
        if old.endswith("_"):
            if name.startswith(old):
                return entry["new"] + name[len(old) :]
        elif name == old:
            return entry["new"]
    return None


def _map_stage_object(obj: dict, active_fields: list[dict], active_values: list[dict]) -> dict:
    """Return a stage object with active field and value renames applied."""
    out = dict(obj)
    for field in active_fields:
        old = field["old"]
        new = field["new"]
        if old in out:
            out[new] = out.pop(old)
    for value in active_values:
        if out.get("stage") == value["old"]:
            out["stage"] = value["new"]
            break
    return out


def _created_dirs_for_dst(root: Path, dst: str, planned: set[str]) -> list[str]:
    """Return parent directories ``dst`` needs, shallowest first, and record them.

    A directory counts as already planned if it is in ``planned`` or exists on
    disk under ``root``.
    """
    parent = Path(dst).parent
    if parent == Path("."):
        created: list[str] = []
    else:
        parts = parent.parts
        created = []
        for i in range(1, len(parts) + 1):
            sub = "/".join(parts[:i])
            if sub not in planned and not (root / sub).is_dir():
                created.append(sub)
                planned.add(sub)
    planned.add(dst)
    return created


def _plan_merge(
    root: Path, old_rel: str, new_rel: str, planned: set[str], steps: list[dict]
) -> None:
    """Plan moving the contents of ``old_rel`` into the vacant ``new_rel``.

    ``new_rel`` must already exist and be a vacant real directory.  Symlinks,
    files, or non-vacant directories on either side raise RenameStateError.
    Mount points are never descended into or moved over.
    """
    old_dir = root / old_rel
    new_dir = root / new_rel
    for entry in sorted(os.scandir(old_dir), key=lambda e: e.name):
        child_rel = f"{old_rel}/{entry.name}"
        target_path = new_dir / entry.name
        target_rel = f"{new_rel}/{entry.name}"
        _refuse_symlink(Path(entry.path), what=f"merge source {child_rel}")
        _refuse_symlink(target_path, what=f"merge target {target_rel}")

        if _is_mount(Path(entry.path)):
            # A mount point cannot be renamed and its content is not the tree's to
            # move. Mounted at the new path as well, it is the runtime's and is left
            # alone when it is empty; a mount holding data is the operator's to
            # mount at the new path.
            if _empty_dir(Path(entry.path)):
                # An empty mount point holds nothing to move; it is left where it is.
                continue
            _refuse_mount_with_data(root, child_rel, target_rel)
        if not target_path.exists():
            created = _created_dirs_for_dst(root, target_rel, planned)
            steps.append(_move_step(child_rel, target_rel, created))
        elif _is_mount(target_path):
            if (
                _vacant_old(Path(entry.path))
                and entry.is_dir(follow_symlinks=False)
                and not _is_mount(Path(entry.path))
            ):
                # Old empty mount-point directory can be left behind.
                continue
            raise RenameStateError(
                f"rename_state: both {child_rel} and {target_rel} exist under {root} "
                "and hold data; move one aside and re-run"
            )
        elif (
            _vacant_new(target_path)
            and not _is_mount(target_path)
            and entry.is_dir(follow_symlinks=False)
            and not _is_mount(Path(entry.path))
        ):
            _plan_merge(root, child_rel, target_rel, planned, steps)
        else:
            raise RenameStateError(
                f"rename_state: both {child_rel} and {target_rel} exist under {root} "
                "and hold data; move one aside and re-run"
            )


def _has_vec_table(db_path: Path) -> bool:
    """Return whether ``db_path`` contains a vec_memories table."""
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'vec_memories' AND type = 'table'"
        )
        return cur.fetchone() is not None
    except sqlite3.Error as exc:
        raise RenameStateError(
            f"rename_state: cannot read {db_path} ({exc}); stop anything using it and re-run"
        ) from exc
    finally:
        if con is not None:
            con.close()


def plan(root: Path, *, qdrant: QdrantAliases | None = None) -> list[dict]:
    """Return the migration steps for ``root`` without writing anything.

    Raises:
        RenameStateError: When a refusal check fails.
    """
    root = Path(root)
    steps: list[dict] = []
    module_moves = _module_moves()
    module_map = {old: new for old, new in module_moves}

    planned: set[str] = set()

    # Step 1: module directory moves.
    for old_key, new_key in module_moves:
        old_dir = root / old_key
        new_dir = root / new_key
        _refuse_symlink(old_dir, what=f"module directory {old_key}")
        _refuse_symlink(new_dir, what=f"module directory {new_key}")
        try:
            old_st = os.lstat(old_dir)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RenameStateError(
                f"rename_state: cannot inspect {old_key} under {root} ({exc}); re-run"
            ) from exc
        if not stat.S_ISDIR(old_st.st_mode):
            continue
        if _is_mount(old_dir) and not _empty_dir(old_dir):
            _refuse_mount_with_data(root, old_key, new_key)
        if _is_mount(old_dir) and not new_dir.exists():
            # A mount point cannot be renamed; the operator mounts the volume at
            # the new path instead.
            raise RenameStateError(
                f"rename_state: {old_key} under {root} is a mount point; mount it at "
                f"{new_key} instead and re-run"
            )
        if not new_dir.exists():
            # Renaming the directory would carry a mount below it to the new path
            # for this boot only; a mount holding data is mounted at its new path
            # by the operator instead.
            nested = _nested_mount_with_data(old_dir)
            if nested is not None:
                rel = nested.relative_to(root).as_posix()
                _refuse_mount_with_data(root, rel, new_key + rel[len(old_key):])
            created = _created_dirs_for_dst(root, new_key, planned)
            steps.append(_move_step(old_key, new_key, created))
        elif _vacant_old(old_dir):
            if _removable(old_dir):
                steps.append(_remove_vacant_step(old_key))
        elif _vacant_new(new_dir) and not _is_mount(new_dir):
            _plan_merge(root, old_key, new_key, planned, steps)
            if _removable(old_dir):
                steps.append(_remove_vacant_step(old_key))
        else:
            raise RenameStateError(
                f"rename_state: both {old_key} and {new_key} exist under {root}; "
                "move one aside and re-run"
            )

    # Step 2: state file moves.
    active_state_paths = _active(_table().STATE_PATHS)
    for entry in active_state_paths:
        old_path = entry["old"]
        new_path = entry["new"]
        original_file = root / old_path
        if not original_file.exists():
            continue
        if old_path != new_path and (root / new_path).exists():
            raise RenameStateError(
                f"rename_state: both {old_path} and {new_path} exist under {root}; "
                "move one aside and re-run"
            )
        translated = _translate_path(old_path, module_map)
        if translated != new_path:
            created = _created_dirs_for_dst(root, new_path, planned)
            steps.append(_move_step(translated, new_path, created))
            if translated.endswith(".db"):
                for suffix in ("-wal", "-shm", "-journal"):
                    companion_src = translated + suffix
                    companion_dst = new_path + suffix
                    if (root / (old_path + suffix)).exists():
                        if (root / companion_dst).exists():
                            raise RenameStateError(
                                f"rename_state: both {old_path + suffix} and "
                                f"{companion_dst} exist under {root}; "
                                "move one aside and re-run"
                            )
                        created = _created_dirs_for_dst(root, companion_dst, planned)
                        steps.append(
                            _move_step(companion_src, companion_dst, created, companion=True)
                        )

    # Step 3: stage file mapping.
    stage_file = root / STAGE_PATH
    if stage_file.is_file():
        try:
            stage_obj = json.loads(stage_file.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError):
            stage_obj = None
        if isinstance(stage_obj, dict):
            active_fields = _active(_table().STAGE_FIELDS)
            active_values = _active(_table().STAGE_VALUES)
            has_old_field = any(field["old"] in stage_obj for field in active_fields)
            has_old_stage_value = any(
                stage_obj.get("stage") == value["old"] for value in active_values
            )
            if has_old_field or has_old_stage_value:
                for field in active_fields:
                    if field["old"] in stage_obj and field["new"] in stage_obj:
                        raise RenameStateError(
                            f"rename_state: stage file holds both {field['old']} and {field['new']}"
                        )
                new_obj = _map_stage_object(stage_obj, active_fields, active_values)
                before_bytes = stage_file.read_bytes()
                after_bytes = json.dumps(new_obj, indent=2, sort_keys=True).encode("utf-8")
                steps.append(
                    {
                        "kind": "stage",
                        "path": STAGE_PATH,
                        "before_sha256": _sha256(before_bytes),
                        "after_sha256": _sha256(after_bytes),
                        "backup": None,
                        "status": "pending",
                    }
                )

    # Step 4: sqlite collection renames.
    active_collections = _active(_table().COLLECTIONS)
    db_entry: dict | None = None
    for entry in active_state_paths:
        if entry["new"].endswith(".db"):
            db_entry = entry
            break
    if db_entry is None:
        for entry in active_state_paths:
            if entry["old"].endswith(".db"):
                db_entry = entry
                break
    if db_entry is not None:
        original_db = root / db_entry["old"]
        is_sqlite = False
        if original_db.is_file():
            with open(original_db, "rb") as fh:
                is_sqlite = fh.read(16) == SQLITE_MAGIC
        if is_sqlite:
            con: sqlite3.Connection | None = None
            try:
                con = sqlite3.connect(f"file:{original_db}?mode=ro", uri=True)
                collections = [
                    row[0]
                    for row in con.execute("SELECT DISTINCT collection FROM memories")
                    if row[0] is not None
                ]
            except sqlite3.Error as exc:
                if "no such table: memories" in str(exc):
                    collections = []
                else:
                    raise RenameStateError(
                        f"rename_state: cannot read the collections in {db_entry['old']} "
                        f"({exc}); stop anything using it and re-run"
                    ) from exc
            finally:
                if con is not None:
                    con.close()
            pairs: list[list[str]] = []
            for name in collections:
                new_name = _map_collection(name, active_collections)
                if new_name is not None:
                    pairs.append([name, new_name])
            for old_name, new_name in pairs:
                if new_name in collections:
                    raise RenameStateError(
                        f"rename_state: database {db_entry['old']} contains both "
                        f"{old_name} and {new_name}"
                    )
            if pairs:
                has_vec = _has_vec_table(original_db)
                if has_vec:
                    try:
                        import sqlite_vec  # noqa: F401
                    except ImportError:
                        raise RenameStateError(
                            f"rename_state: {db_entry['old']} has a sqlite-vec table "
                            "and sqlite_vec is not installed"
                        )
                steps.append(
                    {
                        "kind": "sqlite",
                        "path": db_entry["new"],
                        "pairs": pairs,
                        "vec": has_vec,
                        "status": "pending",
                    }
                )

    # Step 5: Qdrant aliases.
    if qdrant is not None:
        client_collections = qdrant.collections()
        aliases = qdrant.aliases()
        for collection in client_collections:
            alias_name = _map_collection(collection, active_collections)
            if alias_name is None:
                continue
            existing = aliases.get(alias_name)
            if existing == collection:
                continue
            if existing is not None:
                raise RenameStateError(
                    f"rename_state: Qdrant alias {alias_name} already points to {existing}"
                )
            if alias_name in client_collections and alias_name != collection:
                raise RenameStateError(
                    f"rename_state: Qdrant collection {alias_name} already exists"
                )
            steps.append(
                {
                    "kind": "qdrant_alias",
                    "alias": alias_name,
                    "collection": collection,
                    "status": "pending",
                }
            )

    return steps


def _fsync_file(path: Path) -> None:
    """Flush a file's data and metadata to storage."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Flush a directory's metadata to storage."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json_durable(path: Path, payload: Any) -> None:
    """Write JSON to ``path`` durably using a sibling temp file and fsync."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _write_manifest(manifest_path: Path, steps: list[dict], status: str) -> None:
    """Write the in-progress or completed manifest durably."""
    _write_json_durable(
        manifest_path,
        {"version": MANIFEST_VERSION, "status": status, "steps": steps},
    )


def _run_step(root: Path, step: dict, qdrant: QdrantAliases | None) -> None:
    """Execute one migration step if it is not already done."""
    kind = step["kind"]
    if kind == "move":
        _run_move(root, step)
    elif kind == "stage":
        _run_stage(root, step)
    elif kind == "sqlite":
        _run_sqlite(root, step)
    elif kind == "qdrant_alias":
        _run_qdrant_alias(root, step, qdrant)
    elif kind == "remove_vacant":
        _run_remove_vacant(root, step)
    else:
        raise RenameStateError(f"rename_state: unknown step kind {kind!r}")


def _run_move(root: Path, step: dict) -> None:
    """Run a single move step, creating only the planned parent directories."""
    src = _safe_path(root, step["src"], what="move src")
    dst = _safe_path(root, step["dst"], what="move dst")
    _refuse_symlink(src, what="move src")
    _refuse_symlink(dst, what="move dst")

    created_paths: list[Path] = []
    for rel in step.get("created_dirs", []):
        p = _safe_path(root, rel, what="created dir")
        _refuse_symlink(p, what="created dir")
        created_paths.append(p)

    if src.exists() and not dst.exists():
        for p in created_paths:
            p.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)
        log.info("move: %s -> %s", step["src"], step["dst"])
    elif not src.exists() and dst.exists():
        return
    else:
        if not src.exists() and not dst.exists():
            if step.get("companion"):
                log.debug(
                    "companion move %s -> %s already done (both missing)",
                    step["src"],
                    step["dst"],
                )
                return
            raise RenameStateError(
                f"rename_state: neither {step['src']} nor {step['dst']} exists under {root}; "
                "the tree changed since the manifest was written"
            )
        raise RenameStateError(
            f"rename_state: both {step['src']} and {step['dst']} exist under {root}; "
            "move one aside and re-run"
        )


def _run_remove_vacant(root: Path, step: dict) -> None:
    """Remove a vacant directory tree bottom-up, leaving mount points alone."""
    rel = step["path"]
    path = _safe_path(root, rel, what="remove_vacant")
    _refuse_symlink(path, what="remove_vacant")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RenameStateError(
            f"rename_state: cannot remove empty directory {rel} ({exc})"
        ) from exc
    if not stat.S_ISDIR(st.st_mode):
        return
    if _is_mount(path):
        log.info("remove_vacant: %s is a mount point; leaving it", rel)
        return

    to_remove: list[Path] = []

    def _refuse(what: Path, why: str) -> None:
        # Raised from the step, so the manifest stays in progress and the start
        # stops with the refusal; nothing but empty directories was removed.
        raise RenameStateError(
            f"rename_state: cannot remove {what.relative_to(Path(root).resolve())} ({why}); "
            "move its content aside and re-run"
        )

    def _collect(dir_path: Path) -> None:
        try:
            with os.scandir(dir_path) as it:
                entries = [Path(e.path) for e in it]
        except OSError as exc:
            _refuse(dir_path, exc.strerror or type(exc).__name__)
        for child in entries:
            if _is_mount(child):
                if not _empty_dir(child):
                    _refuse(child, "a mount holding data")
                continue
            cst = os.lstat(child)
            if stat.S_ISLNK(cst.st_mode) or not stat.S_ISDIR(cst.st_mode):
                _refuse(child, "it holds data")
            _collect(child)
        to_remove.append(dir_path)

    _collect(path)

    to_remove.sort(key=lambda p: len(p.parts), reverse=True)
    removed: list[str] = list(step.get("removed") or [])
    for dir_path in to_remove:
        try:
            os.rmdir(dir_path)
            rel_removed = dir_path.relative_to(Path(root).resolve()).as_posix()
            if rel_removed not in removed:
                removed.append(rel_removed)
            # Recorded in the manifest with the step, so a revert recreates every
            # directory this step removed, not only the top one.
            step["removed"] = removed
        except FileNotFoundError:
            continue
        except OSError as exc:
            # Only a directory still holding an empty mount point (which is never
            # removed) may stay; anything else stops the run.
            try:
                with os.scandir(dir_path) as it:
                    left = [Path(e.path) for e in it]
            except OSError:
                left = []
            if left and all(_is_mount(c) and _empty_dir(c) for c in left):
                log.info(
                    "remove_vacant: leaving %s, which holds an empty mount point",
                    dir_path.relative_to(Path(root).resolve()),
                )
                continue
            _refuse(dir_path, exc.strerror or type(exc).__name__)


def _run_stage(root: Path, step: dict) -> None:
    """Run a single stage-file mapping step."""
    path = _safe_path(root, step["path"], what="stage")
    _refuse_symlink(path, what="stage")
    backup_rel = step.get("backup")
    if backup_rel is not None:
        _refuse_symlink(_safe_path(root, backup_rel, what="stage backup"), what="stage backup")

    current = path.read_bytes()
    current_sha = _sha256(current)
    if current_sha == step["after_sha256"]:
        return
    if current_sha != step["before_sha256"]:
        raise RenameStateError("rename_state: stage file changed since the manifest was written")
    obj = json.loads(current)
    new_obj = _map_stage_object(obj, _active(_table().STAGE_FIELDS), _active(_table().STAGE_VALUES))
    new_bytes = json.dumps(new_obj, indent=2, sort_keys=True).encode("utf-8")
    if _sha256(new_bytes) != step["after_sha256"]:
        raise RenameStateError("rename_state: stage mapping changed since the manifest was written")
    write_json_atomic(path, new_obj)
    log.info("stage: %s", step["path"])


def _is_done_sqlite(con: sqlite3.Connection, old_names: list[str]) -> bool:
    """Return whether the sqlite database still contains any old collection name."""
    if not old_names:
        return True
    placeholders = ",".join("?" for _ in old_names)
    cur = con.execute(
        f"SELECT 1 FROM memories WHERE collection IN ({placeholders}) LIMIT 1",
        old_names,
    )
    return cur.fetchone() is None


def _rewrite_vec_table(con: sqlite3.Connection, pairs: list[list[str]]) -> None:
    """Rewrite vec_memories so collection names follow the new mapping."""
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'vec_memories' AND type = 'table'"
    ).fetchone()
    if row is None:
        return
    create_sql = row[0]
    con.execute(
        "CREATE TEMP TABLE _vec_backup (rowid INTEGER PRIMARY KEY, collection TEXT, embedding BLOB)"
    )
    for rowid, collection, embedding in con.execute(
        "SELECT rowid, collection, embedding FROM vec_memories"
    ):
        con.execute(
            "INSERT INTO _vec_backup (rowid, collection, embedding) VALUES (?, ?, ?)",
            (rowid, collection, embedding),
        )
    con.execute("DROP TABLE vec_memories")
    con.execute(create_sql)
    mapping = {old: new for old, new in pairs}
    for rowid, collection, embedding in con.execute(
        "SELECT rowid, collection, embedding FROM _vec_backup"
    ):
        new_collection = mapping.get(collection, collection)
        con.execute(
            "INSERT INTO vec_memories (rowid, collection, embedding) VALUES (?, ?, ?)",
            (rowid, new_collection, embedding),
        )


def _apply_sqlite_renames(db_path: Path, pairs: list[list[str]], vec: bool) -> bool:
    """Apply collection renames inside a sqlite database transaction."""
    old_names = [p[0] for p in pairs]
    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        if vec:
            import sqlite_vec

            con.enable_load_extension(True)
            sqlite_vec.load(con)
            con.enable_load_extension(False)
        con.execute("BEGIN IMMEDIATE")
        if _is_done_sqlite(con, old_names):
            con.execute("COMMIT")
            return False
        for old_name, new_name in pairs:
            con.execute(
                "UPDATE memories SET collection = ? WHERE collection = ?",
                (new_name, old_name),
            )
        if vec:
            _rewrite_vec_table(con, pairs)
        con.execute("COMMIT")
        return True
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _run_sqlite(root: Path, step: dict) -> None:
    """Run a single sqlite collection-rename step."""
    db_path = _safe_path(root, step["path"], what="sqlite")
    _refuse_symlink(db_path, what="sqlite")
    if _apply_sqlite_renames(db_path, step["pairs"], step.get("vec", False)):
        log.info("sqlite: %s", step["path"])


def _run_qdrant_alias(root: Path, step: dict, qdrant: QdrantAliases | None) -> None:
    """Run a single Qdrant alias creation step."""
    if qdrant is None:
        raise RenameStateError("rename_state: qdrant_alias step requires a Qdrant client")
    alias = step["alias"]
    collection = step["collection"]
    if qdrant.aliases().get(alias) == collection:
        return
    qdrant.create_alias(alias, collection)
    log.info("qdrant_alias: %s -> %s", alias, collection)


def migrate(
    root: Path,
    *,
    qdrant: QdrantAliases | None = None,
    no_qdrant: bool = False,
    dry_run: bool = False,
) -> RenameResult:
    """Run the rename migration on ``root``."""
    root = Path(root)
    if qdrant is not None and no_qdrant:
        raise RenameStateError("rename_state: pass a Qdrant client or no_qdrant=True, not both")
    if qdrant is None and not no_qdrant:
        raise RenameStateError(
            "rename_state: pass a Qdrant client or no_qdrant=True; "
            "a migration never leaves the Qdrant store under its old names by accident"
        )
    if dry_run:
        steps = plan(root, qdrant=qdrant)
        return RenameResult("dry_run", tuple(steps))

    _refuse_symlink(root / MANIFEST_DIR, what="manifest directory")
    manifest_path = root / MANIFEST_DIR / MANIFEST_NAME
    _refuse_symlink(manifest_path, what="manifest")
    existing: dict | None = None
    existing_steps: list[dict] | None = None

    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_bytes())
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise RenameStateError("rename_state: the manifest is not valid JSON")
        existing_steps = _validate_manifest(root, existing)

        if existing["status"] == "reverting":
            raise RenameStateError("a previous rename is mid-revert; run --revert first")
        if existing["status"] == "in_progress":
            _execute(root, existing_steps, qdrant, manifest_path, resuming=True)
            return RenameResult("resumed", tuple(existing_steps))

    steps = plan(root, qdrant=qdrant)
    if not steps:
        return RenameResult("noop", ())

    if existing is not None and existing["status"] == "complete":
        # Stage steps carried over from a complete manifest must keep their own
        # backups, and those backups must still exist.
        for step in existing_steps:
            if step["kind"] != "stage":
                continue
            backup = step.get("backup")
            backup_path = (
                _safe_path(root, backup, what="stage backup") if backup is not None else None
            )
            if backup_path is None or not backup_path.exists():
                raise RenameStateError(
                    f"rename_state: the stage backup {backup} is missing; "
                    "the manifest cannot be reverted"
                )
        combined_steps = existing_steps + steps
    else:
        combined_steps = steps

    _validate_steps(root, combined_steps)

    existing_step_count = len(existing_steps) if existing_steps is not None else 0
    for index, step in enumerate(combined_steps):
        if step["kind"] != "stage":
            continue
        if index < existing_step_count:
            # Carried over from the previous complete manifest; leave backup alone.
            continue
        new_backup = f"{MANIFEST_DIR}/stage.{index}.json.orig"
        step["backup"] = new_backup
        backup_path = root / new_backup
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_safe_path(root, step["path"], what="stage"), backup_path)
        _fsync_file(backup_path)
        _fsync_dir(backup_path.parent)

    _write_manifest(manifest_path, combined_steps, status="in_progress")
    _execute(root, combined_steps, qdrant, manifest_path, resuming=False)
    return RenameResult("migrated", tuple(combined_steps))


def _execute(
    root: Path,
    steps: list[dict],
    qdrant: QdrantAliases | None,
    manifest_path: Path,
    *,
    resuming: bool,
) -> None:
    """Execute all steps, updating the manifest after each one."""
    for index, step in enumerate(steps):
        _run_step(root, step, qdrant)
        step["status"] = "done"
        status = "complete" if index == len(steps) - 1 else "in_progress"
        _write_manifest(manifest_path, steps, status=status)


def _revert_step(root: Path, step: dict, qdrant: QdrantAliases | None) -> None:
    """Undo a single migration step."""
    kind = step["kind"]
    if kind == "move":
        _revert_move(root, step)
    elif kind == "stage":
        _revert_stage(root, step)
    elif kind == "sqlite":
        _revert_sqlite(root, step)
    elif kind == "qdrant_alias":
        _revert_qdrant_alias(root, step, qdrant)
    elif kind == "remove_vacant":
        _revert_remove_vacant(root, step)
    else:
        raise RenameStateError(f"rename_state: unknown step kind {kind!r}")


def _revert_move(root: Path, step: dict) -> None:
    """Revert a move step and remove any directories it created."""
    src = _safe_path(root, step["src"], what="move src")
    dst = _safe_path(root, step["dst"], what="move dst")
    _refuse_symlink(src, what="move src")
    _refuse_symlink(dst, what="move dst")

    if dst.exists() and not src.exists():
        os.rename(dst, src)
        for rel in reversed(step.get("created_dirs", [])):
            p = _safe_path(root, rel, what="created dir")
            _refuse_symlink(p, what="created dir")
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        log.info("revert move: %s <- %s", step["src"], step["dst"])
    elif src.exists() and not dst.exists():
        return
    else:
        if not src.exists() and not dst.exists():
            log.debug(
                "revert move %s <- %s already reverted (both missing)",
                step["src"],
                step["dst"],
            )
            return
        raise RenameStateError(
            f"rename_state: both {step['src']} and {step['dst']} exist under {root}; "
            "move one aside and re-run"
        )


def _revert_remove_vacant(root: Path, step: dict) -> None:
    """Recreate an empty directory that was removed by a remove_vacant step."""
    rel = step["path"]
    path = _safe_path(root, rel, what="remove_vacant")
    path.mkdir(parents=True, exist_ok=True)
    for removed in sorted(step.get("removed") or [], key=lambda r: len(r.split("/"))):
        _safe_path(root, removed, what="remove_vacant").mkdir(parents=True, exist_ok=True)
    log.info("revert remove_vacant: %s", rel)


def _revert_stage(root: Path, step: dict) -> None:
    """Revert a stage-file mapping step from its backup."""
    path = _safe_path(root, step["path"], what="stage")
    _refuse_symlink(path, what="stage")
    backup = _safe_path(root, step["backup"], what="stage backup")
    _refuse_symlink(backup, what="stage backup")

    current = path.read_bytes()
    current_sha = _sha256(current)
    if current_sha == step["before_sha256"]:
        return
    if current_sha != step["after_sha256"]:
        raise RenameStateError("rename_state: stage file changed since the manifest was written")
    backup_bytes = backup.read_bytes()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(backup_bytes)
    os.replace(tmp, path)
    log.info("revert stage: %s", step["path"])


def _revert_sqlite(root: Path, step: dict) -> None:
    """Revert a sqlite collection-rename step if the database is still present."""
    db_path = _safe_path(root, step["path"], what="sqlite")
    _refuse_symlink(db_path, what="sqlite")
    if not db_path.exists():
        return
    reversed_pairs = [[new, old] for old, new in step["pairs"]]
    if _apply_sqlite_renames(db_path, reversed_pairs, step.get("vec", False)):
        log.info("revert sqlite: %s", step["path"])


def _revert_qdrant_alias(root: Path, step: dict, qdrant: QdrantAliases | None) -> None:
    """Revert a Qdrant alias creation step."""
    if qdrant is None:
        raise RenameStateError("rename_state: qdrant_alias step requires a Qdrant client")
    alias = step["alias"]
    collection = step["collection"]
    current = qdrant.aliases().get(alias)
    if current == collection:
        qdrant.delete_alias(alias)
        log.info("revert qdrant_alias: %s", alias)
    elif current is not None:
        raise RenameStateError(
            f"rename_state: Qdrant alias {alias} now points at {current}, not {collection}; leaving it"
        )


def _precheck_revert(root: Path, steps: list[dict], qdrant: QdrantAliases | None) -> None:
    """Walk steps in reverse order and refuse if any step cannot be undone cleanly.

    This inspects disk and Qdrant state but does not write anything.
    """
    expected_stage_sha: dict[str, str] = {}
    for step in reversed(steps):
        kind = step["kind"]
        if kind == "move":
            src = _safe_path(root, step["src"], what="move src")
            dst = _safe_path(root, step["dst"], what="move dst")
            if src.exists() and dst.exists():
                raise RenameStateError(
                    f"rename_state: both {step['src']} and {step['dst']} exist under {root}; "
                    "move one aside and re-run"
                )
        elif kind == "stage":
            path = _safe_path(root, step["path"], what="stage")
            if not path.exists():
                raise RenameStateError(
                    f"rename_state: stage file {step['path']} is missing; cannot revert"
                )
            current_sha = expected_stage_sha.get(step["path"])
            if current_sha is None:
                current_sha = _sha256(path.read_bytes())
            after = step["after_sha256"]
            before = step["before_sha256"]
            if current_sha == after:
                backup = step.get("backup")
                if backup is None:
                    raise RenameStateError(
                        f"rename_state: stage step {step['path']} has no backup; cannot revert"
                    )
                backup_path = _safe_path(root, backup, what="stage backup")
                if not backup_path.exists():
                    raise RenameStateError(
                        f"rename_state: stage backup {backup} is missing; cannot revert"
                    )
                expected_stage_sha[step["path"]] = before
            elif current_sha == before:
                expected_stage_sha[step["path"]] = before
            else:
                raise RenameStateError(
                    "rename_state: the stage file changed since the migration; "
                    "it is not reverted (inspect it, then revert by hand)"
                )
        elif kind == "qdrant_alias":
            if qdrant is None:
                raise RenameStateError(
                    "the manifest has Qdrant aliases; pass a Qdrant client to revert them"
                )
            alias = step["alias"]
            collection = step["collection"]
            current = qdrant.aliases().get(alias)
            if current is not None and current != collection:
                raise RenameStateError(
                    f"rename_state: Qdrant alias {alias} now points at {current}, "
                    f"not {collection}; leaving it"
                )


def revert(root: Path, *, qdrant: QdrantAliases | None = None) -> RenameResult:
    """Revert a completed or partially-completed rename migration."""
    root = Path(root)
    manifest_path = root / MANIFEST_DIR / MANIFEST_NAME
    if not manifest_path.exists():
        raise RenameStateError("nothing to revert")

    _refuse_symlink(root / MANIFEST_DIR, what="manifest directory")
    _refuse_symlink(manifest_path, what="manifest")

    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RenameStateError("rename_state: the manifest is not valid JSON")
    steps = _validate_manifest(root, manifest)

    _precheck_revert(root, steps, qdrant)

    _write_manifest(manifest_path, steps, status="reverting")
    for step in reversed(steps):
        _revert_step(root, step, qdrant)
        step["status"] = "reverted"
        _write_manifest(manifest_path, steps, status="reverting")

    shutil.rmtree(root / MANIFEST_DIR)
    log.info("reverted: %s", root)
    return RenameResult("reverted", tuple(steps))


def _format_step(step: dict) -> str:
    """Return a one-line description of a migration step."""
    kind = step["kind"]
    if kind == "move":
        return f"move: {step['src']} -> {step['dst']}"
    if kind == "stage":
        return f"stage: {step['path']}"
    if kind == "sqlite":
        return f"sqlite: {step['path']}"
    if kind == "qdrant_alias":
        return f"qdrant_alias: {step['alias']} -> {step['collection']}"
    if kind == "remove_vacant":
        return f"remove empty: {step['path']}"
    return f"{kind}: {step}"


def migrate_at_boot(config: Mapping[str, Any], state_root: Path) -> RenameResult:
    """Migrate the live state tree before the cycle reads it.

    Safe to call on every boot: a tree that is already migrated returns a
    ``noop`` result without writing anything. When Qdrant is configured, this
    function builds a client, performs the migration with alias updates, and
    closes the client afterwards.
    """
    state_root = Path(state_root)
    if not state_root.exists():
        return RenameResult("noop", ())

    from kaine.lifecycle import decommission

    qdrant_in_use = decommission.qdrant_in_use(config)
    if qdrant_in_use:
        client = decommission._qdrant_client(config)
        if client is None:
            raise RenameStateError(
                "rename_state: Qdrant is in use but no client could be built; "
                "check [episodic_memory.qdrant] and re-run"
            )
        adapter = QdrantClientAliases(client)
        try:
            result = migrate(state_root, qdrant=adapter)
        except (RenameStateError, OSError, sqlite3.Error):
            raise
        except Exception as exc:
            # A Qdrant client raises its own error types (an unreachable server, a
            # refused key). Report them as a refusal, not a traceback; a run
            # interrupted after its manifest resumes on the next start.
            raise RenameStateError(
                f"rename_state: Qdrant could not be used ({type(exc).__name__}: {exc}); "
                "check that Qdrant is running and re-run"
            ) from exc
        finally:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("rename_state: ignoring Qdrant client close error: %s", exc)
    else:
        result = migrate(state_root, no_qdrant=True)

    if result.status != "noop":
        log.info("rename_state: %s; %d steps", result.status, len(result.steps))
        for step in result.steps:
            log.info("rename_state: %s", _format_step(step))

    return result


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point for the rename migration."""
    parser = argparse.ArgumentParser(prog="kaine.lifecycle.rename_state")
    parser.add_argument("root")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    qdrant_group = parser.add_mutually_exclusive_group()
    qdrant_group.add_argument("--qdrant-url")
    qdrant_group.add_argument("--no-qdrant", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not args.revert and not args.qdrant_url and not args.no_qdrant:
        print(
            "kaine.lifecycle.rename_state: pass --qdrant-url URL or --no-qdrant",
            file=sys.stderr,
        )
        return 2
    qdrant: QdrantAliases | None = None
    if args.qdrant_url:
        try:
            from qdrant_client import QdrantClient
        except ImportError:
            print(
                "kaine.lifecycle.rename_state: --qdrant-url needs the qdrant-client package",
                file=sys.stderr,
            )
            return 2
        qdrant = QdrantClientAliases(QdrantClient(url=args.qdrant_url))

    try:
        if args.revert:
            result = revert(root, qdrant=qdrant)
        elif args.dry_run:
            result = migrate(root, qdrant=qdrant, no_qdrant=args.no_qdrant, dry_run=True)
        else:
            result = migrate(root, qdrant=qdrant, no_qdrant=args.no_qdrant)

        for step in result.steps:
            print(_format_step(step))
        print(f"status: {result.status}")
        return 0
    except RenameStateError as exc:
        print(f"kaine.lifecycle.rename_state: {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error, ImportError) as exc:
        print(
            f"kaine.lifecycle.rename_state: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
