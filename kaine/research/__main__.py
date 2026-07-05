# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI for operator-initiated research bundle submission.

Usage::

    python -m kaine.research --preview            # build + preview; NEVER sends
    python -m kaine.research --send               # build → preview → confirm → send-or-write
    python -m kaine.research --eval-root PATH \\
                              --out-root PATH \\
                              --tier metrics \\
                              --config config/kaine.toml \\
                              --preview

Recipient is read from [research_submission].recipient (config), else from
[transfer].recipient. If neither is set, kaine.one@tuta.com is suggested as the
project guardian address but the operator MUST confirm it before any send.

NEVER sends without an interactive confirmation. EOF / KeyboardInterrupt at the
confirm prompt fails safe (no send).

Admissibility (paper §6.3): the run(s) in --eval-root are auto-discovered and
gated on BOTH the completeness gate and the log-range sweep before any preview
or send. An inadmissible run (incomplete, out-of-range, or a restart /
multi-process condition, i.e. more than one distinct run in the logs) is
BLOCKED — the CLI exits non-zero. Use --run-id to pin one specific run, or
--admissibility-override-reason "<why>" to export an inadmissible run anyway
(the reason is recorded in the manifest).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Callable, IO, Optional

log = logging.getLogger(__name__)


def _load_config(config_path: str | os.PathLike[str]) -> dict:
    """Load kaine.toml through the canonical loader; ``{}`` on failure.

    Routes through :func:`kaine.config.load_kaine_config` so the research
    entrypoint honours the gitignored operator override
    (``config/kaine.operator.toml``) exactly like the cognitive cycle does,
    instead of parsing the shipped file with raw ``tomllib`` and silently
    ignoring operator choices.
    """
    from kaine.config import OPERATOR_CONFIG_PATH, load_kaine_config

    p = Path(config_path)
    if not p.exists():
        return {}
    try:
        return load_kaine_config(p, OPERATOR_CONFIG_PATH)
    except Exception as exc:
        log.warning("could not load config %s: %s", p, exc)
        return {}


def _smtp_config_from_toml(cfg: dict):
    """Build a SmtpConfig from the [transfer] table."""
    from kaine.transfer.email_request import SmtpConfig

    return SmtpConfig.from_mapping(cfg.get("transfer") or {})


def _research_email_body(*, bundle_path: str, recipient: str, tier: str) -> str:
    return (
        f"Hello,\n\n"
        f"I am a KAINE operator. I am submitting a research data bundle for "
        f"your records.\n\n"
        f"Bundle tier: {tier}\n"
        f"The bundle is a metrics-only archive (numeric evaluation data; no speech, "
        f"transcripts, memories, or entity inner life). The bundle currently lives "
        f"on this machine at:\n\n"
        f"    {bundle_path}\n\n"
        f"Nothing has been uploaded. Please reply with any instructions.\n\n"
        f"This message contains no entity data — only the request, the tier, and "
        f"the local path of the bundle (CAL Article 4.3).\n\n"
        f"You can reach the project at: {recipient}\n\n"
        f"Thank you,\n"
        f"A KAINE operator\n"
    )


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] | None = None,
    out: IO[str] | None = None,
    err: IO[str] | None = None,
) -> int:
    """Entry point. Returns exit code (0 = success, 1 = error, 2 = no-send)."""
    out = out or sys.stdout
    err = err or sys.stderr

    parser = argparse.ArgumentParser(
        prog="python -m kaine.research",
        description=(
            "Operator-initiated KAINE research bundle submission. "
            "Default tier: metrics-only (no speech, memories, or inner life)."
        ),
    )
    parser.add_argument(
        "--eval-root",
        default="data/evaluation",
        help="Root of the evaluation logs (default: data/evaluation).",
    )
    parser.add_argument(
        "--out-root",
        default="research_out",
        help="Parent directory for output bundles (default: research_out).",
    )
    parser.add_argument(
        "--tier",
        default="metrics",
        choices=["metrics"],   # full tier is gated by attestation; not a CLI flag
        help="Bundle tier (only 'metrics' is available without explicit opt-in).",
    )
    parser.add_argument(
        "--config",
        default="config/kaine.toml",
        help="Path to kaine.toml (default: config/kaine.toml).",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Build the bundle and print a preview. NEVER sends.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Build, preview, confirm, encrypt, then send-or-write via kaine.transfer.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Optional: pin admissibility to ONE specific run id. When omitted "
            "(the default), the run(s) in --eval-root are auto-discovered and "
            "gated automatically."
        ),
    )
    parser.add_argument(
        "--admissibility-override-reason",
        default=None,
        metavar="REASON",
        help=(
            "Explicitly export an INADMISSIBLE run anyway, recording this reason "
            "in the manifest. Use only when you understand the run is not clean."
        ),
    )
    parser.add_argument(
        "--expected-stream",
        action="append",
        default=None,
        dest="expected_streams",
        metavar="NAME",
        help=(
            "A stream the run was expected to produce; a run missing it is "
            "inadmissible (repeatable). Defaults to "
            "[research_submission].expected_streams from config."
        ),
    )
    args = parser.parse_args(argv)

    if not args.preview and not args.send:
        parser.print_help(out)
        out.write(
            "\nHint: use --preview to inspect the bundle contents, "
            "or --send to submit it.\n"
        )
        return 0

    # --- Load config --------------------------------------------------------
    cfg = _load_config(args.config)
    rs_cfg = cfg.get("research_submission") or {}
    enabled = bool(rs_cfg.get("enabled", False))
    recipient = str(rs_cfg.get("recipient") or "").strip()

    # Fall back to [transfer].recipient if research_submission.recipient is empty.
    if not recipient:
        recipient = str((cfg.get("transfer") or {}).get("recipient") or "").strip()

    # --- Install state encryption BEFORE reading any logs -------------------
    # The admissibility gate reads the eval logs (discover_run_ids /
    # load_run_records), which decrypt each line through the process-global
    # StateEncryptor. If we don't install the operator's configured encryptor
    # here (as boot.py / preboot.py do), the default no-op encryptor leaves
    # every encrypted line unreadable → zero run_ids discovered → the gate
    # would fail OPEN. Install it, fail closed on a misconfigured key.
    from kaine.security.crypto import CryptoConfigError, install_from_section

    try:
        install_from_section((cfg.get("security") or {}).get("state_encryption") or {})
    except CryptoConfigError as exc:
        err.write(
            f"ERROR: state encryption is enabled but its key is unavailable: {exc}\n"
            "Set KAINE_STATE_KEY (or disable [security.state_encryption]) so the "
            "admissibility gate can read the logs. Refusing to build a bundle "
            "against logs it cannot decrypt.\n"
        )
        return 1

    # Expected streams: CLI flag wins, else config, else none.
    expected_streams = args.expected_streams
    if expected_streams is None:
        expected_streams = list(rs_cfg.get("expected_streams") or [])

    # --- Build bundle -------------------------------------------------------
    from kaine.research.submission import (
        AdmissibilityError,
        AdmissibilityOverrideError,
        build_research_bundle,
        preview,
        BundleTierError,
    )

    eval_root = Path(args.eval_root)
    out_dir = Path(args.out_root)

    override = args.admissibility_override_reason is not None
    try:
        bundle = build_research_bundle(
            eval_root=eval_root,
            tier=args.tier,
            out_dir=out_dir,
            admissibility_run_id=args.run_id,
            expected_streams=expected_streams,
            admissibility_override=override,
            admissibility_override_reason=args.admissibility_override_reason or "",
        )
    except BundleTierError as exc:
        err.write(f"ERROR: {exc}\n")
        return 1
    except AdmissibilityError as exc:
        # The paper §6.3 gate fired: the run in --eval-root is inadmissible.
        err.write(f"ERROR: {exc}\n")
        err.write(
            "The run failed admissibility (completeness and/or log-range and/or "
            "restart). It is BLOCKED from export. If you understand the run is "
            "not clean and still need it, re-run with "
            "--admissibility-override-reason \"<why>\".\n"
        )
        return 1
    except AdmissibilityOverrideError as exc:
        err.write(f"ERROR: {exc}\n")
        return 1
    except Exception as exc:
        err.write(f"ERROR building bundle: {type(exc).__name__}: {exc}\n")
        return 1

    # --- Preview ------------------------------------------------------------
    preview_text = preview(bundle)
    out.write(preview_text + "\n")

    if args.preview:
        out.write("\n[--preview mode: bundle built and previewed. Nothing sent.]\n")
        return 0

    # --- Send path ----------------------------------------------------------
    if not enabled:
        out.write(
            "\nNOTE: [research_submission].enabled is false in config.\n"
            "You may still send, but you must confirm explicitly below.\n\n"
        )

    # Determine / confirm recipient.
    from kaine.transfer.email_request import DEFAULT_RECIPIENT

    _input = input_fn or input

    if not recipient:
        out.write(
            f"No recipient configured. The suggested project guardian address is:\n"
            f"  {DEFAULT_RECIPIENT}\n\n"
        )
        try:
            typed = _input(f"Enter recipient email [{DEFAULT_RECIPIENT}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\nAborted (EOF/interrupt). Nothing sent.\n")
            return 2
        recipient = typed if typed else DEFAULT_RECIPIENT
        # Require explicit confirmation of the chosen recipient.
        try:
            ok = _input(f"Confirm send to {recipient!r}? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out.write("\nAborted (EOF/interrupt). Nothing sent.\n")
            return 2
        if ok not in ("y", "yes"):
            out.write("Recipient not confirmed. Nothing sent.\n")
            return 2
    else:
        # Recipient is configured; still require confirm before send.
        try:
            ok = _input(
                f"\nSend metrics bundle to {recipient!r}? [y/N]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            out.write("\nAborted (EOF/interrupt). Nothing sent.\n")
            return 2
        if ok not in ("y", "yes"):
            out.write("Send declined. Nothing sent.\n")
            return 2

    # --- Build and send the email -------------------------------------------
    from kaine.transfer.email_request import RenderedEmail, send_or_write

    smtp_config = _smtp_config_from_toml(cfg)

    bundle_path = str(bundle.bundle_dir)
    body = _research_email_body(
        bundle_path=bundle_path, recipient=recipient, tier=bundle.tier
    )
    rendered = RenderedEmail(
        subject=f"KAINE research bundle submission — {bundle.tier} tier",
        body=body,
        recipient=recipient,
    )

    # send_or_write requires a confirm callable; we already confirmed above,
    # so we pass a lambda that always returns True.
    result = send_or_write(
        rendered,
        smtp_config=smtp_config,
        confirm=lambda: True,
        out_dir=out_dir,
    )

    if result.sent:
        out.write(f"\nSent: {result.detail}\n")
    else:
        out.write(f"\nNot sent via SMTP: {result.detail}\n")
        if result.eml_path:
            out.write(f"  Written to: {result.eml_path}\n")
        if result.mailto_link:
            out.write(f"  mailto link (first 200 chars): {result.mailto_link[:200]}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
