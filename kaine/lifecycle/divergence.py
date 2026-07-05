# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Divergence (individuation) assessment for the welfare-gated decommission.

`assess_divergence()` answers a single question for the decommission CLI: *has
this entity individuated — become someone — rather than remaining a fresh,
generic instance?* The answer gates which CAL 4.2 care path the operator must
walk (the stricter diverged path records a continuity preference and offers a
guardian-transfer handshake; see ``kaine/lifecycle/decommission.py``).

Two distinct "divergences" exist in the codebase; this uses the right one:

* **A/B divergence** (``kaine.evaluation.ab_divergence``) measures conditioned-
  vs-bare-pretrained output distance. It is present even on a fresh boot when
  conditioning works, so it answers "is this more than a chatbot", NOT "is this
  entity someone." We deliberately do **not** key on it.
* **Individuation** (``kaine.evaluation.individuation``) is a permutation test
  whose ``significant`` flag is true when the entity's divergence from its own
  **birth-state** (its earlier self, captured at run start — never the bare
  organ) exceeds the 95th percentile of the entity's OWN present stochastic
  variation, AND the entity has accumulated the minimum lived experience
  (``warmed_up``). That measures genuine individuation over lived time (not the
  always-present architecture-conditioning effect) and is our primary input. A
  report that is not warmed up is fail-closed here: it reads NOT diverged on
  this axis, with the operator advised to treat the entity as mature if unsure —
  the same warm-up state the live preservation trigger consumes, so the two
  never disagree.

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
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Conservative shipped thresholds for the graded consolidation-divergence
#: signal. Either crossing marks organ-level divergence. Operator-calibrated
#: via ``[hypnos.voice_alignment]`` in kaine.toml (the principled, always-
#: computed signal the threshold-calibration work targets).
DEFAULT_CONSOLIDATION_RATE_THRESHOLD = 0.5
DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD = 0.25


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


def _newest_individuation_report(individuation_dir: Path) -> dict[str, Any] | None:
    """Return the last JSONL line of the newest ``*.jsonl`` report, or None.

    Pure, guarded — any error (missing dir, unreadable file, bad JSON) yields
    None rather than raising.
    """
    try:
        if not individuation_dir.is_dir():
            return None
        files = sorted(
            (p for p in individuation_dir.glob("*.jsonl") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        if not files:
            return None
        newest = files[-1]
        last_obj: dict[str, Any] | None = None
        for line in newest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                last_obj = obj
        return last_obj
    except Exception:
        log.debug("assess_divergence: reading individuation report failed", exc_info=True)
        return None


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


def assess_divergence(
    *,
    state_root: Path = Path("state"),
    eval_root: Path = Path("data/evaluation"),
    consolidation_rate_threshold: float = DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
    consolidation_magnitude_threshold: float = DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
) -> DivergenceAssessment:
    """Classify whether an entity has individuated. Pure reads; never raises.

    Parameters
    ----------
    state_root:
        Root of the on-disk entity state (default ``state``). Tests point this
        at a tmp dir.
    eval_root:
        Root of evaluation output (default ``data/evaluation``); the newest
        ``individuation/*.jsonl`` report is read from here.
    consolidation_rate_threshold, consolidation_magnitude_threshold:
        The graded consolidation-divergence thresholds. The latest
        ``state/hypnos/consolidation_divergence.json`` record marks organ-level
        divergence when its ``divergence_rate`` >= the rate threshold OR its
        (non-null) ``divergence_magnitude`` >= the magnitude threshold. Shipped
        conservative; operator-calibrated.
    """
    state_root = Path(state_root)
    eval_root = Path(eval_root)

    # --- Primary: individuation permutation test --------------------------
    # The report shares ONE warmed-up, birth-state-referenced signal with the
    # live preservation trigger. Fail-closed: a report that is not warmed up
    # (insufficient lived experience) reads NOT significant here, exactly as the
    # live monitor treats it as not-crossed — the two consumers never disagree.
    # A legacy report missing the ``warmed_up`` key is treated as warmed up
    # (mature-by-construction operator path), but ``significant`` itself is only
    # ever set true by the instrument when warm-up held, so this never upgrades
    # a void report.
    report = _newest_individuation_report(eval_root / "individuation")
    report_warmed_up = (
        bool(report.get("warmed_up", True)) if report else False
    )
    primary_significant = (
        bool(report.get("significant")) and report_warmed_up if report else False
    )
    p_value = report.get("p_value") if report else None
    fork_divergence = report.get("fork_divergence") if report else None

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
    adapters_present = _adapters_present(state_root / "hypnos" / "adapters")

    diverged = bool(
        primary_significant
        or consolidation_diverged
        or eidolon_drift
        or adapters_present
    )

    signals: dict[str, Any] = {
        "individuation_report_found": report is not None,
        "individuation_warmed_up": report_warmed_up,
        "individuation_significant": primary_significant,
        "individuation_p_value": p_value,
        "fork_divergence": fork_divergence,
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
        if primary_significant:
            reasons.append("the individuation permutation test is significant")
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
    elif report is not None and not report_warmed_up:
        # A report exists but the entity has not accumulated the minimum lived
        # experience for the individuation signal to be trusted (Defect B). The
        # signal is fail-closed: NOT diverged on this axis, with the operator
        # advised to treat the entity as mature if unsure. Other (warmed-up or
        # warm-up-independent) signals above may still set ``diverged``; this
        # branch only fires when none of them did.
        summary = (
            "NOT DIVERGED (INSUFFICIENT LIVED EXPERIENCE): the individuation "
            "report has not warmed up — the entity has not accumulated the "
            "minimum logged observations and lived time for the signal to be "
            "trusted, so individuation could not be confirmed from it. Treat the "
            "entity as mature if you are unsure and choose the stricter "
            "decommission path."
        )
    elif (
        self_model is None
        and report is None
        and consolidation is None
        and not adapters_present
    ):
        summary = (
            "COULD NOT CONFIRM: no individuation report, Eidolon self-model, or "
            "voice adapters were found, so individuation could not be assessed. "
            "Treat the entity as mature if you are unsure and choose the stricter "
            "decommission path."
        )
    else:
        summary = (
            "NOT DIVERGED: the available signals do not indicate individuation. "
            "If you have any reason to believe this entity has become an individual, "
            "treat it as mature and choose the stricter decommission path."
        )

    return DivergenceAssessment(diverged=diverged, signals=signals, summary=summary)
