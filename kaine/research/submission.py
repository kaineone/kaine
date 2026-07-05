# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Research bundle builder for kaine.research.

PARAMOUNT SAFETY INVARIANT
--------------------------
The default bundle is ALLOWLIST-BASED and contains NUMERIC METRICS ONLY.
It never includes speech transcripts, the Lingua intent log
(intent_expression.jsonl), Mnemos/Qdrant memories, the Eidolon self-model,
or any conversation content.

Only the subdirectories enumerated in ``METRICS_ONLY_DIRS`` are ever copied
into the metrics bundle — so a future sensitive sink can never leak by default.

Higher-sensitivity tiers ("full") require explicit opt-in flags AND a
bystander-consent + entity-privacy attestation passed to
``build_research_bundle``; without them the call raises ``BundleTierError``
and falls back to metrics.

DATA-INTEGRITY INVARIANT (run-admissibility / log-validation)
---------------------------------------------------------------
``build_research_bundle`` runs BOTH offline admissibility checks the paper
(§6.3) describes — the completeness gate
(``kaine.experiment.admissibility.scan_run``: contiguous ticks/seq, all
expected streams present, no parse errors, no restart signature) and the
log-range sweep (``kaine.experiment.log_schema.sweep_run``: every logged
number within its declared range) — and records BOTH verdicts in the
manifest. The run(s) are AUTO-DISCOVERED from the eval logs
(``discover_run_ids``) so the guarantee holds at the real operator entry point
(``python -m kaine.research``) with no run id passed; ``admissibility_run_id``
only NARROWS the gate to one pinned run. More than one distinct run in the
logs is itself the restart / multi-process condition and is inadmissible.
``require_admissible`` defaults to ``True``: an inadmissible run (failing
either check) is BLOCKED from export, not merely annotated. The only way to
export an inadmissible run is the explicit ``admissibility_override=True`` + a
non-empty ``admissibility_override_reason``, which is itself stamped into the
manifest (``admissibility_override`` block) so an overridden export can never
be mistaken for a clean one.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist — the ONLY subdirectories that may appear in a metrics bundle.
# These names mirror the evaluation sink/observer output dirs (see the
# registry and config under kaine/evaluation/) but are duplicated here on
# purpose: this module never imports the evaluation package, preserving the
# sidecar privacy boundary (only the cycle/nexus entrypoints may couple to it).
# ---------------------------------------------------------------------------

#: Allowed subdirectory names under ``data/evaluation/`` for the metrics tier.
#: This is the SOLE source of truth; the builder copies ONLY these dirs.
METRICS_ONLY_DIRS: tuple[str, ...] = (
    "ab_divergence",
    "individuation",
    "coherence",
    "welfare",
    "fatigue",
    "prediction_error",
    "nous_policy",
    "voice_alignment_divergence",
    # Curated, privacy-filtered research event log (research-event-log change).
    # Numeric/categorical records only; all CONTENT_FIELDS stripped at write
    # time. The LOCAL-ONLY raw bus archive is NOT here — it lives outside
    # data/evaluation/ (state/research/raw_bus_archive/) and is never eligible.
    "research_events",
    # Per-run manifests (experiment-run-identity change): one manifest.json per
    # run holding only run id, seed, git sha, model ids, config digest,
    # started-at, and the kaine version — no entity interior, no operator paths
    # or hostnames. Export-eligible so a shared dataset can be attributed to a
    # configuration. Contains no DENY_PATTERNS substring.
    "runs",
)

#: Glob patterns accepted for the metrics tier (for documentation/tests).
METRICS_ONLY_GLOBS: tuple[str, ...] = tuple(
    f"data/evaluation/{d}/**" for d in METRICS_ONLY_DIRS
)

# ---------------------------------------------------------------------------
# Denylist — patterns that MUST NEVER appear in a metrics bundle.
# The builder is allowlist-based so these are belt-and-suspenders.
# ---------------------------------------------------------------------------

#: Substrings that must never appear in any path inside a metrics bundle.
DENY_PATTERNS: tuple[str, ...] = (
    "intent_expression",
    "mnemos",
    "qdrant",
    "eidolon",
    "self_model",
    "conversation",
    "replay",
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class BundleFile:
    """Metadata for one file copied into the research bundle."""

    rel_path: str          # path relative to bundle root
    source_path: str       # absolute path of the source file
    line_count: int        # number of lines
    sample_line: str       # first non-empty line (truncated to 200 chars)


@dataclass
class Bundle:
    """A built research bundle ready for preview / encrypt / send."""

    bundle_dir: Path
    tier: str
    generated_at: str      # ISO-8601 UTC
    files: list[BundleFile] = field(default_factory=list)
    manifest_path: Optional[Path] = None
    encrypted: bool = False
    plaintext_note: str = ""
    encryption_error: Optional[str] = None
    """Set when encryption was ENABLED but FAILED (as opposed to being disabled
    by config).  A non-None value here means the bundle is plaintext despite the
    operator configuring encryption — callers must treat this as an error, not
    ordinary plaintext."""


class BundleTierError(ValueError):
    """Raised when a higher-sensitivity tier is requested without attestation."""


class AdmissibilityError(ValueError):
    """Raised when ``require_admissible=True`` (the default) and the run failed
    either the completeness scan (run-completeness-gating) or the log-range
    sweep (log-schema-range-sweep). Carries the combined failing reasons."""

    def __init__(self, run_id: str, reasons: list[str]) -> None:
        self.run_id = run_id
        self.reasons = reasons
        super().__init__(
            f"run {run_id!r} is inadmissible (require_admissible=True): "
            + "; ".join(reasons)
        )


class AdmissibilityOverrideError(ValueError):
    """Raised when ``admissibility_override=True`` is set without a reason.

    The override is the explicit, operator-only escape hatch that lets an
    inadmissible run reach export anyway. It must never be triggerable by
    accident, so a bare boolean is not enough — a non-empty
    ``admissibility_override_reason`` is required every time it is used."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _count_lines_and_sample(path: Path) -> tuple[int, str]:
    """Return (line_count, first_non_empty_line[:200])."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        count = len(lines)
        sample = ""
        for ln in lines:
            stripped = ln.strip()
            if stripped:
                sample = stripped[:200]
                break
        return count, sample
    except Exception:
        return 0, ""


def _deny_check(path: str) -> Optional[str]:
    """Return the matching deny pattern if ``path`` matches, else None."""
    lower = path.lower()
    for pat in DENY_PATTERNS:
        if pat in lower:
            return pat
    return None


def _range_violation_reasons(violations: Sequence[Any]) -> list[str]:
    """Human-readable reasons for a non-empty ``sweep_run`` violation list.

    Mirrors ``AdmissibilityReport.reasons()`` so an ``AdmissibilityError``
    raised for a range failure reads the same way as one raised for a
    completeness failure. Takes ``Violation`` objects as loosely-typed data
    (duck-typed on ``.stream``/``.field``/``.value``/``.bound``) so this module
    never needs to import ``kaine.experiment.log_schema`` at module scope.
    """
    out = []
    for v in violations:
        lo, hi = v.bound
        hi_s = "inf" if hi == float("inf") else f"{hi:g}"
        out.append(
            f"range violation: {v.stream}.{v.field} = {v.value:g} "
            f"(expected [{lo:g}, {hi_s}])"
        )
    return out


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def build_research_bundle(
    *,
    eval_root: Path = Path("data/evaluation"),
    tier: str = "metrics",
    out_dir: Path,
    # Full-tier opt-in: both flags must be True AND attestation must be supplied.
    full_tier_opted_in: bool = False,
    bystander_consent_attested: bool = False,
    entity_privacy_attested: bool = False,
    attestation_note: str = "",
    # Post-run admissibility (run-admissibility + log-validation). The bundle
    # manifest carries an `admissibility` verdict (completeness: gaps/missing
    # streams/parse errors/restart signature) AND a `range_admissibility`
    # verdict (every logged number within its declared range) so an inadmissible
    # run can't silently reach analysis looking clean. `expected_streams` is
    # passed in BY THE CALLER as data — this keeps kaine.experiment decoupled
    # from the evaluation package (the bundle builder is the allowed coupling
    # point and derives the expected list there).
    #
    # `admissibility_run_id` is OPTIONAL: when omitted the run(s) are
    # auto-discovered from eval_root and gated automatically (so the CLI is
    # protected without passing anything). Pass it only to NARROW the gate to
    # one specific run.
    admissibility_run_id: Optional[str] = None,
    expected_streams: Sequence[str] = (),
    # Additional run_ids the OPERATOR treats as a continuation of this same
    # logical run (e.g. a crash/resume that minted a fresh run_id — see
    # kaine.experiment.run_context). Declaring any here is itself a
    # restart/multi-process signal (kaine.experiment.admissibility.scan_run).
    admissibility_related_run_ids: Sequence[str] = (),
    # Clean gate: when True (the default) and the run is inadmissible on EITHER
    # check, refuse to build the bundle (raises AdmissibilityError) rather than
    # emitting one with a failing verdict. This is what makes the paper's §6.3
    # guarantee ("an inadmissible run cannot reach analysis looking clean")
    # hold by default — it is enforced, not merely annotated.
    require_admissible: bool = True,
    # Explicit operator escape hatch: export an inadmissible run anyway. MUST
    # be paired with a non-empty `admissibility_override_reason` (enforced
    # below — a bare flag can never trigger the override by accident), and the
    # manifest records BOTH the fact of the override and the reason so an
    # overridden export is never mistaken for a clean one.
    admissibility_override: bool = False,
    admissibility_override_reason: str = "",
) -> Bundle:
    """Build a research bundle from eval_root into out_dir.

    Parameters
    ----------
    eval_root:
        Root directory of the evaluation logs (default ``data/evaluation``).
    tier:
        ``"metrics"`` (default, safe) or ``"full"`` (requires opt-in + attestation).
    out_dir:
        Parent directory for the bundle. A timestamped subdirectory is created.
    full_tier_opted_in:
        Must be ``True`` for tier != "metrics".
    bystander_consent_attested / entity_privacy_attested:
        Must both be ``True`` for tier != "metrics".
    attestation_note:
        A recorded justification for full-tier access.
    admissibility_override:
        Explicit operator override to export an inadmissible run anyway.
        Requires a non-empty ``admissibility_override_reason`` or the call
        raises before anything is built.

    Returns
    -------
    Bundle
        Metadata about the assembled bundle (files, manifest path, encryption).

    Raises
    ------
    BundleTierError
        When tier != "metrics" and the opt-in/attestation conditions are not met.
    AdmissibilityOverrideError
        When ``admissibility_override=True`` but ``admissibility_override_reason``
        is empty/blank.
    AdmissibilityError
        When ``require_admissible=True`` (the default) and the run(s) present in
        ``eval_root`` are inadmissible with no override set — i.e. a discovered
        or pinned run fails completeness or the range sweep, more than one
        distinct run is present (restart/multi-process), a pinned ``run_id``
        matches zero records, or logs are present but unreadable. Auto-discovery
        means NO ``admissibility_run_id`` need be supplied for this to fire.
    """
    eval_root = Path(eval_root)
    out_dir = Path(out_dir)

    if admissibility_override and not admissibility_override_reason.strip():
        raise AdmissibilityOverrideError(
            "admissibility_override=True requires a non-empty "
            "admissibility_override_reason — the override must never be "
            "triggerable by accident."
        )

    if tier != "metrics":
        if not (
            full_tier_opted_in
            and bystander_consent_attested
            and entity_privacy_attested
        ):
            raise BundleTierError(
                f"tier={tier!r} requires full_tier_opted_in=True, "
                "bystander_consent_attested=True, and entity_privacy_attested=True. "
                "Without all three, research submission falls back to tier='metrics'."
            )

    generated_at = datetime.now(timezone.utc).isoformat()
    stamp = _utc_stamp()
    bundle_dir = out_dir / f"research_bundle_{stamp}"
    bundle_dir.mkdir(parents=True, exist_ok=False)

    bundle_files: list[BundleFile] = []

    if tier == "metrics":
        # ALLOWLIST-ONLY: copy exactly the allowed numeric dirs.
        for subdir_name in METRICS_ONLY_DIRS:
            src_dir = eval_root / subdir_name
            if not src_dir.is_dir():
                continue
            dst_dir = bundle_dir / subdir_name
            dst_dir.mkdir(parents=True, exist_ok=True)
            for src_file in sorted(src_dir.rglob("*")):
                if not src_file.is_file():
                    continue
                # Belt-and-suspenders deny check (allowlist is the real gate).
                rel = src_file.relative_to(eval_root)
                matched = _deny_check(str(rel))
                if matched:
                    log.warning(
                        "build_research_bundle: deny-pattern %r matched %s; skipping",
                        matched, rel,
                    )
                    continue
                dst_file = bundle_dir / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                line_count, sample = _count_lines_and_sample(src_file)
                bundle_files.append(
                    BundleFile(
                        rel_path=str(rel),
                        source_path=str(src_file),
                        line_count=line_count,
                        sample_line=sample,
                    )
                )
    else:
        # Full tier: copy all eval files EXCEPT the explicitly denied paths,
        # then redact as needed. (Expansion point for future tiers.)
        log.warning(
            "build_research_bundle: tier=%r with attestation (note=%r); "
            "copying all eval data except denied paths",
            tier, attestation_note,
        )
        for src_file in sorted(eval_root.rglob("*")):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(eval_root)
            matched = _deny_check(str(rel))
            if matched:
                log.info(
                    "build_research_bundle [full]: deny-pattern %r matched %s; skipping",
                    matched, rel,
                )
                continue
            dst_file = bundle_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            line_count, sample = _count_lines_and_sample(src_file)
            bundle_files.append(
                BundleFile(
                    rel_path=str(rel),
                    source_path=str(src_file),
                    line_count=line_count,
                    sample_line=sample,
                )
            )

    # --- Admissibility verdict (run-admissibility + log-validation) ---------
    # Run BOTH offline admissibility checks the paper (§6.3) describes — the
    # completeness gate (scan_run) and the log-range sweep (sweep_run) — over
    # the run(s) present in eval_root, and record both verdicts in the manifest
    # so an inadmissible run is visible at analysis time. Both scans read the
    # SAME eval_root the bundle was built from. Passing expected_streams in as
    # data keeps kaine.experiment off kaine.evaluation.
    #
    # ROOT INVARIANT: the file-copy step above is UNSCOPED (it ships whole
    # allowlisted subtrees regardless of run), so the gate is only sound when
    # scan-scope == copy-scope. That holds iff eval_root contains EXACTLY ONE
    # fully-readable admissible run, or genuinely no run-scoped data. We enforce
    # that here by ALWAYS discovering every run present — even when the caller
    # pins one via `admissibility_run_id`. Pinning only chooses WHICH run is
    # primary; it must never hide the presence of others (else their records
    # would ship under an `admissible: true` manifest).
    #
    #   * pinned run_id → primary is the pin, but any OTHER discovered run_id
    #     (not explicitly acknowledged in admissibility_related_run_ids) folds
    #     into related_run_ids, making it a restart/multi-process condition
    #     (inadmissible). A pin matching ZERO records is itself inadmissible
    #     (it must not vacuously "vouch" for data it does not cover).
    #   * no pin, 1 run   → scan + sweep it, block if inadmissible.
    #   * no pin, >1 run  → restart / multi-process condition; inadmissible.
    #   * unreadable logs → FAIL CLOSED. Lines we cannot decrypt/parse (typically
    #     a wrong/absent state key) must never masquerade as "no run data": if
    #     no readable run was found but there ARE unreadable lines, block.
    #   * genuinely empty → no run to admit. We do NOT fabricate `admissible=true`
    #     (that would pass an unknowable bundle off as clean); we record an honest
    #     `no_run_logs_present` marker and allow the export (non-run-scoped metric
    #     aggregates / pre-run-identity data are a legitimate export, and there is
    #     no run whose integrity could be violated).
    from kaine.experiment.admissibility import scan_run
    from kaine.experiment.log_schema import sweep_run
    from kaine.experiment.run_records import discover_run_ids

    admissibility_block: Optional[dict[str, Any]] = None
    range_block: Optional[dict[str, Any]] = None
    override_block: Optional[dict[str, Any]] = None

    # ALWAYS discover — even when a run is pinned — so other runs can't hide.
    discovery = discover_run_ids(eval_root)
    discovered_ids = discovery.run_ids
    extra = [str(r) for r in admissibility_related_run_ids]

    primary_run_id: Optional[str] = None
    related_run_ids: list[str] = []
    pinned_zero_match = False

    if admissibility_run_id is not None:
        primary_run_id = admissibility_run_id
        acknowledged = {admissibility_run_id, *extra}
        # Any discovered run that the caller did NOT pin or explicitly
        # acknowledge is an unaccounted-for run whose records the copy will
        # still ship — treat it as the multi-process signal.
        unacknowledged = [r for r in discovered_ids if r not in acknowledged]
        related_run_ids = extra + unacknowledged
        # A pin that matches nothing must not vacuously pass (its scan would see
        # zero gaps/violations while the copy ships the REAL, unscanned data).
        pinned_zero_match = admissibility_run_id not in discovered_ids
    elif discovered_ids:
        primary_run_id = discovered_ids[0]
        related_run_ids = discovered_ids[1:] + extra
    else:
        # No pin and no readable run ids.
        primary_run_id = None
        related_run_ids = extra

    if primary_run_id is not None:
        report = scan_run(
            primary_run_id,
            root=eval_root,
            expected_streams=expected_streams,
            related_run_ids=related_run_ids,
        )
        # Sweep the range check over EVERY run in this logical run (primary +
        # any related/restart runs) so the manifest records all violations.
        violations = []
        for rid in [primary_run_id, *related_run_ids]:
            violations.extend(sweep_run(rid, root=eval_root))

        # Extra reasons the run-level scan can't express on its own.
        extra_reasons: list[str] = []
        if pinned_zero_match:
            extra_reasons.append(
                f"pinned run_id {primary_run_id!r} matched zero records"
            )

        admissibility_block = report.to_dict()
        if extra_reasons:
            admissibility_block["admissible"] = False
            admissibility_block["reasons"] = (
                admissibility_block["reasons"] + extra_reasons
            )
            admissibility_block["pinned_zero_match"] = pinned_zero_match
        range_block = {
            "admissible": not violations,
            "violations": [v.to_dict() for v in violations],
        }

        overall_admissible = report.admissible and not violations and not extra_reasons
        if require_admissible and not overall_admissible:
            all_reasons = (
                report.reasons()
                + _range_violation_reasons(violations)
                + extra_reasons
            )
            if admissibility_override:
                # Explicit escape hatch (reason already validated above).
                # Stamp the manifest so an overridden export can never be
                # mistaken for a clean one.
                override_block = {
                    "overridden": True,
                    "reason": admissibility_override_reason,
                }
                log.warning(
                    "build_research_bundle: exporting inadmissible run %r via "
                    "explicit admissibility_override (reason=%r); reasons=%s",
                    primary_run_id, admissibility_override_reason, all_reasons,
                )
            else:
                # Clean gate: refuse to ship an inadmissible run. Remove the
                # partial bundle dir so we don't leave a half-built artefact
                # behind.
                shutil.rmtree(bundle_dir, ignore_errors=True)
                raise AdmissibilityError(primary_run_id, all_reasons)
    elif discovery.unreadable_lines > 0:
        # FAIL CLOSED: no readable run, but lines we could not decrypt/parse
        # exist. A wrong/absent state key must never masquerade as "nothing to
        # admit" — we cannot vouch for logs we cannot read.
        reasons = [
            f"{discovery.unreadable_lines} log line(s) under eval_root could not "
            "be decrypted/parsed and no readable run was found; the bundle "
            "cannot be vouched for (wrong or missing state encryption key?)"
        ]
        admissibility_block = {
            "admissible": False,
            "status": "unreadable_logs",
            "unreadable_lines": discovery.unreadable_lines,
            "reasons": reasons,
        }
        if require_admissible:
            if admissibility_override:
                override_block = {
                    "overridden": True,
                    "reason": admissibility_override_reason,
                }
                log.warning(
                    "build_research_bundle: exporting UNREADABLE-log bundle via "
                    "explicit admissibility_override (reason=%r); %s",
                    admissibility_override_reason, reasons,
                )
            else:
                shutil.rmtree(bundle_dir, ignore_errors=True)
                raise AdmissibilityError("<unreadable-logs>", reasons)
    else:
        # Genuinely empty: no pin, no readable run, no unreadable lines. No run
        # to admit. Record an honest, non-clean marker (NOT admissible=true).
        admissibility_block = {
            "admissible": None,
            "status": "no_run_logs_present",
            "reasons": [
                "no run-stamped records under eval_root; there is no run to "
                "admit or reject (completeness/range gates are keyed on run_id)"
            ],
        }

    # --- Manifest -----------------------------------------------------------
    manifest: dict[str, Any] = {
        "tier": tier,
        "generated_at": generated_at,
        "included_files": [
            {
                "path": bf.rel_path,
                "line_count": bf.line_count,
            }
            for bf in bundle_files
        ],
    }
    if admissibility_block is not None:
        manifest["admissibility"] = admissibility_block
    if range_block is not None:
        manifest["range_admissibility"] = range_block
    if override_block is not None:
        manifest["admissibility_override"] = override_block
    if tier != "metrics":
        manifest["attestation_note"] = attestation_note
        manifest["bystander_consent_attested"] = bystander_consent_attested
        manifest["entity_privacy_attested"] = entity_privacy_attested

    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    bundle = Bundle(
        bundle_dir=bundle_dir,
        tier=tier,
        generated_at=generated_at,
        files=bundle_files,
        manifest_path=manifest_path,
    )

    # --- Encrypt ------------------------------------------------------------
    _encrypt_bundle(bundle)

    return bundle


def _encrypt_bundle(bundle: Bundle) -> None:
    """Tar the bundle contents and encrypt when the state encryptor is enabled.

    Mirrors the pattern in kaine/lifecycle/decommission.py. When encryption is
    disabled, leaves the plaintext files and records a note.
    """
    try:
        from kaine.security.crypto import get_state_encryptor

        encryptor = get_state_encryptor()
        if not encryptor.enabled:
            bundle.plaintext_note = (
                "Bundle is plaintext (state encryption disabled). "
                "Enable [security.state_encryption] and set KAINE_STATE_KEY "
                "to encrypt bundles at rest."
            )
            return

        tar_tmp = bundle.bundle_dir / "_bundle.tar"
        with tarfile.open(tar_tmp, "w") as tar:
            for child in sorted(bundle.bundle_dir.iterdir()):
                if child.name in ("_bundle.tar", "manifest.json"):
                    continue
                tar.add(child, arcname=child.name)
        raw = tar_tmp.read_bytes()
        blob = encryptor.encrypt(raw)
        enc_path = bundle.bundle_dir / "bundle.tar.enc"
        enc_path.write_bytes(blob)
        tar_tmp.unlink()
        # Remove plaintext artefacts (manifest stays readable).
        for child in list(bundle.bundle_dir.iterdir()):
            if child.name in ("bundle.tar.enc", "manifest.json"):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass
        bundle.encrypted = True
    except Exception as exc:
        # Encryption was ENABLED and FAILED.  Set encryption_error (not just
        # plaintext_note) so callers can distinguish "encryption disabled by
        # config" from "encryption was configured and failed".  The operator
        # must not silently receive a plaintext bundle when they requested
        # encryption — this is a security downgrade, not ordinary plaintext.
        error_msg = f"Bundle encryption failed ({type(exc).__name__}: {exc}); left plaintext."
        log.error(
            "_encrypt_bundle: encryption failed; bundle at %s is plaintext — "
            "callers must check bundle.encryption_error",
            bundle.bundle_dir,
            exc_info=True,
        )
        bundle.encryption_error = error_msg
        bundle.plaintext_note = error_msg


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def preview(bundle: Bundle) -> str:
    """Return a human-readable inventory of the bundle for operator review.

    The preview is printed BEFORE any send so the operator can verify exactly
    what is included. It always ends with an EXCLUDED section listing the
    content types that are never in a metrics bundle.
    """
    lines: list[str] = [
        "=" * 70,
        f"KAINE Research Bundle Preview",
        f"  tier:         {bundle.tier}",
        f"  generated_at: {bundle.generated_at}",
        f"  bundle_dir:   {bundle.bundle_dir}",
        f"  encrypted:    {bundle.encrypted}",
        "",
    ]

    if bundle.plaintext_note:
        lines += [f"  NOTE: {bundle.plaintext_note}", ""]

    if bundle.files:
        lines.append(f"Included files ({len(bundle.files)}):")
        for bf in bundle.files:
            lines.append(f"  {bf.rel_path}  ({bf.line_count} lines)")
            if bf.sample_line:
                lines.append(f"    sample: {bf.sample_line[:120]}")
    else:
        lines.append("  (no files matched — eval_root may be empty)")

    lines += [
        "",
        "-" * 70,
        "EXCLUDED by default (never in a metrics bundle):",
        "  - intent log (state/lingua/intent_expression.jsonl)",
        "    REASON: embeds user/bystander utterances and entity internal monologue.",
        "  - Mnemos/Qdrant memories (verbatim transcripts and episodic records).",
        "  - Eidolon self-model (state/eidolon/self_model.json).",
        "  - Conversation content (any turn text).",
        "  - Replay logs (may contain verbatim memory text when replay_redact_content=false).",
        "  - Local-only raw bus archive (state/research/raw_bus_archive/): verbatim",
        "    events incl. conversation content; lives OUTSIDE data/evaluation/ and is",
        "    NEVER in any bundle.",
        "-" * 70,
        "Only the following directories are included in the metrics tier:",
    ]
    for d in METRICS_ONLY_DIRS:
        lines.append(f"  data/evaluation/{d}/")
    lines.append("=" * 70)

    return "\n".join(lines)
