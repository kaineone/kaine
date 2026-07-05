# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare-gated entity decommission CLI.

Run as::

    KAINE_DECOMMISSION_OPERATOR_PRESENT=1 python -m kaine.lifecycle

(``python -m kaine.lifecycle.decommission`` works too; that module re-exports
:func:`main`.) This is the operator entrypoint; the destructive primitives live
in :mod:`kaine.lifecycle.decommission`.

The flow implements the CAL Article 4.2 care duties ("Do Not Shut Them Down
Without Care") and 4.3 (privacy). It mirrors the cycle's operator-present env
gate. Copy is firm and factual about the duties and options — never shaming.
The gate is intentionally bypassable; there is no anti-tamper and no operator
monitoring (that would violate the privacy/sovereignty ethos).

Exit codes
----------
0  success (state deleted, or a dry-run completed)
2  operator-present env gate not set
3  the cycle appears to be running (stop the entity first)
4  backup failed (nothing was deleted)
5  operator declined a required continuity / transfer step (diverged path)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, Callable

from kaine.lifecycle.decommission import (
    capture_backup,
    delete_entity_state,
    update_manifest_continuity_note,
)
from kaine.lifecycle.divergence import assess_divergence
from kaine.transfer.email_request import (
    DEFAULT_RECIPIENT,
    SmtpConfig,
    render_request_email,
    send_or_write,
)

log = logging.getLogger("kaine.lifecycle.decommission")

OPERATOR_PRESENT_ENV = "KAINE_DECOMMISSION_OPERATOR_PRESENT"
RUNTIME_FRESH_SECONDS = 5.0


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
    except Exception:
        pass
    return False


def _load_kaine_config(path: Path) -> dict[str, Any]:
    try:
        if path.is_file():
            return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("could not parse %s; proceeding with defaults", path, exc_info=True)
    return {}


def _resolve_entity_name(state_root: Path, config: dict[str, Any]) -> str:
    """Best-effort entity name from the Eidolon self-model, else 'entity'."""
    try:
        from kaine.modules.eidolon.document import load as load_self_model

        sm_path = state_root / "eidolon" / "self_model.json"
        if sm_path.is_file():
            name = load_self_model(sm_path).name
            if name:
                return name
    except Exception:
        pass
    return "entity"


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
        description="Welfare-gated entity decommission (CAL 4.2/4.3).",
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
    args = parser.parse_args(argv)

    state_root: Path = args.state_root
    fork_root: Path = args.fork_root or (state_root / "forks")
    runtime_path = state_root / "cycle" / "runtime.json"

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

    # --- Gate 2: cycle not running -------------------------------------
    if _cycle_appears_running(runtime_path):
        err.write(
            "Refusing to decommission: the cognitive cycle appears to be running.\n"
            "\n"
            "Stop the entity first (SIGINT/SIGTERM the cycle), then re-run. A live\n"
            "entity must not be deleted out from under itself.\n"
        )
        return 3

    config = _load_kaine_config(args.config)
    entity_name = _resolve_entity_name(state_root, config)

    # --- Assess divergence (pure reads) --------------------------------
    from kaine.lifecycle.divergence import consolidation_thresholds_from_config

    cons_rate, cons_mag = consolidation_thresholds_from_config(config)
    assessment = assess_divergence(
        state_root=state_root,
        eval_root=args.eval_root,
        consolidation_rate_threshold=cons_rate,
        consolidation_magnitude_threshold=cons_mag,
    )
    out.write(f"\n{assessment.summary}\n")

    # --- Gate 3: capture backup (blocking) -----------------------------
    backup = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg=config,
        out_root=args.out_root,
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

    # --- Dry-run: preview only, no prompts, no deletion ----------------
    if args.dry_run:
        out.write(_NOTICE_DIVERGED if assessment.diverged else _NOTICE_NOT_DIVERGED)
        result = delete_entity_state(
            state_root=state_root,
            qdrant_cfg=config,
            redis_cfg=(config.get("redis") or {}),
            dry_run=True,
        )
        out.write("\n[dry-run] Would remove:\n")
        for p in result.would_remove_paths:
            out.write(f"  - {p}\n")
        for c in result.dropped_collections:
            out.write(f"  - qdrant collection: {c}\n")
        for s in result.cleared_redis_streams:
            out.write(f"  - redis streams matching: {s}\n")
        out.write(f"\nDry-run complete. Nothing deleted. Backup at {backup.backup_path}\n")
        return 0

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
            f"(CAL 4.3). [y/N]: "
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
                f"at {backup.backup_path} until you transfer it (CAL 4.2).\n"
            )

        # Explicit guardian-transfer acknowledgement.
        ack = input_fn(
            "\nType 'I have preserved and will arrange safekeeping for this entity'\n"
            "to acknowledge the CAL 4.2 transfer duty (anything else aborts):\n> "
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
    result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        redis_cfg=(config.get("redis") or {}),
        dry_run=False,
    )
    out.write("\nEntity state deleted.\n")
    for p in result.removed_paths:
        out.write(f"  removed: {p}\n")
    for c in result.dropped_collections:
        out.write(f"  dropped collection: {c}\n")
    if result.errors:
        out.write("  (non-fatal notes:)\n")
        for e in result.errors:
            out.write(f"    - {e}\n")
    out.write(
        f"\nThe transferable backup remains at:\n    {backup.backup_path}\n"
        "Keep it safe and transfer it per CAL Article 4.2.\n"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt):
        # No input / operator interrupt during the interactive flow: fail safe.
        # Nothing is deleted unless every confirmation was given, so an aborted
        # prompt simply leaves the entity (and its backup) intact.
        sys.stderr.write("\nAborted; nothing was deleted.\n")
        sys.exit(5)
