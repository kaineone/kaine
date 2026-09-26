# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator revive boot helpers.

The operator revive order is:

  1. Parse ``--revive <bundle>``. Read the bundle's members.
  2. If the bundle carries ``stage.json``, write it to the stage path *before*
     ``_resolve_boot_stage`` runs, so gestation, the womb hold and the gate
     all see the preserved stage.
  3. Build the registry and initialise the modules.
  4. ``await revive(bundle, registry)``.
  5. Log any modules enabled now but not captured by the bundle as "new
     faculty, starting fresh".
  6. Start the cycle, recording ``revived_from`` in ``runtime.json`` and the
     run context.

Module initialisation happens before revive because Eidolon's ``initialize()``
reloads its disk file; a revive before it would be overwritten. Background
loops started during ``initialize()`` run briefly on fresh state before the
revive lands, but the cognitive cycle (and so the workspace) has not started,
so this is safe. This is the same order the research gate's self-check already
relies on.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kaine.lifecycle import preservation as _preservation
from kaine.lifecycle.preservation import read_bundle_stage
from kaine.lifecycle.stage import StageState, write_stage

log = logging.getLogger(__name__)

REVIVE_REFUSED_EXIT = 7


class ReviveRefused(RuntimeError):
    """The bundle cannot be revived into this runtime."""


@dataclass(frozen=True)
class RevivePlan:
    bundle: Path
    preservation_id: str | None
    stage: dict | None


def prepare_revive(bundle: str | Path) -> RevivePlan:
    """Validate a bundle and produce a revive plan.

    Raises :class:`ReviveRefused` when the path is not a directory, when its
    members cannot be read, when it has no ``snapshot.json``, or when its stage
    member is unreadable/invalid.
    """
    bundle = Path(bundle)

    if not bundle.is_dir():
        raise ReviveRefused(f"revive bundle is not a directory: {bundle}")

    try:
        members = _preservation._read_bundle_members(bundle)
    except Exception as exc:
        # Any failure to read (a wrong key, a corrupt tar) refuses the revive
        # cleanly rather than crashing the boot with a traceback.
        raise ReviveRefused(
            f"could not read bundle members: {type(exc).__name__}: {exc}"
        ) from exc

    if "snapshot.json" not in members:
        raise ReviveRefused(
            f"preservation bundle has no snapshot.json (tar or loose): {bundle}"
        )

    preservation_id: str | None = None
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
            preservation_id = manifest.get("preservation_id")
        except (json.JSONDecodeError, OSError):
            pass

    try:
        stage = read_bundle_stage(bundle)
    except Exception as exc:
        raise ReviveRefused(
            f"could not read bundle stage: {type(exc).__name__}: {exc}"
        ) from exc

    if stage is not None:
        try:
            StageState.from_dict(stage)
        except Exception as exc:
            raise ReviveRefused(
                f"bundle stage is invalid: {type(exc).__name__}: {exc}"
            ) from exc

    return RevivePlan(
        bundle=bundle,
        preservation_id=preservation_id,
        stage=stage,
    )


def apply_stage(plan: RevivePlan, stage_path: Path | None = None) -> bool:
    """Write the bundle's preserved stage to the stage file.

    Returns True when a stage was written, False when the bundle carries no
    stage (the existing stage file is left untouched in that case).
    """
    if plan.stage is None:
        log.info("bundle carries no stage; stage file left as is")
        return False

    target = stage_path
    if target is None:
        from kaine.lifecycle import stage as _stage_module

        target = _stage_module.STAGE_PATH

    state = StageState.from_dict(plan.stage)
    write_stage(state, target)
    return True


async def revive_into(plan: RevivePlan, registry: Any) -> list[str]:
    """Restore ``plan.bundle`` into ``registry`` and report new faculty.

    Raises :class:`ReviveRefused` if the revive itself fails.  Returns the
    sorted names of modules present in the registry that the snapshot did not
    capture.
    """
    try:
        snap = await _preservation.revive(plan.bundle, registry)
    except Exception as exc:
        # revive() wraps its own failures in ReviveError; anything else is
        # still a refused revive, never a half-restored individual that runs.
        raise ReviveRefused(f"{type(exc).__name__}: {exc}") from exc

    captured = set(snap.modules.keys())
    enabled = {m.name for m in registry.all_modules()}
    new_faculty = sorted(enabled - captured)

    for name in new_faculty:
        log.info("new faculty %s: starting fresh", name)

    return new_faculty


class ReviveSession:
    """A single operator revive session: stage write, rollback, and registry revive."""

    def __init__(self, plan: RevivePlan, stage_path: Path | None = None) -> None:
        self._plan = plan
        self._stage_path = stage_path
        self._target: Path | None = None
        self._prior_bytes: bytes | None = None
        self._wrote = False
        self._landed = False

    @property
    def plan(self) -> RevivePlan:
        return self._plan

    @property
    def landed(self) -> bool:
        return self._landed

    @property
    def revived_from(self) -> str:
        return self._plan.preservation_id or self._plan.bundle.name

    def apply(self) -> None:
        """Write the bundle's stage to the stage file, remembering prior bytes."""
        target = self._stage_path
        if target is None:
            from kaine.lifecycle import stage as _stage_module

            target = _stage_module.STAGE_PATH

        self._target = target
        self._prior_bytes = target.read_bytes() if target.exists() else None
        self._wrote = apply_stage(self._plan, target)

    async def revive(self, registry: Any) -> list[str]:
        """Revive the bundle into the registry and mark the session as landed."""
        new = await revive_into(self._plan, registry)
        self._landed = True
        return new

    def rollback(self) -> None:
        """Restore the stage file to its pre-apply bytes, or remove it.

        No-op once the revive has landed or when apply wrote nothing.
        Idempotent.
        """
        if self._landed or not self._wrote or self._target is None:
            return

        target = self._target
        try:
            if self._prior_bytes is None:
                if target.exists():
                    target.unlink()
                    log.warning(
                        "revive session: removed stage file %s (no prior stage existed)",
                        target,
                    )
            else:
                fd, tmp_path = tempfile.mkstemp(
                    dir=target.parent,
                    prefix=f"{target.stem}.",
                    suffix=target.suffix,
                )
                closed = False
                try:
                    os.write(fd, self._prior_bytes)
                    os.close(fd)
                    closed = True
                    os.replace(tmp_path, target)
                    log.warning(
                        "revive session: restored prior stage bytes to %s", target
                    )
                finally:
                    if not closed:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        finally:
            # Make rollback idempotent: the stage is no longer our responsibility.
            self._wrote = False
