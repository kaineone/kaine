# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Sleep-time ignition audit — pure functions over event lists.

Change ``sleep-ignition-audit``. Everything here is a PURE classification over
lists of already-collected event records: no bus, no I/O, no imports beyond
the stdlib/dataclasses, so the audit core is trivially testable and the Hypnos
wiring stays thin.

Taxonomy:

* external input types (other-initiated ignition): ``audition.transcription``,
  ``mundus.chat``;
* drive type: ``thymos.drive``;
* realization markers: ``external_speech`` (lingua.external),
  ``internal_speech`` (lingua.internal), ``vox.synthesized`` (vox.out),
  ``praxis.action`` (praxis.out); ``realization_failed`` is excluded;
* ``intent.act`` on ``nous.out`` is unrealizable — no effector reads
  ``nous.out`` — and is counted separately, never as executed.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# External-input (other-initiated) workspace coalition member types.
EXTERNAL_INPUT_TYPES = frozenset({"audition.transcription", "mundus.chat"})
# Internal drive coalition member type.
DRIVE_TYPE = "thymos.drive"
# Realization markers (a realized ignition). realization_failed is NOT here.
# NOTE: when Vox is enabled an utterance may appear as BOTH external_speech
# and vox.synthesized (counted twice in realized_total; acceptable while Vox
# ships disabled in the base thesis — revisit if Vox is enabled).
REALIZATION_TYPES = frozenset(
    {"external_speech", "internal_speech", "vox.synthesized", "praxis.action"}
)
REALIZATION_FAILED = "realization_failed"
INTENT_SPEAK = "intent.speak"
INTENT_THINK = "intent.think"
INTENT_ACT = "intent.act"
# No effector reads nous.out — act intents published there are unrealizable
# wiring signals, never executed actions.
UNREALIZABLE_STREAM = "nous.out"


def _member_type(member: Dict[str, Any]) -> Optional[str]:
    """A coalition member's ignition type — ``type`` first, ``source`` back."""
    return member.get("type") or member.get("source")


def _intent_kind(event_type: str) -> Optional[str]:
    if event_type == INTENT_SPEAK:
        return "speak"
    if event_type == INTENT_THINK:
        return "think"
    if event_type == INTENT_ACT:
        return "act"
    return None


def _realization_kind(event_type: str) -> Optional[str]:
    if event_type == "praxis.action":
        return "act"
    if event_type == "internal_speech":
        return "think"
    if event_type in REALIZATION_TYPES:
        return "speak"
    return None


@dataclass
class IgnitionAuditReport:
    """Content-free result of one sleep's ignition audit.

    Only counts, entry_ids, event types, salience values and the sleep_index —
    never text, transcripts, or latent vectors.
    """

    sleep_index: int
    realized_total: int = 0
    input_triggered: int = 0
    drive_triggered: int = 0
    self_initiated: int = 0
    unrealizable_nous_intents: int = 0
    realization_failed_count: int = 0
    input_triggered_entry_ids: List[str] = field(default_factory=list)
    drive_triggered_entry_ids: List[str] = field(default_factory=list)
    self_initiated_entry_ids: List[str] = field(default_factory=list)
    event_types: List[str] = field(default_factory=list)
    saliences: List[Any] = field(default_factory=list)

    def as_payload(self) -> Dict[str, Any]:
        return {
            "sleep_index": self.sleep_index,
            "realized_total": self.realized_total,
            "input_triggered": self.input_triggered,
            "drive_triggered": self.drive_triggered,
            "self_initiated": self.self_initiated,
            "unrealizable_nous_intents": self.unrealizable_nous_intents,
            "realization_failed_count": self.realization_failed_count,
            "input_triggered_entry_ids": list(self.input_triggered_entry_ids),
            "drive_triggered_entry_ids": list(self.drive_triggered_entry_ids),
            "self_initiated_entry_ids": list(self.self_initiated_entry_ids),
            "event_types": list(self.event_types),
            "saliences": list(self.saliences),
        }


def classify_realizations(
    broadcasts: List[Dict[str, Any]],
    intents: List[Dict[str, Any]],
    realizations: List[Dict[str, Any]],
    sleep_index: int = 0,
) -> IgnitionAuditReport:
    """Classify realized volition intents into the three ignition categories.

    ``broadcasts`` are workspace.broadcast snapshot dicts (each with a
    ``selected`` / ``coalition`` list of members carrying ``entry_id``,
    ``source``, ``type``, ``salience``). ``intents`` and ``realizations`` are
    event records ``{"stream", "type", "payload"}`` in stream order.

    A realization (external_speech / internal_speech / vox.synthesized /
    praxis.action, excluding realization_failed) is linked to the most recent
    prior intent of the matching kind: via the realization payload's
    ``entry_id`` when present, else the most recent intent of that kind. The
    intent's ``entry_id`` is then matched against broadcast coalition members:
    input-triggered if the resolved member's source/type is an external-input
    type, or such a type was anywhere in the winning coalition of the
    triggering broadcast; drive-triggered if ``thymos.drive`` is in the
    coalition path; else self-initiated. A missing link classifies as
    self-initiated — the honest default; never guess. ``intent.act`` records
    on ``nous.out`` are counted separately as unrealizable and never counted
    among executed actions.
    """
    coalitions: List[List[Dict[str, Any]]] = []
    for snap in broadcasts:
        members = snap.get("selected") or snap.get("coalition") or []
        if members:
            coalitions.append(list(members))

    unrealizable = 0
    intent_by_entry: Dict[Any, Dict[str, Any]] = {}
    last_by_kind: Dict[str, Dict[str, Any]] = {}
    for rec in intents:
        event_type = rec.get("type", "")
        payload = rec.get("payload") or {}
        if event_type == INTENT_ACT and rec.get("stream") == UNREALIZABLE_STREAM:
            # Wiring signal only — no effector reads nous.out.
            unrealizable += 1
            continue
        kind = _intent_kind(event_type)
        if kind is None:
            continue
        last_by_kind[kind] = rec
        entry_id = payload.get("entry_id")
        if entry_id is not None:
            intent_by_entry[entry_id] = rec

    def _classify(entry_id: Any) -> str:
        # The same entry can win multiple broadcasts, so scan EVERY
        # coalition containing the entry and apply the conservative rule:
        # any external-input member -> input; else any drive member ->
        # drive; else self.
        coalitions_with_entry: list[list[dict[str, Any]]] = []
        for members in coalitions:
            if any(m.get("entry_id") == entry_id for m in members):
                coalitions_with_entry.append(members)
        if not coalitions_with_entry:
            # Honest default — never guess.
            return "self"
        for members in coalitions_with_entry:
            for m in members:
                if _member_type(m) in EXTERNAL_INPUT_TYPES:
                    return "input"
        for members in coalitions_with_entry:
            for m in members:
                if _member_type(m) == DRIVE_TYPE:
                    return "drive"
        return "self"

    report = IgnitionAuditReport(sleep_index=sleep_index)
    report.unrealizable_nous_intents = unrealizable
    for rec in realizations:
        event_type = rec.get("type", "")
        if event_type == REALIZATION_FAILED:
            report.realization_failed_count += 1
            continue
        kind = _realization_kind(event_type)
        if kind is None:
            continue
        payload = rec.get("payload") or {}
        entry_id = payload.get("entry_id")
        intent = intent_by_entry.get(entry_id) if entry_id is not None else None
        if intent is None:
            intent = last_by_kind.get(kind)
        intent_payload = (intent or {}).get("payload") or {}
        intent_entry = intent_payload.get("entry_id")
        if intent_entry is None:
            intent_entry = entry_id
        category = _classify(intent_entry)
        report.realized_total += 1
        report.event_types.append(event_type)
        salience = intent_payload.get("salience")
        if salience is None:
            salience = payload.get("salience")
        if salience is not None:
            report.saliences.append(salience)
        if intent_entry is not None:
            entry_str = str(intent_entry)
            if category == "input":
                report.input_triggered_entry_ids.append(entry_str)
            elif category == "drive":
                report.drive_triggered_entry_ids.append(entry_str)
            else:
                report.self_initiated_entry_ids.append(entry_str)
        if category == "input":
            report.input_triggered += 1
        elif category == "drive":
            report.drive_triggered += 1
        else:
            report.self_initiated += 1
    return report
