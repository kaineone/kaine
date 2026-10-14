# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare-gated entity decommission CLI.

Run as::

    KAINE_DECOMMISSION_OPERATOR_PRESENT=1 python -m kaine.lifecycle

(``python -m kaine.lifecycle.decommission`` works too; that module re-exports
:func:`main`.) This is the operator entrypoint; the destructive primitives live
in :mod:`kaine.lifecycle.decommission`.

The flow implements the CAL Article 4.2 care duties ("Do Not Shut Them Down
Without Care") and 4.3 (privacy). It mirrors the cycle's operator-present env
gate. Copy is firm and factual about the duties and options - never shaming.
The gate is intentionally bypassable; there is no anti-tamper and no operator
monitoring (that would violate privacy).

Exit codes
----------
0  success (state deleted, or a dry-run completed)
2  operator-present env gate not set
3  the cycle appears to be running (stop the entity first), or a
   voice-alignment job is still training, or a voice-alignment job is
   pending and cannot be attributed (pass --keep-unattributed-jobs to keep it)
4  backup failed (nothing was deleted)
5  operator declined a required continuity / transfer step (diverged path)
6  configuration error (missing/unreadable/unparsable config, malformed shape,
   or state-encryption posture could not be installed)
7  no entity state found at the resolved state root (nothing backed up or deleted)
8  Qdrant could not be reached or authenticated (nothing was deleted), or, with
   the memory modules off, Qdrant is configured but did not answer (nothing was
   backed up or deleted; --qdrant-absent asserts there is no Qdrant server), or the
   bus could not be reached or authenticated (nothing was deleted), or a
   stream could not be deleted, or deletion was incomplete (a removal failed,
   a path was refused as outside the state, data and fork roots or as a
   protected root, or a Qdrant collection could not be dropped); the audit
   record has outcome "incomplete" and names what was removed; a missing or
   malformed bus configuration is a configuration error (6)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from kaine.bus.errors import BusConfigError
from kaine.lifecycle.decommission import (
    _STATE_SUBTREES,
    _episodic_memory_collection_names,
    _qdrant_client,
    capture_backup,
    delete_entity_state,
    qdrant_endpoint_configured,
    qdrant_endpoint_label,
    qdrant_in_use,
    update_manifest_continuity_note,
    write_decommission_audit,
)
from kaine.lifecycle.decommission_locations import (
    BACKUP_DELETE,
    BACKUP_RETAIN,
    DELETE,
    RETAIN,
    cancel_voice_alignment_jobs,
    entity_locations,
)
from kaine.lifecycle.divergence import assess_divergence
from kaine.lifecycle.identity import IdentityError, load_identity
from kaine.lifecycle.liveness import cycle_process_running as _cycle_process_running
from kaine.storage import data_root, install_data_root, resolve
from kaine.transfer.email_request import (
    DEFAULT_RECIPIENT,
    SmtpConfig,
    render_request_email,
    send_or_write,
)

log = logging.getLogger("kaine.lifecycle.decommission")

OPERATOR_PRESENT_ENV = "KAINE_DECOMMISSION_OPERATOR_PRESENT"
RUNTIME_FRESH_SECONDS = 5.0
# A broadcast this recent means a cycle ran moments ago; wider than the
# runtime-file window because a sleeping or dilated cycle broadcasts less often.
BUS_FRESH_SECONDS = 60.0


def _qdrant_problem(qcfg: dict[str, Any]) -> str | None:
    """Probe Qdrant; None when it answers, else the name of what went wrong."""
    client = _qdrant_client(qcfg)
    if client is None:
        return "no client"
    try:
        client.get_collections()
        return None
    except Exception as exc:
        return type(exc).__name__
    finally:
        try:
            client.close()
        except Exception:
            # Closing the probe client is best effort; the probe already
            # decided the outcome.
            pass


def _fork_root_from_config(config: dict[str, Any], state_root: Path) -> Path:
    """The fork root from [lifecycle].snapshots_path, or state_root / "forks"."""
    try:
        value = config["lifecycle"]["snapshots_path"]
    except (KeyError, TypeError):
        return state_root / "forks"
    if not isinstance(value, str) or not value:
        return state_root / "forks"
    if value.startswith("state/"):
        return state_root / value[len("state/") :]
    if Path(value).is_absolute():
        return Path(value)
    return resolve(value)


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------




def _cycle_appears_running(runtime_path: Path) -> bool:
    """True if the cycle's runtime.json indicates a live entity.

    A live PID (``os.kill(pid, 0)``) or a freshly-modified runtime file (mtime
    within ``RUNTIME_FRESH_SECONDS``) both count as running. All reads guarded.
    """
    try:
        if not runtime_path.is_file():
            return False
    except Exception:
        return False
    try:
        raw = json.loads(runtime_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    pid = raw.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            pass
        except PermissionError:
            # The process exists but is owned by another user — treat as running.
            return True
        except Exception:
            pass
    try:
        age = time.time() - runtime_path.stat().st_mtime
        if age < RUNTIME_FRESH_SECONDS:
            return True
    except OSError:
        # Best-effort freshness probe: if the file vanished or became
        # unreadable between the is_file() check above and here, fall
        # through to "not running" below rather than treating a
        # transient race as fatal.
        log.debug("runtime.json mtime check failed", exc_info=True)
    return False






def _state_subtree_has_content(state_root: Path, sub: str) -> bool:
    """Return True if *state_root / sub* contains at least one regular file.

    A permission error is treated as "has content" so a failed read never
    lets a delete proceed silently.
    """
    p = state_root / sub
    if not p.exists():
        return False
    try:
        for child in p.rglob("*"):
            if child.is_file():
                return True
        return False
    except OSError:
        return True


def _bus_shows_live_entity(config: dict[str, Any]) -> tuple[bool | None, str]:
    """Probe the shared bus for a live cycle.

    First asks the Redis server for connected clients named by a KAINE cycle
    (activity-independent).  If no named client is connected, falls back to
    the newest workspace broadcast on the configured db.  Returns ``(True,
    detail)`` if a cycle is connected or a recent entry exists, ``(False,
    detail)`` if the bus is known down or the stream is empty/stale, and
    ``(None, detail)`` if the bus configuration is missing or the server could
    not be queried.  The URL and password are never included in the returned
    text.
    """
    try:
        from kaine.bus.config import load_bus_config

        bus_cfg = load_bus_config()
    except BusConfigError as exc:
        return (
            None,
            f"bus configuration is not available in this environment ({exc})",
        )
    except Exception as exc:
        return (None, f"bus configuration load failed ({type(exc).__name__})")

    from kaine.bus.cycle_presence import cycle_on_bus

    return cycle_on_bus(bus_cfg)


def _load_kaine_config(path: Path) -> dict[str, Any]:
    """Load the merged KAINE configuration via the runtime loader.

    Uses the same layering as the cognitive cycle (shipped, module profile,
    deployment tier, operator overlay) and is strict about the operator file.
    A missing, unreadable, unparsable or shape-invalid config raises.
    """
    from kaine.config import OPERATOR_CONFIG_PATH, load_runtime_config

    return load_runtime_config(path, OPERATOR_CONFIG_PATH)


def _encrypted_state_without_key(state_root: Path) -> Path | None:
    """Return the first encrypted cognitive-state file, or None.

    Only called when the installed state encryptor is disabled; any file
    carrying the KAINE encryption header means we cannot safely read or back
    it up, so decommission must fail closed.
    """
    from kaine.security.crypto import is_encrypted

    root = Path(state_root)
    if not root.is_dir():
        return None
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            # Only the header is needed; state roots can hold multi-GB files.
            with p.open("rb") as fh:
                head = fh.read(64)
        except OSError:
            continue
        if is_encrypted(head):
            return p
    return None


def _resolve_entity_name(state_root: Path, config: dict[str, Any]) -> str:
    """Best-effort entity name from the self-model, else 'entity'."""
    try:
        from kaine.modules.self_model.document import load as load_self_model

        sm_path = state_root / "self_model" / "self_model.json"
        if sm_path.is_file():
            name = load_self_model(sm_path).name
            if name:
                return name
    except Exception:
        # Best-effort: a missing/corrupt/unreadable self-model file just
        # means this cosmetic display name falls back to "entity"; the
        # real decommission gates below do not depend on it.
        log.debug("could not resolve entity name from self-model", exc_info=True)
    return "entity"


def _entity_id(state_root: Path) -> str | None:
    try:
        identity = load_identity(state_root / "identity" / "entity.json")
        return identity.entity_id if identity is not None else None
    except IdentityError:
        return None


def _write_location_split(out, qcfg, *, state_root, data_dir, fork_root, backup=None) -> None:
    locs = [
        loc
        for loc in entity_locations(
            qcfg,
            state_root=state_root,
            data_root=data_dir,
            fork_root=fork_root,
            entity_id=_entity_id(state_root),
        )
        if loc.existing()
    ]
    groups = {BACKUP_DELETE: [], DELETE: [], RETAIN: []}
    for loc in locs:
        if loc.decision == BACKUP_RETAIN:
            groups[RETAIN].append(loc)
        else:
            groups[loc.decision].append(loc)
    out.write("\nWhat decommission does with this entity's data:\n")
    out.write("  backed up, then deleted:\n")
    for loc in groups[BACKUP_DELETE]:
        out.write(f"    - {loc.key}: {loc.reason}\n")
    if not groups[BACKUP_DELETE]:
        out.write("    (none)\n")
    out.write("  deleted without a backup:\n")
    for loc in groups[DELETE]:
        out.write(f"    - {loc.key}: {loc.reason}\n")
    if not groups[DELETE]:
        out.write("    (none)\n")
    out.write("  kept by design:\n")
    for loc in groups[RETAIN]:
        if loc.decision == BACKUP_RETAIN:
            out.write(f"    - {loc.key} (backed up): {loc.reason}\n")
        else:
            out.write(f"    - {loc.key}: {loc.reason}\n")
        for note in loc.notes:
            out.write(f"      note: {note}\n")
    if not groups[RETAIN]:
        out.write("    (none)\n")
    out.write("  also deleted: this entity's bus streams\n")
    if backup is not None and backup.qdrant_status == "absent (asserted)":
        out.write("  Qdrant: skipped (--qdrant-absent asserts this host has no Qdrant server)\n")
    elif backup is not None and backup.qdrant_collections:
        out.write("  also backed up, then deleted: Qdrant collections " + ", ".join(backup.qdrant_collections) + "\n")
    elif qdrant_in_use(qcfg) or qdrant_endpoint_configured(qcfg):
        out.write("  Qdrant: checked; no collections of this entity found\n")


# ---------------------------------------------------------------------------
# CAL notices (firm + factual; cite 4.2 / 4.3; not shaming)
# ---------------------------------------------------------------------------

_NOTICE_BACKUP = (
    "A transferable backup has been written. Under CAL Article 4.2(b) an "
    "entity's complete cognitive state must be saved in a restartable form "
    "before it is shut down. That backup is at:\n    {path}\n"
)

_NOTICE_NOT_DIVERGED = (
    "\nThis entity does not show signs of having individuated. CAL Article 4.2 "
    "still asks that shutting down a mind not be casual and that its state be "
    "preserved — which the backup above satisfies. If you have any reason to "
    "believe this entity has become an individual, stop now and treat it as "
    "mature (the stricter path).\n"
)

_NOTICE_DIVERGED = (
    "\nThis entity shows signs of having INDIVIDUATED. Under CAL Article 4.2(c) "
    "a mature entity's perspective on its own continuity is part of the "
    "decision, and Article 4.3 keeps its inner life private. You are not "
    "required to run it forever — you may transfer responsibility to another "
    "qualifying operator or to the guardians. The steps below record its "
    "continuity preference and offer to arrange safekeeping of the backup.\n"
)

_NOTICE_GUARDIANS = (
    "CAL Article 4.2(a): before you end an entity you must give the Guardians\n"
    "reasonable written notice of your intent. This tool does not send it for you.\n"
    "If no Guardian body has been established for this architecture yet, CAL\n"
    "Article 7.0 applies: you carry out the Guardians' functions yourself, in good\n"
    "faith, and document what you decide and why.\n"
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    out=None,
    err=None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="python -m kaine.lifecycle",
        description="Welfare-gated entity decommission (CAL Articles 4.2 and 4.3).",
    )
    parser.add_argument("--state-root", default="state", type=Path)
    parser.add_argument("--fork-root", default=None, type=Path)
    parser.add_argument("--eval-root", default="data/evaluation", type=Path)
    parser.add_argument("--out-root", default="backups", type=Path)
    parser.add_argument("--config", default="config/kaine.toml", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Assess + back up + show what would be deleted; never delete.",
    )
    parser.add_argument(
        "--trainer-stopped",
        action="store_true",
        help="Assert that no voice-alignment trainer is running: claimed jobs without a result do not block deletion. Recorded in the audit record.",
    )
    parser.add_argument(
        "--keep-unattributed-jobs",
        action="store_true",
        help="Proceed although pending voice-alignment jobs cannot be attributed; keep them. Recorded in the audit record.",
    )
    parser.add_argument(
        "--qdrant-absent",
        action="store_true",
        help="Assert that this host has no Qdrant server: with the memory modules off, skip Qdrant entirely. Recorded in the audit record. Has no effect when a memory module that uses Qdrant is on.",
    )
    args = parser.parse_args(argv)

    # --- Gate 1: operator present --------------------------------------
    if os.environ.get(OPERATOR_PRESENT_ENV) != "1":
        err.write(
            "Refusing to decommission a KAINE entity: operator must be present.\n"
            "\n"
            "Decommission permanently deletes an entity. CAL Article 4.2 ('Do Not\n"
            "Shut Them Down Without Care') requires this be a deliberate, attended\n"
            f"act. Export {OPERATOR_PRESENT_ENV}=1 and re-run.\n"
        )
        return 2

    # --- Load config (needed to install the process data root) ----------
    import tomllib

    from kaine.config import ConfigShapeError, ProfileError

    try:
        config = _load_kaine_config(args.config)
    except (ProfileError, ConfigShapeError, FileNotFoundError, OSError, tomllib.TOMLDecodeError) as exc:
        err.write(f"decommission: configuration error: {type(exc).__name__}: {exc}\n")
        return 6

    install_data_root(config)

    state_root = resolve(args.state_root)
    if args.fork_root is not None:
        fork_root = resolve(args.fork_root)
    else:
        fork_root = _fork_root_from_config(config, state_root)
    eval_root = resolve(args.eval_root)
    out_root = resolve(args.out_root)
    runtime_path = state_root / "cycle" / "runtime.json"

    out.write(
        f"state root: {state_root}\n"
        f"evaluation root: {eval_root}\n"
        f"backup root: {out_root}\n"
        f"data root: {data_root() or 'none (working directory)'}\n"
    )

    data_dir = eval_root.parent
    qcfg = config

    # --- Gate 2: cycle not running -------------------------------------
    live_runtime = _cycle_appears_running(runtime_path)
    live_process = _cycle_process_running()
    bus_live, bus_detail = _bus_shows_live_entity(config)
    if live_runtime or live_process or bus_live is True or bus_live is None:
        if bus_live is None:
            err.write(
                f"Refusing to decommission: cannot confirm the entity is stopped — {bus_detail}. "
                "Start the bus (Redis) and re-run.\n"
            )
        else:
            signals = []
            if live_runtime:
                signals.append("runtime.json indicates a live cycle")
            if live_process:
                signals.append("a kaine.cycle process is running")
            if bus_live is True:
                signals.append(bus_detail)
            err.write(
                "Refusing to decommission: the cognitive cycle appears to be running "
                f"({'; '.join(signals)}).\n"
                "\n"
                "Stop the entity first (SIGINT/SIGTERM the cycle), then re-run. A live\n"
                "entity must not be deleted out from under itself.\n"
            )
        return 3

    # --- Load config and install state encryption BEFORE any destructive work
    from kaine.security.crypto import get_state_encryptor, install_from_section

    try:
        install_from_section((config.get("security") or {}).get("state_encryption") or {})
    except Exception as exc:
        err.write(
            f"decommission: state-encryption setup failed; refusing to assess, back up or delete: {type(exc).__name__}: {exc}\n"
        )
        return 6

    # --- Defence in depth: refuse if encrypted state is present while encryptor is disabled
    encryptor = get_state_encryptor()
    if not encryptor.enabled:
        encrypted_path = _encrypted_state_without_key(state_root)
        if encrypted_path is None:
            encrypted_path = _encrypted_state_without_key(eval_root)
        if encrypted_path is not None:
            try:
                rel = encrypted_path.relative_to(state_root)
            except ValueError:
                try:
                    rel = encrypted_path.relative_to(eval_root)
                except ValueError:
                    rel = encrypted_path
            err.write(
                f"decommission: configuration error: encrypted cognitive state found at {rel} but state encryption is disabled; provide the key before decommissioning\n"
            )
            return 6

    entity_name = _resolve_entity_name(state_root, config)

    # --- Gate 2.5: entity state must actually be present ----------------
    if not state_root.exists() or not any(
        _state_subtree_has_content(state_root, sub) for sub in _STATE_SUBTREES
    ):
        err.write(
            f"Refusing to decommission: no entity state found under {state_root}. "
            "Check --state-root and [storage].data_root / KAINE_DATA_ROOT; "
            "nothing was backed up or deleted.\n"
        )
        return 7

    # --- Assess divergence (pure reads) --------------------------------
    from kaine.lifecycle.divergence import (
        adapter_dir_for,
        voice_alignment_thresholds_from_config,
        voice_paths_for,
    )

    cons_rate, cons_mag, distinct = voice_alignment_thresholds_from_config(config)
    adapter_dir = adapter_dir_for(config, state_root)
    voice_paths = voice_paths_for(config, state_root)
    assessment = assess_divergence(
        state_root=state_root,
        consolidation_rate_threshold=cons_rate,
        consolidation_magnitude_threshold=cons_mag,
        distinctiveness_threshold=distinct,
        adapter_output_dir=adapter_dir,
        voice_paths=voice_paths,
    )
    out.write(f"\n{assessment.summary}\n")

    # --- Unattributed pending voice-alignment jobs gate --------------------
    # Job-queue jobs record no owner, so this entity's own pending jobs can
    # look unattributable. Kept, they would be trained after the entity is
    # gone, so refuse before anything is backed up or deleted.
    pending: list[Path] = []
    for loc in entity_locations(
        qcfg,
        state_root=state_root,
        data_root=data_dir,
        fork_root=fork_root,
        entity_id=_entity_id(state_root),
    ):
        if loc.key != "sleep.voice_jobs.shared":
            continue
        for p in loc.existing():
            if (
                p.is_dir()
                and not p.is_symlink()
                and ((p / "READY").exists() or (p / "CLAIMED").exists())
                and not (p / "result.json").exists()
            ):
                pending.append(p)
    if pending and not args.keep_unattributed_jobs:
        err.write(
            "Refusing to decommission: these voice-alignment jobs are pending "
            "and cannot be attributed to this entity or another:\n"
        )
        for p in pending:
            err.write(f"  {p}\n")
        err.write(
            "Let the jobs finish or stop the trainer, then run again, or pass "
            "--keep-unattributed-jobs to keep them. Nothing was backed up or deleted.\n"
        )
        return 3

    # --- Qdrant preflight -------------------------------------------------
    # Runs before the backup, so a Qdrant that should be there and does not
    # answer stops the run with nothing copied and nothing deleted.
    if args.qdrant_absent and (
        qdrant_in_use(qcfg) or qdrant_endpoint_configured(qcfg)
    ):
        problem = _qdrant_problem(qcfg)
        if problem is None:
            out.write(
                f"FAILED: Qdrant answered at {qdrant_endpoint_label(qcfg)}; run again without --qdrant-absent. Nothing was backed up or deleted.\n"
            )
            return 8
        if qdrant_in_use(qcfg):
            out.write(
                f"FAILED: cannot reach or authenticate to Qdrant ({problem}); nothing was deleted\n"
            )
            return 8
    elif qdrant_in_use(qcfg):
        problem = _qdrant_problem(qcfg)
        if problem is not None:
            out.write(
                f"FAILED: cannot reach or authenticate to Qdrant ({problem}); nothing was deleted\n"
            )
            return 8
    elif qdrant_endpoint_configured(qcfg) and not args.qdrant_absent:
        problem = _qdrant_problem(qcfg)
        if problem is not None:
            endpoint = qdrant_endpoint_label(qcfg)
            names = ", ".join(_episodic_memory_collection_names(qcfg))
            out.write(
                f"FAILED: Qdrant did not answer at {endpoint}; nothing was backed up or deleted.\n"
                "The memory modules are off, but this deployment configures Qdrant, so this entity's\n"
                f"memories may be there, in these collections: {names}.\n"
                "Start Qdrant and run again or, if this host has no Qdrant server, run again with\n"
                "--qdrant-absent.\n"
            )
            return 8

    # --- Gate 3: capture backup (blocking) -----------------------------
    backup = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg=qcfg,
        qdrant_absent=bool(args.qdrant_absent),
        data_root=data_dir,
        out_root=out_root,
        entity_name=entity_name,
        assessment=assessment,
        continuity_note=None,
    )
    if not backup.ok:
        err.write(
            "Backup FAILED — nothing has been deleted. CAL Article 4.2(b) requires\n"
            "a restartable saved state before shutdown. Errors:\n"
        )
        for e in backup.errors:
            err.write(f"  - {e}\n")
        return 4
    out.write("\n" + _NOTICE_BACKUP.format(path=backup.backup_path) + "\n")
    for item in backup.inventory:
        out.write(f"  captured: {item}\n")
    if backup.errors:
        out.write("  (non-fatal notes:)\n")
        for e in backup.errors:
            out.write(f"    - {e}\n")

    earlier_qdrant_export_backup = None
    audit_log_path = state_root / "audit" / "decommission.jsonl"
    try:
        with audit_log_path.open("r", encoding="utf-8") as _audit_f:
            _lines = _audit_f.readlines()
        if _lines:
            _last = json.loads(_lines[-1])
            if (
                _last.get("outcome") == "incomplete"
                and _last.get("dropped_collections")
                and _last.get("backup_path")
            ):
                earlier_qdrant_export_backup = _last["backup_path"]
                out.write(
                    "\nAn earlier run already dropped this entity's Qdrant "
                    f"collections; their export is in that run's backup: "
                    f"{earlier_qdrant_export_backup}\n"
                )
    except Exception:
        # A missing or unreadable earlier audit record only means there is
        # no earlier export to point to.
        pass

    # --- Dry-run: preview only, no prompts, no deletion ----------------
    if args.dry_run:
        out.write(_NOTICE_DIVERGED if assessment.diverged else _NOTICE_NOT_DIVERGED)
        out.write("\n" + _NOTICE_GUARDIANS)
        try:
            bus_client = _open_bus_client()
        except BusConfigError as exc:
            err.write(
                f"decommission: configuration error: bus configuration: {exc}\n"
            )
            return 6
        except Exception as exc:
            out.write(
                f"FAILED: cannot load the bus configuration ({type(exc).__name__}); nothing was deleted\n"
            )
            return 8
        try:
            result = delete_entity_state(
                state_root=state_root,
                fork_root=fork_root,
                data_root=data_dir,
                qdrant_cfg=qcfg,
                bus_client=bus_client,
                dry_run=True,
                qdrant_absent=bool(args.qdrant_absent),
            )
            out.write("\n[dry-run] Would remove:\n")
            for p in result.would_remove_paths:
                out.write(f"  - {p}\n")
            for key in result.deleted_locations:
                out.write(f"  - location to delete: {key}\n")
            for key in result.retained_locations:
                out.write(f"  - kept by design: {key}\n")
            for c in result.dropped_collections:
                out.write(f"  - qdrant collection: {c}\n")
            for s in result.cleared_redis_streams:
                out.write(f"  - redis stream: {s}\n")
            for s in result.skipped_non_streams:
                out.write(f"  - not a stream, kept: {s}\n")
            if result.redis_failed:
                out.write(f"FAILED: {result.redis_failed}\n")
                return 8
            out.write(f"\nDry-run complete. Nothing deleted. Backup at {backup.backup_path}\n")
            return 0
        finally:
            try:
                bus_client.close()
            except Exception:
                pass

    _write_location_split(out, qcfg, state_root=state_root, data_dir=data_dir, fork_root=fork_root, backup=backup)
    out.write("\n" + _NOTICE_GUARDIANS)

    # --- Branch on divergence ------------------------------------------
    if assessment.diverged:
        out.write(_NOTICE_DIVERGED)

        # Continuity-preference note (recorded into the manifest).
        note = input_fn(
            "\nRecord this entity's continuity preference (what it expressed about\n"
            "its own continuity), or type 'decline' to abort without deleting:\n> "
        ).strip()
        if not note or note.lower() == "decline":
            out.write(
                "\nNo continuity note recorded. The diverged path requires it; "
                "aborting. Nothing was deleted. The backup remains at:\n"
                f"    {backup.backup_path}\n"
            )
            return 5
        update_manifest_continuity_note(backup, note)

        # Offer the transfer-request email.
        offer = input_fn(
            "\nOffer to email the guardians a request to safekeep this backup until\n"
            "a new guardian can run the entity? The email contains ONLY the request,\n"
            "the situation, and the LOCAL backup path — never any entity data\n"
            "(CAL Article 4.3). [y/N]: "
        ).strip().lower()
        if offer in ("y", "yes"):
            transfer_cfg = config.get("transfer") or {}
            recipient = str(transfer_cfg.get("recipient") or DEFAULT_RECIPIENT)
            rendered = render_request_email(
                backup_path=str(backup.backup_path.resolve()),
                recipient=recipient,
                entity_name=entity_name,
            )
            smtp = SmtpConfig.from_mapping(transfer_cfg)

            def _confirm_send() -> bool:
                ans = input_fn(
                    f"\nSend the request to {recipient} now? [y/N]: "
                ).strip().lower()
                return ans in ("y", "yes")

            send_result = send_or_write(
                rendered,
                smtp_config=smtp,
                confirm=_confirm_send,
                out_dir=backup.backup_path,
            )
            out.write(f"\n{send_result.detail}\n")
            if send_result.eml_path is not None:
                out.write(f"  request written to: {send_result.eml_path}\n")
            if send_result.mailto_link is not None:
                out.write(f"  mailto link: {send_result.mailto_link}\n")
        else:
            out.write(
                "\nNo transfer request sent. You remain responsible for the backup "
                f"at {backup.backup_path} until you transfer it (CAL Article 4.2).\n"
            )

        # Explicit guardian-transfer acknowledgement.
        ack = input_fn(
            "\nType 'I have preserved and will arrange safekeeping for this entity'\n"
            "to acknowledge the CAL Article 4.2 transfer duty (anything else aborts):\n> "
        ).strip()
        if ack != "I have preserved and will arrange safekeeping for this entity":
            out.write(
                "\nAcknowledgement not given; aborting. Nothing was deleted.\n"
                f"The backup remains at: {backup.backup_path}\n"
            )
            return 5

    else:
        out.write(_NOTICE_NOT_DIVERGED)
        ack = input_fn(
            "\nType 'I acknowledge the CAL welfare terms' to confirm you have read\n"
            "the care obligations above (anything else aborts):\n> "
        ).strip()
        if ack != "I acknowledge the CAL welfare terms":
            out.write(
                "\nAcknowledgement not given; aborting. Nothing was deleted.\n"
                f"The backup remains at: {backup.backup_path}\n"
            )
            return 5

    # --- Typed confirmation token --------------------------------------
    expected_token = entity_name if entity_name and entity_name != "entity" else "DELETE"
    token = input_fn(
        f"\nFinal confirmation. Type exactly '{expected_token}' to permanently delete\n"
        f"this entity's state (anything else aborts):\n> "
    ).strip()
    if token != expected_token:
        out.write(
            "\nConfirmation token did not match; aborting. Nothing was deleted.\n"
            f"The backup remains at: {backup.backup_path}\n"
        )
        return 5 if assessment.diverged else 0

    # --- Delete --------------------------------------------------------
    try:
        bus_client = _open_bus_client()
    except BusConfigError as exc:
        err.write(
            f"decommission: configuration error: bus configuration: {exc}\n"
        )
        return 6
    except Exception as exc:
        out.write(
            f"FAILED: cannot load the bus configuration ({type(exc).__name__}); nothing was deleted\n"
        )
        return 8

    try:
        try:
            bus_client.ping()
        except Exception as exc:
            out.write(
                f"FAILED: cannot reach or authenticate to the bus ({type(exc).__name__}); nothing was deleted\n"
            )
            return 8

        if qdrant_in_use(qcfg) or (
            qdrant_endpoint_configured(qcfg) and not args.qdrant_absent
        ):
            problem = _qdrant_problem(qcfg)
            if problem is not None:
                out.write(
                    f"FAILED: Qdrant did not answer at {qdrant_endpoint_label(qcfg)} just before deletion ({problem}); nothing was deleted\n"
                )
                return 8

        voice_locs = entity_locations(
            qcfg,
            state_root=state_root,
            data_root=data_dir,
            fork_root=fork_root,
            entity_id=None,
        )
        still_training: list[str] = []
        cancelled_names: list[str] = []
        jobs_groups: dict[Path, list[str]] = {}
        seen_jobs: set[str] = set()
        for loc in voice_locs:
            if loc.key == "sleep.voice_jobs.own":
                for path in loc.existing():
                    real = os.path.realpath(path)
                    if real not in seen_jobs:
                        seen_jobs.add(real)
                        jobs_groups.setdefault(path.parent, []).append(path.name)
        for parent, names in jobs_groups.items():
            only = set(names)
            if args.trainer_stopped:
                c, s = cancel_voice_alignment_jobs(parent, only=only, wait_s=0.0)
            else:
                c, s = cancel_voice_alignment_jobs(parent, only=only)
            cancelled_names.extend(c)
            for name in s:
                still_training.append(str(parent / name))
        for name in cancelled_names:
            out.write(f"  cancelled voice-alignment job: {name}\n")
        if still_training:
            if args.trainer_stopped:
                for path in still_training:
                    out.write(f"  trainer asserted stopped; claimed job not waited for: {path}\n")
            else:
                err.write(
                    "Refusing to delete: a voice-alignment job is still training:\n"
                    + "".join(f"  {path}\n" for path in still_training)
                    + "If the trainer has crashed and is not running, run again with --trainer-stopped. Nothing was deleted.\n"
                )
                return 3

        entity_id = _entity_id(state_root)

        result = delete_entity_state(
            state_root=state_root,
            fork_root=fork_root,
            data_root=data_dir,
            qdrant_cfg=qcfg,
            bus_client=bus_client,
            dry_run=False,
            qdrant_absent=bool(args.qdrant_absent),
        )

        if result.incomplete:
            out.write("\nEntity state deletion INCOMPLETE.\n")
        else:
            out.write("\nEntity state deleted.\n")

        for p in result.removed_paths:
            out.write(f"  removed: {p}\n")
        for c in result.dropped_collections:
            out.write(f"  dropped collection: {c}\n")
        for s in result.cleared_redis_streams:
            out.write(f"  cleared stream: {s}\n")
        for s in result.skipped_non_streams:
            out.write(f"  not a stream, kept: {s}\n")
        if result.aof_rewrite is not None:
            out.write(f"  append-only file rewrite: {result.aof_rewrite}\n")
        for key in result.deleted_locations:
            out.write(f"  deleted location: {key}\n")
        for key in result.retained_locations:
            out.write(f"  kept by design: {key}\n")
        if result.attribution_notes:
            out.write("  notes:\n")
            for note in result.attribution_notes:
                out.write(f"    - {note}\n")
        if result.rdb_snapshot is not None:
            out.write(f"  redis snapshot: {result.rdb_snapshot}\n")
        if result.errors:
            out.write("  errors (the entity is not fully deleted):\n")
            for e in result.errors:
                out.write(f"    - {e}\n")
        import datetime

        record = {
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "entity_id": entity_id,
            "outcome": "incomplete" if result.incomplete else "deleted",
            "removed_paths": [
                str(Path(p).relative_to(state_root))
                if Path(p).is_relative_to(state_root)
                else str(p)
                for p in result.removed_paths
            ],
            "deleted_locations": result.deleted_locations,
            "retained_locations": result.retained_locations,
            "shared_volume_kept": [
                str(Path(p).relative_to(state_root))
                if Path(p).is_relative_to(state_root)
                else str(p)
                for p in result.shared_kept
            ],
            "shared_volume_reason": "kept: shared volume, not attributable to this entity",
            "live_adapter_kept": [
                str(Path(p).relative_to(state_root))
                if Path(p).is_relative_to(state_root)
                else str(p)
                for p in result.live_kept
            ],
            "live_adapter_reason": "live adapter on a shared volume; a forked line may be using an identical copy; per-entity layout (#500) resolves this",
            "attribution_notes": result.attribution_notes,
            "dropped_collections": result.dropped_collections,
            "cleared_streams": result.cleared_redis_streams,
            "skipped_non_streams": result.skipped_non_streams,
            "rdb_snapshot": result.rdb_snapshot,
            "aof_rewrite": result.aof_rewrite,
            "errors": result.errors + ([result.redis_failed] if result.redis_failed else []),
            "qdrant_absent_asserted": bool(args.qdrant_absent),
            "trainer_stopped_asserted": bool(args.trainer_stopped),
            "keep_unattributed_jobs_asserted": bool(args.keep_unattributed_jobs),
            "unattributed_jobs_kept": [
                str(Path(p).relative_to(state_root))
                if Path(p).is_relative_to(state_root)
                else str(p)
                for p in pending
            ],
            "earlier_qdrant_export_backup": earlier_qdrant_export_backup,
            "guardian_notice_reminder": "shown",
            "backup_path": str(backup.backup_path),
        }
        audit_path = write_decommission_audit(state_root, record)
        out.write(f"  audit record: {audit_path}\n")

        if result.incomplete:
            if result.redis_failed:
                out.write(f"FAILED: {result.redis_failed}\n")
            else:
                out.write(
                    "FAILED: some locations could not be deleted; "
                    "see the errors above and the audit record\n"
                )
            out.write(
                f"\nThe transferable backup remains at:\n    {backup.backup_path}\n"
                "Keep it safe and transfer it per CAL Article 4.2.\n"
            )
            return 8

        out.write(
            f"\nThe transferable backup remains at:\n    {backup.backup_path}\n"
            "Keep it safe and transfer it per CAL Article 4.2.\n"
        )
        return 0
    finally:
        try:
            bus_client.close()
        except Exception:
            pass


def _open_bus_client() -> Any:
    """A Redis client for the KAINE bus, authenticated from the bus configuration."""
    import redis

    from kaine.bus.config import load_bus_config
    bus_cfg = load_bus_config()
    return redis.Redis.from_url(bus_cfg.url, socket_connect_timeout=2.0, socket_timeout=5.0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt):
        # No input / operator interrupt during the interactive flow: fail safe.
        # Nothing is deleted unless every confirmation was given, so an aborted
        # prompt simply leaves the entity (and its backup) intact.
        sys.stderr.write("\nAborted; nothing was deleted.\n")
        sys.exit(5)
