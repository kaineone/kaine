# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Wizard step and helpers for selecting and relocating KAINE's data root."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from kaine.lifecycle.liveness import cycle_process_running
from kaine.setup.steps import Field, Step, StepContext

PSEUDO_FS = frozenset(
    {
        "proc",
        "sysfs",
        "tmpfs",
        "devtmpfs",
        "devpts",
        "cgroup",
        "cgroup2",
        "overlay",
        "squashfs",
        "securityfs",
        "pstore",
        "debugfs",
        "tracefs",
        "configfs",
        "fusectl",
        "mqueue",
        "hugetlbfs",
        "autofs",
        "binfmt_misc",
        "bpf",
        "nsfs",
        "ramfs",
        "efivarfs",
        "fuse.portal",
        "fuse.gvfsd-fuse",
        "nfsd",
        "rpc_pipefs",
    }
)

SKIP_PREFIXES = ("/proc", "/sys", "/dev", "/run", "/snap", "/boot")

GROWING_VOLUMES = (
    "kaine-state",
    "kaine-eval-data",
    "kaine-trajectory",
    "kaine-backups",
    "kaine-ignition",
    "kaine-nexus-record",
    "kaine-studies",
    "kaine-redis-data",
    "kaine-qdrant-data",
    "kaine-models",
)

_RELOCATE_SUBDIRS = ("state", "data", "backups", "studies")


def list_filesystems(
    mounts_path: Path = Path("/proc/mounts"),
    disk_usage: Callable[[str], Any] = shutil.disk_usage,
) -> list[dict]:
    """Return a list of real, mounted filesystems with free space.

    One entry per physical device (first mount wins).  Pseudofilesystems,
    loop/snap mounts and anything under ``/proc``, ``/sys``, ``/dev``,
    ``/run``, ``/snap`` or ``/boot`` are ignored.  Never raises.
    """
    try:
        text = mounts_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    rows: dict[str, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue

        device = parts[0]
        mount = parts[1].replace("\\040", " ")
        fstype = parts[2]

        if fstype in PSEUDO_FS:
            continue
        if any(mount == prefix or mount.startswith(prefix + "/") for prefix in SKIP_PREFIXES):
            continue
        if device in rows:
            continue

        try:
            usage = disk_usage(mount)
        except Exception:
            continue

        rows[device] = {
            "mount": mount,
            "device": device,
            "fstype": fstype,
            "total_gb": usage.total / (1024**3),
            "free_gb": usage.free / (1024**3),
            "is_system": mount == "/",
        }

    return list(rows.values())


def recommend_root(filesystems: list[dict]) -> str | None:
    """Recommend a non-system data root if one has more free space.

    Returns ``<largest_data_mount>/kaine`` when a non-system filesystem has
    strictly more free space than the system drive, otherwise ``None``.
    """
    system: dict | None = None
    best: dict | None = None
    for fs in filesystems:
        if fs.get("is_system"):
            system = fs
            continue
        if best is None or fs["free_gb"] > best["free_gb"]:
            best = fs
    if best and system and best["free_gb"] > system["free_gb"]:
        return str(Path(best["mount"]) / "kaine")
    return None


def free_gb_at(path: Path, disk_usage: Callable[[str], Any] = shutil.disk_usage) -> float:
    """Return free gigabytes on the nearest existing ancestor of *path*."""
    p = Path(path).expanduser()
    while not p.exists():
        parent = p.parent
        if parent == p:
            break
        p = parent
    usage = disk_usage(str(p))
    return usage.free / (1024**3)


def _filesystems_for(ctx: StepContext) -> list[dict]:
    """Return (and cache) the filesystem list for *ctx*."""
    if "filesystems" not in ctx.extra:
        ctx.extra["filesystems"] = list_filesystems()
    return ctx.extra["filesystems"]


def _explain_storage(ctx: StepContext) -> list[str]:
    filesystems = _filesystems_for(ctx)
    lines: list[str] = []

    for fs in filesystems:
        flag = " — system drive" if fs["is_system"] else ""
        lines.append(
            f"  {fs['mount']} ({fs['fstype']}): {fs['free_gb']:.0f} GB free of "
            f"{fs['total_gb']:.0f} GB{flag}"
        )

    recommendation = recommend_root(filesystems)
    if recommendation:
        lines.append(f"Recommendation: {recommendation}")
    else:
        lines.append("the working directory is fine here")

    lines.append(
        "memories, logs, evaluation output, backups and models all grow under this root."
    )
    return lines


def _storage_fields(ctx: StepContext) -> tuple[Field, ...]:
    filesystems = _filesystems_for(ctx)
    recommendation = recommend_root(filesystems)

    def _validate_data_root(value: Any) -> str | None:
        if value == "" or value is None:
            return None

        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            return "path must be absolute"

        min_free_gb = float(ctx.extra.get("min_free_gb", 20.0))

        try:
            free = free_gb_at(path)
        except Exception as exc:
            return f"could not check free space at {value}: {exc}"

        if free < min_free_gb:
            return (
                f"only {free:.1f} GB free at {value}; at least {min_free_gb:g} GB is required"
            )
        return None

    return (
        Field(
            name="data_root",
            prompt="Data root (empty keeps the working directory)",
            kind="text",
            default=recommendation or "",
            validate=_validate_data_root,
        ),
    )


def _apply_storage(ctx: StepContext, answers: dict[str, Any]) -> None:
    value = answers.get("data_root", "")
    if value:
        ctx.config["storage"] = {
            "data_root": str(Path(str(value)).expanduser()),
        }


storage_step = Step(
    id="storage",
    title="Where growing data lives",
    explanation=_explain_storage,
    fields=_storage_fields,
    applies=lambda _ctx: True,
    apply=_apply_storage,
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def relocate(
    old_root: Path,
    new_root: Path,
    subdirs: tuple[str, ...] = _RELOCATE_SUBDIRS,
    *,
    out: Callable[[str], Any],
) -> tuple[bool, str]:
    """Copy and verify KAINE data from *old_root* to *new_root*.

    The original tree is never deleted.  Verification checks size and SHA-256
    for every regular file before reporting success.
    """
    if cycle_process_running():
        return (
            False,
            "a KAINE cycle is running; stop it before moving its data",
        )

    old_root = Path(old_root)
    new_root = Path(new_root)

    # Copying a tree into a directory inside itself never terminates.
    new_resolved = new_root.resolve()
    for sub in subdirs:
        src = old_root / sub
        if src.exists() and new_resolved.is_relative_to(src.resolve()):
            return (
                False,
                f"the new root {new_root} is inside {src}; choose a location outside the current data",
            )

    for sub in subdirs:
        src = old_root / sub
        if not src.exists():
            continue
        dst = new_root / sub
        if dst.exists() and any(dst.iterdir()):
            return (
                False,
                f"{dst} already exists and is not empty; refusing to overwrite",
            )
        try:
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
        except Exception as exc:
            return False, f"could not copy {src} to {dst}: {exc}"

    n = 0
    for sub in subdirs:
        src = old_root / sub
        if not src.exists():
            continue
        for root, _dirs, files in os.walk(src, followlinks=False):
            for name in files:
                src_file = Path(root) / name
                if not src_file.is_file():
                    continue
                rel = src_file.relative_to(old_root)
                dst_file = new_root / rel
                if not dst_file.is_file():
                    return (
                        False,
                        f"verification failed for {rel}; the new copy was left in place "
                        "for inspection and the configuration was not changed",
                    )
                if dst_file.stat().st_size != src_file.stat().st_size:
                    return (
                        False,
                        f"verification failed for {rel}; the new copy was left in place "
                        "for inspection and the configuration was not changed",
                    )
                if _sha256(dst_file) != _sha256(src_file):
                    return (
                        False,
                        f"verification failed for {rel}; the new copy was left in place "
                        "for inspection and the configuration was not changed",
                    )
                n += 1

    return (
        True,
        f"copied and verified {n} files; the original at {old_root} was left in place "
        "— remove it yourself when you are satisfied",
    )


def _relocation_applies(ctx: StepContext) -> bool:
    old = ctx.extra.get("old_root")
    new_path = (ctx.config.get("storage") or {}).get("data_root")
    if old is None or not new_path:
        return False

    old_p = Path(str(old)).resolve()
    new_p = Path(str(new_path)).expanduser().resolve()
    if old_p == new_p:
        return False

    return any((old_p / s).exists() for s in _RELOCATE_SUBDIRS)


def _relocation_fields(ctx: StepContext) -> tuple[Field, ...]:
    return (
        Field(
            name="move",
            prompt="Copy the existing data to the new root now?",
            kind="bool",
            default=True,
        ),
    )


def _apply_relocation(ctx: StepContext, answers: dict[str, Any]) -> None:
    old = ctx.extra.get("old_root")
    new_path = (ctx.config.get("storage") or {}).get("data_root")
    if old is None or not new_path:
        return

    old_p = Path(str(old)).resolve()
    new_p = Path(str(new_path)).expanduser().resolve()
    if old_p == new_p:
        ctx.extra["relocation_note"] = (
            f"old and new data roots are the same ({old_p}); nothing to move"
        )
        return

    present_subdirs = [s for s in _RELOCATE_SUBDIRS if (old_p / s).exists()]
    if not present_subdirs:
        ctx.extra["relocation_note"] = (
            f"no KAINE data directories at {old_p}; nothing to move"
        )
        return

    move = answers.get("move", True)
    if isinstance(move, str):
        move = move.strip().lower() in {"y", "yes", "true", "1"}

    out = ctx.extra.get("out", lambda _s: None)
    if not move:
        ctx.extra["relocation_note"] = (
            f"existing data stays at {old_p}; the new root {new_p} will start empty"
        )
        return

    ok, msg = relocate(old_p, new_p, subdirs=_RELOCATE_SUBDIRS, out=out)
    if ok:
        ctx.extra["relocation_note"] = msg
    else:
        ctx.config.pop("storage", None)
        ctx.extra["relocation_error"] = msg


relocation_step = Step(
    id="relocation",
    title="Move existing data",
    explanation=lambda _ctx: [],
    fields=_relocation_fields,
    applies=_relocation_applies,
    apply=_apply_relocation,
)


def render_volume_override(root: Path) -> str:
    """Return a compose YAML fragment that binds KAINE volumes under *root*."""
    root = Path(root)
    lines = [
        "# Generated by `python -m kaine.setup`: binds KAINE's growing volumes "
        "under the data root.",
        "# This file is local and gitignored.",
        "volumes:",
    ]
    for v in GROWING_VOLUMES:
        lines.extend(
            [
                f"  {v}:",
                f"    name: {v}",
                "    driver: local",
                "    driver_opts:",
                "      type: none",
                "      o: bind",
                f"      device: {root / 'volumes' / v}",
            ]
        )
    return "\n".join(lines) + "\n"


def existing_volumes(run: Callable[..., Any] = subprocess.run) -> set[str] | None:
    """Return the set of existing Docker volume names, or ``None`` on failure."""
    try:
        result = run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            return None
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}
    except Exception:
        return None


def write_volume_override(
    root: Path,
    compose_dir: Path,
    *,
    existing: set[str] | None,
) -> tuple[bool, str]:
    """Write the local compose volume override if it is safe to do so."""
    root = Path(root)
    compose_dir = Path(compose_dir)

    if existing is None:
        return False, "docker is not available; no compose override written"

    overlap = [v for v in GROWING_VOLUMES if v in existing]
    if overlap:
        lines = [
            "existing docker volumes would hide their data if bound over: "
            + ", ".join(overlap),
            "Copy them to the data root first, then remove the old volumes, "
            "before using this override:",
        ]
        for v in overlap:
            lines.append(
                f"docker run --rm -v {v}:/from -v {root / 'volumes' / v}:/to "
                "alpine sh -c 'cp -a /from/. /to/'"
            )
        return False, "\n".join(lines)

    for v in GROWING_VOLUMES:
        (root / "volumes" / v).mkdir(parents=True, exist_ok=True)

    path = compose_dir / "kaine.storage.local.yml"
    path.write_text(render_volume_override(root))
    return (
        True,
        f"wrote {path}; add -f compose/kaine.storage.local.yml to your compose commands",
    )
