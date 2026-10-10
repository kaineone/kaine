# SPDX-License-Identifier: LicenseRef-CAL-0.4
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
  4. ``await revive(bundle, registry)``, restore the bundle's individuation
     evidence, then write the bundle's stage to the stage file; only then has
     the revive landed.
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
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.lifecycle import preservation as _preservation
from kaine.lifecycle.identity import (
    EntityIdentity,
    IdentityError,
    check_sidecar_agrees,
    identity_of_snapshot,
    legacy_identity,
)
from kaine.lifecycle.preservation import read_bundle_stage
from kaine.lifecycle.snapshot import ForkSnapshot
from kaine.lifecycle.stage import StageState, write_stage
from kaine.storage import resolve

log = logging.getLogger(__name__)

REVIVE_REFUSED_EXIT = 7


class ReviveRefused(RuntimeError):
    """The bundle cannot be revived into this runtime."""


@dataclass(frozen=True)
class RevivePlan:
    bundle: Path
    preservation_id: str | None
    stage: dict | None
    # The being this bundle revives (entity-identity): the snapshot's own
    # identity, else the manifest's, else the deterministic legacy identity of
    # a bundle written before identities existed. Never freshly minted.
    identity: EntityIdentity


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
        except (json.JSONDecodeError, OSError) as exc:
            # The id is informational only; a stage read below still gates revival.
            log.debug("could not read preservation_id from %s: %s", manifest_path, exc)

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

    identity = _plan_identity(bundle, members, preservation_id)

    return RevivePlan(
        bundle=bundle,
        preservation_id=preservation_id,
        stage=stage,
        identity=identity,
    )


def _plan_identity(
    bundle: Path, members: dict, preservation_id: str | None
) -> EntityIdentity:
    """The identity a revive of ``bundle`` restores.

    The snapshot's identity (inside the possibly encrypted bundle) must agree
    with the plaintext manifest's. The snapshot's full identity wins; a bundle
    with only a manifest identity carries that ID; a bundle with neither, written
    before identities existed, gets ``legacy_identity("bundle:<preservation_id>")``.
    Raises :class:`ReviveRefused` before anything is written.
    """
    try:
        snap = ForkSnapshot.from_dict(json.loads(members["snapshot.json"]))
        snap_identity = identity_of_snapshot(snap)
        manifest_identity = _preservation._manifest_identity(bundle)
        check_sidecar_agrees(manifest_identity, snap_identity)
    except (IdentityError, ValueError) as exc:
        raise ReviveRefused(f"bundle identity is unreadable or inconsistent: {exc}") from exc
    if snap_identity is not None:
        return snap_identity
    if manifest_identity is not None:
        entity_id, lineage = manifest_identity
        legacy = entity_id.startswith("legacy-")
        if legacy and not preservation_id:
            raise ReviveRefused("bundle has a legacy identity but no preservation_id")
        try:
            return EntityIdentity(
                entity_id=entity_id,
                lineage=lineage,
                origin="legacy" if legacy else "minted",
                legacy_source=f"manifest:{preservation_id}" if legacy else None,
            )
        except IdentityError as exc:
            raise ReviveRefused(f"bundle identity is malformed: {exc}") from exc
    if not preservation_id:
        raise ReviveRefused(
            "bundle has no identity and no preservation_id; cannot derive a "
            "deterministic identity"
        )
    return legacy_identity(f"bundle:{preservation_id}")


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
    """A single operator revive session: in-memory stage, individuation
    evidence, and registry revive."""

    def __init__(
        self,
        plan: RevivePlan,
        stage_path: Path | None = None,
        individuation_root: Path | None = None,
    ) -> None:
        self._plan = plan
        self._stage_path = stage_path
        self._individuation_root = individuation_root
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

        # Restore individuation evidence before the stage file is written.
        try:
            target = self._individuation_root
            if target is None:
                from kaine.lifecycle.individuation_store import DEFAULT_ROOT

                target = resolve(DEFAULT_ROOT)
            target = Path(target)

            staging = target.with_name(target.name + ".revived")
            shutil.rmtree(staging, ignore_errors=True)

            try:
                restored = _preservation.extract_bundle_individuation(
                    self._plan.bundle, staging
                )
            except Exception as exc:
                # Extraction failure leaves the existing target untouched.
                shutil.rmtree(staging, ignore_errors=True)
                raise ReviveRefused(
                    f"could not extract individuation evidence from bundle: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            # The moved-aside tree is kept, never deleted: it may hold another
            # being's evidence, or this being's own if the restore is undone.
            replaced: Path | None = None

            def _replaced_name() -> str:
                return (
                    f"{target.name}.replaced-"
                    f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
                    f"-{uuid.uuid4().hex[:8]}"
                )

            if not restored:
                # The bundle carried no evidence. Any existing tree must not be
                # attributed to the revived being.
                if target.exists():
                    replaced = target.with_name(_replaced_name())
                    os.replace(target, replaced)
                    log.warning(
                        "revive: bundle carried no individuation evidence; "
                        "existing tree %s moved to %s so the revived being does "
                        "not inherit another being's evidence",
                        target,
                        replaced,
                    )
                else:
                    log.warning(
                        "revive: bundle carried no individuation evidence"
                    )
                log.info(
                    "revive: bundle carried no individuation evidence; a capture "
                    "reference will be taken at first boot"
                )
            else:
                if target.exists():
                    replaced = target.with_name(_replaced_name())
                    os.replace(target, replaced)
                    log.warning(
                        "revive: existing individuation tree %s moved to %s "
                        "before restore",
                        target,
                        replaced,
                    )
                try:
                    os.replace(staging, target)
                except OSError as exc:
                    # Best-effort rollback: restore the aside tree so the being
                    # is not left without evidence.
                    if replaced is not None and replaced.exists():
                        try:
                            os.replace(replaced, target)
                            log.warning(
                                "revive: os.replace(%s, %s) failed; rolled "
                                "back to the previous individuation tree",
                                staging,
                                target,
                            )
                        except OSError as rollback_exc:
                            log.error(
                                "revive: could not roll back aside tree %s to "
                                "%s after os.replace failure: %s",
                                replaced,
                                target,
                                rollback_exc,
                                exc_info=True,
                            )
                    raise ReviveRefused(
                        f"could not move restored individuation evidence into "
                        f"place: {type(exc).__name__}: {exc}"
                    ) from exc
        except ReviveRefused:
            raise
        except Exception as exc:
            raise ReviveRefused(
                f"could not restore individuation evidence: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if self._plan.stage is not None:
            target = self._stage_path
            if target is None:
                from kaine.lifecycle import stage as _stage_module

                target = _stage_module.STAGE_PATH

            # Gestation progress travels with the being (awake time persists across boots).
            try:
                _preservation.extract_bundle_gestation(self._plan.bundle, Path(target).parent)
            except Exception as exc:
                raise ReviveRefused(
                    f"could not restore gestation progress: {type(exc).__name__}: {exc}"
                ) from exc

            try:
                write_stage(StageState.from_dict(self._plan.stage), target)
            except Exception as exc:
                raise ReviveRefused(
                    f"could not write the stage file: {type(exc).__name__}: {exc}"
                ) from exc

        self._landed = True
        return new
