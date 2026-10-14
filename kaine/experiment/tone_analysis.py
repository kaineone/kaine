# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The tone analysis of the planned test.

Paper §6.3, "Speech sound and tone of voice", and Appendix A.8, "Speech sound
and tone". In the tone variant of the on arm every tone event is graded by the
tone model's error ratio alone. The analysis reads a run's research-event
records of type ``audition.emotion`` and ``workspace.broadcast`` and computes
the accessed fraction of the emotional tone events minus the accessed fraction
of the neutral ones. Across runs the statistics enter the exact sign tests of
the decision rule in ``kaine.experiment.calibration_rules.sign_test_verdict``.

The first test is on the run's difference of fractions, the second on its
adjusted difference over the tone bins; both are made at alpha_test, outside the
verdict on the thesis, with no multiplicity adjustment (paper A.8).
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from kaine.bus.schema import split_stream_entry_key
from kaine.experiment.calibration_rules import N_EXACT, SignTestResult, sign_test_verdict

TONE_EVENT_TYPE = "audition.emotion"
BROADCAST_EVENT_TYPE = "workspace.broadcast"
TONE_VARIANT_RULE = "error_ratio"
NEUTRAL = "neutral"


class ToneAnalysisError(ValueError):
    """A tone-analysis input record was malformed."""


@dataclass(frozen=True)
class ToneEvent:
    """One classified tone event with its error ratio and access status."""

    entry_id: str
    emotional: bool
    error_ratio: float
    accessed: bool


def accessed_members(records: Iterable[Mapping[str, Any]]) -> set[tuple[str, str, str]]:
    """Return the (source, type, entry_id) tuples of all accessed broadcast members.

    A non-inhibited broadcast contributes its members whose score reaches the
    access threshold, which such a broadcast must carry when it has members. The
    score is ``salience_scores.get(entry_id, member salience)``, as in
    ``kaine.modules.context`` (paper A.1). An inhibited broadcast contributes
    nothing.

    Both member ids and matching tone event ids are the stream-qualified ids
    ``<stream>:<entry_id>`` (a bus entry id alone is unique only within its
    stream).

    Raises:
        ToneAnalysisError: on malformed broadcast metadata.
    """
    accessed: set[tuple[str, str, str]] = set()
    for record in records:
        if record.get("event_type") != BROADCAST_EVENT_TYPE:
            continue

        inhibited = record.get("inhibited")
        if not isinstance(inhibited, bool):
            raise ToneAnalysisError("broadcast record inhibited must be a bool")

        if "entries" in record and not isinstance(record["entries"], list):
            raise ToneAnalysisError("broadcast entries must be a list or absent")
        if inhibited:
            continue

        if "salience_scores" in record and not isinstance(record["salience_scores"], dict):
            raise ToneAnalysisError("broadcast salience_scores must be a dict or absent")

        threshold = record.get("access_threshold")
        if threshold is not None:
            if (
                not isinstance(threshold, (int, float))
                or isinstance(threshold, bool)
                or not math.isfinite(threshold)
            ):
                raise ToneAnalysisError("broadcast access_threshold must be a finite number or absent")

        salience_scores = record.get("salience_scores") or {}
        members = record.get("entries", []) or []
        # The tone variant runs the competitive arm, whose broadcasts with
        # members always carry the threshold; without it access is unknown.
        if members and threshold is None:
            raise ToneAnalysisError("an accessed broadcast with members has no access_threshold")
        seen_entry_ids: set[str] = set()
        for member in members:
            if not isinstance(member, dict):
                raise ToneAnalysisError("broadcast member must be a dict")
            entry_id = member.get("entry_id")
            source = member.get("source")
            type_ = member.get("type")
            if not isinstance(entry_id, str) or not entry_id:
                raise ToneAnalysisError("broadcast member entry_id must be a non-empty string")
            if not all(split_stream_entry_key(entry_id)):
                raise ToneAnalysisError(
                    "broadcast member entry_id has no stream: "
                    "the record predates stream-qualified candidate ids "
                    "(<stream>:<entry_id>) and cannot be joined; re-record the run"
                )
            if not isinstance(source, str) or not source:
                raise ToneAnalysisError("broadcast member source must be a non-empty string")
            if not isinstance(type_, str) or not type_:
                raise ToneAnalysisError("broadcast member type must be a non-empty string")

            # Candidate ids are unique within a tick, so two members with one id
            # mean a corrupt record.
            if entry_id in seen_entry_ids:
                raise ToneAnalysisError(
                    f"a broadcast has two members with entry_id {entry_id!r}"
                )
            seen_entry_ids.add(entry_id)

            score = salience_scores.get(entry_id, member.get("salience"))
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not math.isfinite(score)
            ):
                raise ToneAnalysisError("broadcast member score must be a finite number")

            if score >= threshold:
                accessed.add((source, type_, entry_id))

    return accessed


def tone_events(
    records: Iterable[Mapping[str, Any]],
    *,
    tone_rule: str = TONE_VARIANT_RULE,
    t_learn_s: float | None = None,
) -> list[ToneEvent]:
    """Extract classified tone events and their access status.

    Materializes ``records`` once, computes the set of accessed broadcast members,
    then returns one ``ToneEvent`` per classified ``audition.emotion`` record in
    input order. Unclassified events are skipped; malformed records raise.

    When ``t_learn_s`` is not ``None``, only events whose ``entity_time_s`` is
    strictly greater than ``t_learn_s`` are returned. This implements the planned
    test's rule that tone events count only after the learning period ``T_learn``,
    measured in entity time (paper Appendix A.8). In this mode every classified
    tone record must carry a finite ``entity_time_s``; otherwise a
    ``ToneAnalysisError`` is raised.

    Raises:
        ToneAnalysisError: if a tone record is missing required fields, has an
            unexpected rule, carries a non-finite / negative normalised error, or
            (when ``t_learn_s`` is given) has no finite ``entity_time_s``.
    """
    records = list(records)
    accessed = accessed_members(records)

    events: list[ToneEvent] = []
    for record in records:
        if record.get("event_type") != TONE_EVENT_TYPE:
            continue

        classified = record.get("classified")
        if not isinstance(classified, bool):
            raise ToneAnalysisError("tone event classified must be a bool")
        if not classified:
            continue

        if t_learn_s is not None:
            entity_time_s = record.get("entity_time_s")
            if (
                not isinstance(entity_time_s, (int, float))
                or isinstance(entity_time_s, bool)
                or not math.isfinite(entity_time_s)
            ):
                raise ToneAnalysisError(
                    "tone event has no entity_time_s: the record predates tone timestamps and cannot be counted after T_learn; re-record the run"
                )
            if entity_time_s <= t_learn_s:
                continue

        rule = record.get("tone_rule")
        if rule != tone_rule:
            raise ToneAnalysisError(
                f"tone event rule {rule!r} does not match expected rule {tone_rule!r}"
            )

        entry_id = record.get("entry_id")
        source = record.get("source")
        if not isinstance(entry_id, str) or not entry_id:
            raise ToneAnalysisError("tone event entry_id must be a non-empty string")
        if not all(split_stream_entry_key(entry_id)):
            raise ToneAnalysisError(
                "tone event entry_id has no stream: "
                "the record predates stream-qualified candidate ids "
                "(<stream>:<entry_id>) and cannot be joined; re-record the run"
            )
        if not isinstance(source, str) or not source:
            raise ToneAnalysisError("tone event source must be a non-empty string")

        category = record.get("category")
        if not isinstance(category, str):
            raise ToneAnalysisError("tone event category must be a string")

        error = record.get("tone_error_ratio")
        if (
            not isinstance(error, (int, float))
            or isinstance(error, bool)
            or not math.isfinite(error)
            or error < 0
        ):
            raise ToneAnalysisError("tone event tone_error_ratio must be a finite non-negative number")

        events.append(
            ToneEvent(
                entry_id=entry_id,
                emotional=category != NEUTRAL,
                error_ratio=float(error),
                accessed=(source, TONE_EVENT_TYPE, entry_id) in accessed,
            )
        )

    return events


def accessed_fractions(events: Sequence[ToneEvent]) -> tuple[float | None, float | None]:
    """Return (emotional accessed fraction, neutral accessed fraction).

    A group with no event returns ``None``.
    """
    emotional = [e for e in events if e.emotional]
    neutral = [e for e in events if not e.emotional]

    emotional_frac = (
        None
        if not emotional
        else sum(1 for e in emotional if e.accessed) / len(emotional)
    )
    neutral_frac = (
        None if not neutral else sum(1 for e in neutral if e.accessed) / len(neutral)
    )
    return emotional_frac, neutral_frac


def run_statistic(events: Sequence[ToneEvent]) -> float | None:
    """Emotional accessed fraction minus neutral accessed fraction.

    ``None`` when either group has no event.
    """
    emotional_frac, neutral_frac = accessed_fractions(events)
    if emotional_frac is None or neutral_frac is None:
        return None
    return emotional_frac - neutral_frac


def bin_index(error_ratio: float, edges: Sequence[float]) -> int:
    """Return the tone-error-ratio bin index.

    A value equal to an interior edge falls in the bin above it, matching
    ``bisect.bisect_right``.
    """
    return bisect.bisect_right(edges, error_ratio)


def adjusted_statistic(events: Sequence[ToneEvent], edges: Sequence[float]) -> float | None:
    """Adjusted difference of emotional and neutral accessed fractions.

    Group ``events`` by ``bin_index`` over ``edges``. For each bin that holds
    both emotional and neutral tone events, compute ``run_statistic`` on the
    events in that bin. The adjusted statistic is the plain mean of the defined
    bin statistics; it is ``None`` when no bin has both kinds of event.

    This follows Cochran (1968): stratify by the nuisance variable and average
    the within-stratum contrasts to remove the confounding (paper A.8).
    """
    by_bin: dict[int, list[ToneEvent]] = {}
    for event in events:
        by_bin.setdefault(bin_index(event.error_ratio, edges), []).append(event)

    bin_stats = [
        run_statistic(by_bin[b]) for b in sorted(by_bin) if run_statistic(by_bin[b]) is not None
    ]
    if not bin_stats:
        return None
    return sum(bin_stats) / len(bin_stats)


def tone_runs_still_needed(differences: Sequence[float | None], n_exact: int = N_EXACT) -> int:
    """Return how many additional tone runs are needed.

    The tone variant is planned with the arms' ``n_run`` and runs are added
    until at least ``n_exact`` runs give a defined difference (paper A.8).
    """
    if n_exact < 1:
        raise ToneAnalysisError("n_exact must be at least 1")
    defined = sum(1 for d in differences if d is not None)
    return max(0, n_exact - defined)


def tone_verdict(statistics: Sequence[float | None], min_effect: float) -> SignTestResult:
    """Sign-test verdict for the tone run-level statistics."""
    return sign_test_verdict(statistics, min_effect)


__all__ = [
    "BROADCAST_EVENT_TYPE",
    "NEUTRAL",
    "TONE_EVENT_TYPE",
    "TONE_VARIANT_RULE",
    "ToneAnalysisError",
    "ToneEvent",
    "accessed_fractions",
    "accessed_members",
    "adjusted_statistic",
    "bin_index",
    "run_statistic",
    "tone_events",
    "tone_runs_still_needed",
    "tone_verdict",
]
