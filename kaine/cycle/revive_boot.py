# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator revive boot helpers.

The operator revive order is:

  1. Parse ``--revive <bundle>``. Read the bundle's members.
  2. If the bundle carries ``stage.json``, its stage is handed to
     ``_resolve_boot_stage`` in memory, so gestation, the womb hold, the womb
     clock and the gate all see the preserved stage. The stage file is NOT
     written yet. A bundle without a stage member resolves the stage from the
     stage file as today and logs that.
  3. Build the registry and initialise the modules.
  4. ``await revive(bundle, registry)``, then write the bundle's stage to the
     stage file; only then has the revive landed.
  5. Log any modules enabled now but not captured by the bundle as "new
     faculty, starting fresh".
  6. Start the cycle, recording ``revived_from`` in ``runtime.json`` and the
     run context.

Module initialisation happens before revive because Eidolon's ``initialize()``
reloads its disk file; a revive before it would be overwritten. Background
loops started during ``initialize()`` run briefly on fresh state before the
revive lands, but the cognitive cycle (and so the workspace) has not started,
so this is safe. This is the same order the research gate's self-check already
relies on. A crash or interruption before the stage file is written leaves the
stage file exactly as it was; running the same revive again completes it.
"""
from __future__ import annotations

import json
import logging
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
    """A single operator revive session: in-memory stage and registry revive."""

    def __init__(self, plan: RevivePlan, stage_path: Path | None = None) -> None:
        self._plan = plan
        self._stage_path = stage_path
        self._landed = False

    @property
    def plan(self) -> RevivePlan:
        return self._plan

    @property
    def stage_state(self) -> StageState | None:
        """The bundle's preserved stage, if any, validated but not yet written."""
        if self._plan.stage is None:
            return None
        return StageState.from_dict(self._plan.stage)

    @property
    def landed(self) -> bool:
        return self._landed

    @property
    def revived_from(self) -> str:
        return self._plan.preservation_id or self._plan.bundle.name

    async def revive(self, registry: Any) -> list[str]:
        """Revive the bundle into ``registry`` and write the stage on success.

        Raises :class:`ReviveRefused` if the revive itself fails or if the
        stage file cannot be written. Only once both the registry revive and
        the stage write succeed is the session considered landed.
        """
        new = await revive_into(self._plan, registry)

        if self._plan.stage is not None:
            target = self._stage_path
            if target is None:
                from kaine.lifecycle import stage as _stage_module

                target = _stage_module.STAGE_PATH

            try:
                write_stage(StageState.from_dict(self._plan.stage), target)
            except Exception as exc:
                raise ReviveRefused(
                    f"could not write the stage file: {type(exc).__name__}: {exc}"
                ) from exc

        self._landed = True
        return new
