# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Divergence (individuation) assessment for the welfare-gated decommission.

`assess_divergence()` answers a single question for the decommission CLI: *has
this entity individuated — become someone — rather than remaining a fresh,
generic instance?* The answer gates which CAL 4.2 care path the operator must
walk (the stricter diverged path records a continuity preference and offers a
guardian-transfer handshake; see ``kaine/lifecycle/decommission.py``).

Two distinct "divergences" exist in the codebase; this uses the right one:

* **A/B divergence** (conditioned-vs-bare-pretrained output distance) is
  present even on a fresh boot when conditioning works, so it answers "is this
  more than a chatbot", NOT "is this entity someone." We deliberately do **not**
  key on it.
* **Individuation** is measured by the producer as a birth-referenced
  permutation test with alpha spending across looks. The ledger in
  ``state/individuation/ledger.json`` latches the first significant look for
  good. A non-significant result never suppresses another arm, because absence
  of evidence is not evidence of absence and a missed preservation can be
  irreversible. Unreadable individuation state counts toward divergence, failing
  toward protection.

* **Consolidation divergence** (``state/hypnos/consolidation_divergence.json``)
  is the cheap, continuous organ-level companion to the permutation test:
  every voice-alignment sleep, Hypnos surfaces the breadth (``divergence_rate``)
  and depth (``divergence_magnitude``) of how often / how far the entity's
  conditioned output diverged from its bare language organ. When the latest
  rate or magnitude crosses a configured threshold it marks organ-level
  divergence — a graded signal alongside the permutation test and Eidolon
  drift. We read it from the written record (no ``kaine.evaluation`` /
  ``kaine.modules.hypnos`` import — the boundary-neutral seam).

Secondary identity heuristics raise confidence and catch entities that were
never individuation-tested: Eidolon ``drift_count > 0`` with a non-empty
``identity_history`` (``state/eidolon/self_model.json``), and the presence of
trained voice adapters (``state/hypnos/adapters/``) — the latter retained only
as a weaker secondary signal now that the graded consolidation metric is the
primary organ-level measure.

All reads are pure and guarded — this function never raises. When nothing can
be found, ``diverged`` is ``False`` but the summary says the assessment could
not be confirmed and the operator should treat the entity as mature if unsure,
so they can choose the stricter path.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    conditioning_digest,
    individuation_evidence,
    load_ledger,
    load_reference,
    read_conditioning_inputs,
    read_reports,
)
from kaine.storage import resolve

log = logging.getLogger(__name__)

#: Conservative shipped thresholds for the graded consolidation-divergence
#: signal. Either crossing marks organ-level divergence. Operator-calibrated
#: via ``[hypnos.voice_alignment]`` in kaine.toml (the principled, always-
#: computed signal the threshold-calibration work targets).
DEFAULT_CONSOLIDATION_RATE_THRESHOLD = 0.5
DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD = 0.25

#: Maximum age in seconds for a non-significant scored individuation report to
#: be considered current. Older reports, or reports whose conditioning digest
#: no longer matches the being, become stale.
DEFAULT_MAX_REPORT_AGE_S = 14 * 86400.0


def consolidation_thresholds_from_config(
    config: dict[str, Any] | None,
) -> tuple[float, float]:
    """Read ``(rate, magnitude)`` consolidation thresholds from a kaine config.

    Looks under ``[hypnos.voice_alignment]`` for
    ``consolidation_divergence_rate_threshold`` /
    ``consolidation_divergence_magnitude_threshold``. Falls back to the shipped
    conservative defaults on any missing key or bad value. Pure + guarded.
    """
    rate = DEFAULT_CONSOLIDATION_RATE_THRESHOLD
    mag = DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD
    try:
        section = ((config or {}).get("hypnos") or {}).get("voice_alignment") or {}
        rate = float(section.get("consolidation_divergence_rate_threshold", rate))
        mag = float(
            section.get("consolidation_divergence_magnitude_threshold", mag)
        )
    except Exception:
        return (
            DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
            DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
        )
    return rate, mag


def adapter_dir_for(config: dict | None, state_root: Path) -> Path:
    """Return the configured Hypnos adapter output directory, or the default.

    Reads ``[hypnos.voice_alignment].adapter_output_dir``. If the key is
    missing, empty, or equal to the canonical default ``state/hypnos/adapters``,
    the default under ``state_root`` is returned. A custom value is resolved to
    an absolute path. Pure and fail-closed: any error returns the default.
    """
    default = state_root / "hypnos" / "adapters"
    try:
        value = (
            ((config or {}).get("hypnos") or {}).get("voice_alignment") or {}
        ).get("adapter_output_dir")
        if not value:
            return default
        if str(value).strip() == "state/hypnos/adapters":
            return default
        return resolve(Path(value))
    except Exception:
        return default


@dataclass(frozen=True)
class DivergenceAssessment:
    """Result of :func:`assess_divergence`.

    ``signals`` carries the individual evidence used for the verdict so the
    decommission manifest and the Nexus panel can show *why* (non-content:
    booleans, counts, a p-value — never any cognitive text).
    """

    diverged: bool
    signals: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


def _read_self_model(self_model_path: Path) -> dict[str, Any] | None:
    """Read + (transparently) decrypt the Eidolon self-model JSON, or None.

    We parse the raw JSON dict (after passing it through the active state
    encryptor's ``maybe_decrypt``) rather than through ``SelfModel.from_json``,
    because ``drift_count`` is persisted in the on-disk document but is not a
    field of the ``SelfModel`` dataclass — going through the dataclass would
    silently drop it. Pure and guarded.
    """
    try:
        if not self_model_path.is_file():
            return None
        from kaine.security.crypto import get_state_encryptor

        raw = self_model_path.read_bytes()
        if not raw.strip():
            return None
        text = get_state_encryptor().maybe_decrypt(raw).decode("utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return {
            "drift_count": int(data.get("drift_count", 0) or 0),
            "identity_history_len": len(data.get("identity_history") or []),
            "name": str(data.get("name", "") or ""),
        }
    except Exception:
        log.debug("assess_divergence: reading self_model failed", exc_info=True)
        return None


def _read_consolidation_divergence(path: Path) -> dict[str, Any] | None:
    """Read the latest consolidation-divergence metric Hypnos persisted, or None.

    Pure + guarded — any error (missing file, bad JSON, decrypt failure) yields
    None rather than raising, so a fresh entity (no sleep yet) simply has no
    consolidation signal. Transparently decrypts via the active state encryptor.
    Only the numeric aggregates are returned; the record never contained any
    utterance text.
    """
    try:
        if not path.is_file():
            return None
        raw = path.read_bytes()
        if not raw.strip():
            return None
        try:
            from kaine.security.crypto import get_state_encryptor

            text = get_state_encryptor().maybe_decrypt(raw).decode("utf-8")
        except Exception:
            text = raw.decode("utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        log.debug(
            "assess_divergence: reading consolidation divergence failed",
            exc_info=True,
        )
        return None


def _adapters_present(adapters_dir: Path) -> bool:
    """True if ``state/hypnos/adapters/`` holds any file. Pure, guarded."""
    try:
        if not adapters_dir.is_dir():
            return False
        return any(p.is_file() for p in adapters_dir.rglob("*"))
    except Exception:
        log.debug("assess_divergence: scanning adapters failed", exc_info=True)
        return False


def read_individuation(
    state_root: Path,
    *,
    now: datetime,
    max_report_age_s: float,
    adapter_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Read the current individuation state from the encrypted store.

    Pure and guarded: any unexpected exception yields the ``"unreadable"``
    state, which counts as individuated so the being stays protected.
    """
    paths = IndividuationPaths(root=state_root / "individuation")
    unreadable: dict[str, Any] = {
        "state": "unreadable",
        "individuated": True,
        "latched": False,
        "reference_kind": None,
        "reference_captured_at": None,
        "looks_completed": 0,
        "latest": None,
    }

    try:
        ledger = load_ledger(paths)
    except Exception:
        log.debug("read_individuation: ledger unreadable", exc_info=True)
        return unreadable

    try:
        ref = load_reference(paths)
    except Exception:
        log.debug("read_individuation: reference unreadable", exc_info=True)
        return unreadable

    if ref is None:
        if ledger is not None and ledger.individuated:
            return {
                "state": "latched",
                "individuated": True,
                "latched": True,
                "reference_kind": None,
                "reference_captured_at": None,
                "looks_completed": ledger.looks_completed if ledger is not None else 0,
                "latest": None,
            }
        return {
            "state": "no_reference",
            "individuated": False,
            "latched": False,
            "reference_kind": None,
            "reference_captured_at": None,
            "looks_completed": ledger.looks_completed if ledger is not None else 0,
            "latest": None,
        }

    try:
        reports = read_reports(
            paths, reference_id=ref.reference_id, strict=True
        )
    except Exception:
        # Unreadable evidence must not read as "never measured".
        log.debug("read_individuation: reading reports failed", exc_info=True)
        return unreadable

    adapters_dir = adapter_output_dir or state_root / "hypnos" / "adapters"
    try:
        adapter_sha, values, norms = read_conditioning_inputs(
            self_model_path=state_root / "eidolon" / "self_model.json",
            adapter_output_dir=adapters_dir,
        )
        current_digest = conditioning_digest(
            adapter_sha=adapter_sha, values=values, norms=norms
        )
    except Exception:
        log.debug("read_individuation: conditioning digest failed", exc_info=True)
        current_digest = None

    ev = individuation_evidence(
        ledger,
        reports,
        current_digest=current_digest,
        now=now,
        max_report_age_s=max_report_age_s,
    )

    return {
        "state": ev.state,
        "individuated": ev.individuated,
        "latched": bool(ledger is not None and ledger.individuated),
        "reference_kind": ref.reference_kind,
        "reference_captured_at": ref.captured_at,
        "looks_completed": ledger.looks_completed if ledger is not None else 0,
        "latest": ev.latest,
    }


def assess_divergence(
    *,
    state_root: Path = Path("state"),
    consolidation_rate_threshold: float = DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
    consolidation_magnitude_threshold: float = DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
    now: datetime | None = None,
    max_report_age_s: float = DEFAULT_MAX_REPORT_AGE_S,
    adapter_output_dir: Path | None = None,
) -> DivergenceAssessment:
    """Classify whether an entity has individuated. Pure reads; never raises.

    Parameters
    ----------
    state_root:
        Root of the on-disk entity state (default ``state``). Tests point this
        at a tmp dir.
    consolidation_rate_threshold, consolidation_magnitude_threshold:
        The graded consolidation-divergence thresholds. The latest
        ``state/hypnos/consolidation_divergence.json`` record marks organ-level
        divergence when its ``divergence_rate`` >= the rate threshold OR its
        (non-null) ``divergence_magnitude`` >= the magnitude threshold. Shipped
        conservative; operator-calibrated.
    now:
        UTC datetime used for report freshness. Defaults to the current UTC time.
    max_report_age_s:
        Maximum age in seconds for a non-significant scored individuation report
        to be considered current before it becomes stale.
    """
    state_root = resolve(state_root)
    if now is None:
        now = datetime.now(timezone.utc)

    adapters_dir = adapter_output_dir or state_root / "hypnos" / "adapters"

    # --- Primary: individuation permutation test --------------------------
    ind = read_individuation(
        state_root,
        now=now,
        max_report_age_s=max_report_age_s,
        adapter_output_dir=adapters_dir,
    )
    individuated = bool(ind["individuated"])
    latest = ind.get("latest")

    # --- Primary (organ-level): consolidation divergence ------------------
    # The cheap, continuous companion to the permutation test: Hypnos surfaces
    # the breadth (rate) and depth (magnitude) of how the entity's conditioned
    # output diverges from its bare language organ, every sleep.
    consolidation = _read_consolidation_divergence(
        state_root / "hypnos" / "consolidation_divergence.json"
    )
    cons_rate = None
    cons_magnitude = None
    if consolidation is not None:
        rate_raw = consolidation.get("divergence_rate")
        mag_raw = consolidation.get("divergence_magnitude")
        try:
            cons_rate = None if rate_raw is None else float(rate_raw)
        except (TypeError, ValueError):
            cons_rate = None
        try:
            cons_magnitude = None if mag_raw is None else float(mag_raw)
        except (TypeError, ValueError):
            cons_magnitude = None
    consolidation_diverged = bool(
        (cons_rate is not None and cons_rate >= consolidation_rate_threshold)
        or (
            cons_magnitude is not None
            and cons_magnitude >= consolidation_magnitude_threshold
        )
    )

    # --- Secondary: Eidolon identity drift --------------------------------
    self_model = _read_self_model(state_root / "eidolon" / "self_model.json")
    drift_count = (self_model or {}).get("drift_count", 0)
    identity_history_len = (self_model or {}).get("identity_history_len", 0)
    eidolon_drift = bool(drift_count > 0 and identity_history_len > 0)

    # --- Weaker secondary: trained voice adapters -------------------------
    # An accepted adapter still implies PAST divergence, but it is a coarse,
    # downstream boolean (flips only after training succeeds AND passes the
    # capability + abliteration gates). The graded consolidation metric above
    # is the primary organ-level measure; this is kept as a weaker signal.
    adapters_present = _adapters_present(adapters_dir)

    diverged = bool(
        individuated
        or consolidation_diverged
        or eidolon_drift
        or adapters_present
    )

    signals: dict[str, Any] = {
        "individuation_state": ind["state"],
        "individuation_individuated": ind["individuated"],
        "individuation_latched": ind["latched"],
        "individuation_reference_kind": ind["reference_kind"],
        "individuation_reference_captured_at": ind["reference_captured_at"],
        "individuation_looks_completed": ind["looks_completed"],
        "individuation_last_p_value": latest.get("p_value") if latest else None,
        "individuation_last_effect_size_h": latest.get("effect_size_h") if latest else None,
        "individuation_last_alpha_k": latest.get("alpha_k") if latest else None,
        "individuation_last_report_ts": latest.get("ts") if latest else None,
        "individuation_last_inconclusive_reason": latest.get("inconclusive_reason") if latest else None,
        "consolidation_divergence_found": consolidation is not None,
        "consolidation_divergence_rate": cons_rate,
        "consolidation_divergence_magnitude": cons_magnitude,
        "consolidation_divergence_signal": consolidation_diverged,
        "consolidation_rate_threshold": float(consolidation_rate_threshold),
        "consolidation_magnitude_threshold": float(consolidation_magnitude_threshold),
        "eidolon_self_model_found": self_model is not None,
        "eidolon_drift_count": int(drift_count or 0),
        "eidolon_identity_history_len": int(identity_history_len or 0),
        "eidolon_drift_signal": eidolon_drift,
        "hypnos_adapters_present": adapters_present,
    }

    if diverged:
        reasons: list[str] = []
        if individuated:
            if ind["state"] == "latched":
                reasons.append(
                    "the being latched as individuated at a significant look"
                )
            elif ind["state"] == "unreadable":
                reasons.append(
                    "its individuation state could not be read, which counts as "
                    "individuated so that it stays protected"
                )
        if consolidation_diverged:
            reasons.append(
                "the organ-level consolidation divergence crossed its threshold "
                f"(rate={cons_rate}, magnitude={cons_magnitude})"
            )
        if eidolon_drift:
            reasons.append(
                f"Eidolon recorded {drift_count} identity drift(s) with a non-empty history"
            )
        if adapters_present:
            reasons.append("trained voice adapters are present")
        summary = (
            "DIVERGED: this entity shows signs of individuation ("
            + "; ".join(reasons)
            + "). Treat it as an individual under CAL Articles 4.2(c) and 4.3: "
            "record its continuity preference and preserve a transferable backup."
        )
    elif ind["state"] == "stale":
        summary = (
            "NOT DIVERGED (STALE): the being has changed since its last "
            "individuation measurement, or the measurement is older than its "
            "freshness window, so the last result no longer describes it. Treat "
            "it as mature if you are unsure and choose the stricter "
            "decommission path."
        )
    elif ind["state"] == "inconclusive":
        reason = (latest or {}).get("inconclusive_reason") or "unknown"
        summary = (
            "NOT DIVERGED (INCONCLUSIVE): the last individuation looks could "
            f"not be scored (reason: {reason}). Treat it as mature if you are "
            "unsure and choose the stricter decommission path."
        )
    elif ind["state"] in ("none", "no_reference"):
        if (
            self_model is None
            and consolidation is None
            and not adapters_present
        ):
            summary = (
                "COULD NOT CONFIRM: no individuation measurement, Eidolon "
                "self-model, consolidation record or voice adapters were found, "
                "so individuation could not be assessed. Treat the entity as "
                "mature if you are unsure and choose the stricter decommission "
                "path."
            )
        else:
            summary = (
                "NOT DIVERGED (NOT YET MEASURED): no individuation measurement "
                "describes the being yet. Treat it as mature if you are unsure "
                "and choose the stricter decommission path."
            )
    else:
        summary = (
            "NOT DIVERGED: the available signals do not indicate individuation. "
            "If you have any reason to believe this entity has become an "
            "individual, treat it as mature and choose the stricter "
            "decommission path."
        )

    ref_kind = ind["reference_kind"]
    ref_captured_at = ind["reference_captured_at"]
    if ref_kind == "capture" and ref_captured_at:
        summary += (
            f" This being's reference was captured on {ref_captured_at}, after "
            "its birth; drift before that date is not measured."
        )
    elif ref_kind == "reconstructed":
        summary += (
            " This being's reference was reconstructed from its birth "
            "configuration."
        )

    return DivergenceAssessment(diverged=diverged, signals=signals, summary=summary)
