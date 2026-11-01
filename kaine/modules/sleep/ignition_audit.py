# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Sleep-time ignition audit: pure functions over event lists.

Change ``sleep-ignition-audit``. Everything here is a PURE classification over
lists of already-collected event records: no bus, no I/O, and no imports
beyond the stdlib and the shared external-input type list
(``kaine.faithful.external_input``), so the audit core is trivially testable
and the sleep module wiring stays thin.

Realization-to-intent linking uses the language module's intent log. A
realization payload from ``language.external`` or ``language.internal`` carries
``record_id``; the caller provides a mapping from that ``record_id`` to the
intent ``entry_id`` it realized. Only a requested sleep still falls back to the
most recent ``intent.rest``; speak, think, and act realizations are not
attributed to another intent when the link is missing.

Taxonomy:

* external input types (other-initiated ignition): ``audition.transcription``,
  ``embodiment.chat``;
* drive type: ``affect.drive``;
* realization markers: ``external_speech`` (language.external),
  ``internal_speech`` (language.internal), ``vocal.synthesized`` (vocal.out),
  ``effectors.action`` (effectors.out), and ``sleep.sleep.started`` with
  ``trigger == "requested"`` (a realized rest); ``realization_failed`` is
  excluded;
* ``intent.*`` on ``planning.out`` is unrealizable (no effector reads
  ``planning.out``) and is counted separately, never as executed;
* planning-originated intents (``origin == "planning"``) are classified
  ``planning_initiated`` before the input/drive/self rules;
* ``action_selection.proposal_outcome`` events contribute ``planning_proposals_realized``,
  ``planning_proposals_declined`` and ``planning_proposals_forwarded`` counts;
  forwarded rests are counted separately because the sleep module decides them, and
  an accepted one shows up as a requested sleep.

The operator-speech readout (change ``operator-speech-as-perception``,
:func:`operator_speech_readout`) is a separate pure function over the waking
window's main-bus transcription counts, broadcasts and realizations: operator
speech heard, how often it won access, how often the entity spoke within
:data:`OPERATOR_SPEECH_WINDOW_S` of entity time after it, and how often it
spoke otherwise. It is content-free (counts only) and observation only: the
sleep module publishes it on ``sleep_readout.out``, a stream the cycle never
reads and no module consumes, never on ``sleep.out`` and never in the audit
record, so nothing of it enters the entity.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from kaine.bus.schema import OPERATOR_SOURCES, entry_id_sort_key, stream_entry_key
from kaine.bus.streams import AUDITION_STREAM, OPERATOR_SPEECH_READOUT_FIELDS, PLANNING_STREAM
from kaine.faithful.external_input import EXTERNAL_INPUT_TYPES, spoken_counts

# EXTERNAL_INPUT_TYPES (other-initiated coalition member types) is the shared
# definition from kaine.faithful.external_input, also used by heard-speech
# redaction.
# Internal drive coalition member type.
DRIVE_TYPE = "affect.drive"
# Realization markers (a realized ignition). realization_failed is NOT here.
# NOTE: when the vocal module is enabled an utterance may appear as BOTH external_speech
# and vocal.synthesized (counted twice in realized_total; acceptable while the vocal module
# ships disabled in the first configuration; revisit if the vocal module is enabled).
REALIZATION_TYPES = frozenset(
    {"external_speech", "internal_speech", "vocal.synthesized", "effectors.action"}
)
REALIZATION_FAILED = "realization_failed"
INTENT_SPEAK = "intent.speak"
INTENT_THINK = "intent.think"
INTENT_ACT = "intent.act"
INTENT_REST = "intent.rest"
# No effector reads planning.out: act intents published there are unrealizable
# wiring signals, never executed actions.
UNREALIZABLE_STREAM = PLANNING_STREAM


def _member_type(member: Dict[str, Any]) -> Optional[str]:
    """A coalition member's ignition type: ``type`` first, ``source`` back."""
    return member.get("type") or member.get("source")


def _intent_kind(event_type: str) -> Optional[str]:
    if event_type == INTENT_SPEAK:
        return "speak"
    if event_type == INTENT_THINK:
        return "think"
    if event_type == INTENT_ACT:
        return "act"
    if event_type == INTENT_REST:
        return "rest"
    return None


def _realization_kind(event_type: str, payload: Dict[str, Any]) -> Optional[str]:
    if event_type == "effectors.action":
        return "act"
    if event_type == "internal_speech":
        return "think"
    if event_type == "sleep.sleep.started":
        if payload.get("trigger") == "requested":
            return "rest"
        return None
    if event_type in REALIZATION_TYPES:
        return "speak"
    return None


@dataclass
class IgnitionAuditReport:
    """Content-free result of one sleep's ignition audit.

    Only counts, entry_ids, event types, salience values and the sleep_index,
    never text, transcripts, or latent vectors.
    """

    sleep_index: int
    realized_total: int = 0
    input_triggered: int = 0
    drive_triggered: int = 0
    self_initiated: int = 0
    planning_initiated: int = 0
    unrealizable_planning_intents: int = 0
    realization_failed_count: int = 0
    planning_proposals_realized: int = 0
    planning_proposals_declined: int = 0
    planning_proposals_forwarded: int = 0
    input_triggered_entry_ids: List[str] = field(default_factory=list)
    drive_triggered_entry_ids: List[str] = field(default_factory=list)
    self_initiated_entry_ids: List[str] = field(default_factory=list)
    planning_initiated_entry_ids: List[str] = field(default_factory=list)
    event_types: List[str] = field(default_factory=list)
    saliences: List[Any] = field(default_factory=list)

    def as_payload(self) -> Dict[str, Any]:
        return {
            "sleep_index": self.sleep_index,
            "realized_total": self.realized_total,
            "input_triggered": self.input_triggered,
            "drive_triggered": self.drive_triggered,
            "self_initiated": self.self_initiated,
            "planning_initiated": self.planning_initiated,
            "unrealizable_planning_intents": self.unrealizable_planning_intents,
            "realization_failed_count": self.realization_failed_count,
            "planning_proposals_realized": self.planning_proposals_realized,
            "planning_proposals_declined": self.planning_proposals_declined,
            "planning_proposals_forwarded": self.planning_proposals_forwarded,
            "input_triggered_entry_ids": list(self.input_triggered_entry_ids),
            "drive_triggered_entry_ids": list(self.drive_triggered_entry_ids),
            "self_initiated_entry_ids": list(self.self_initiated_entry_ids),
            "planning_initiated_entry_ids": list(self.planning_initiated_entry_ids),
            "event_types": list(self.event_types),
            "saliences": list(self.saliences),
        }


def classify_realizations(
    broadcasts: List[Dict[str, Any]],
    intents: List[Dict[str, Any]],
    realizations: List[Dict[str, Any]],
    proposal_outcomes: List[Dict[str, Any]] = (),
    sleep_index: int = 0,
    *,
    record_links: Optional[Mapping[str, str]] = None,
) -> IgnitionAuditReport:
    """Classify realized action selection module intents into ignition categories.

    ``broadcasts`` are workspace.broadcast snapshot dicts (each with a
    ``selected`` / ``coalition`` list of members carrying ``entry_id``,
    ``source``, ``type``, ``salience``). ``intents`` and ``realizations`` are
    event records ``{"stream", "type", "payload"}`` in stream order.
    ``proposal_outcomes`` are ``action_selection.proposal_outcome`` records with
    ``realized`` bool and optional ``reason``. ``record_links`` maps a language
    module ``record_id`` to the ``intent_entry_id`` of the intent that record
    realized.

    A successful realization (external_speech / internal_speech /
    vocal.synthesized with success=True / effectors.action / sleep.sleep.started
    with trigger="requested", excluding realization_failed and
    vocal.synthesized with success=False) is linked to its intent. The link is
    the realization payload's ``entry_id`` if present, otherwise
    ``record_links[payload["record_id"]]`` when a mapping is provided. Only a
    requested sleep falls back to the most recent ``intent.rest``; speak, think,
    and act realizations are left unlinked rather than attributed to another
    intent. The intent's ``entry_id`` is then matched against broadcast coalition
    members:
    The planning-module-originated intents (``origin == "planning"``) win first as
    ``planning_initiated``; otherwise input-triggered if the resolved member's
    source/type is an external-input type, or such a type was anywhere in the
    winning coalition of the triggering broadcast; drive-triggered if
    ``affect.drive`` is in the coalition path; else self-initiated. When the
    link is missing for speak, think, or act, the category is self-initiated,
    the honest default; never guess. A realization whose link is known but whose
    intent is not present in this window is still classified by its link against
    the window's broadcasts. ``intent.*`` records on ``planning.out`` are counted
    separately as unrealizable and never counted among executed actions.
    ``action_selection.proposal_outcome`` events contribute
    ``planning_proposals_realized``, ``planning_proposals_declined`` and
    ``planning_proposals_forwarded`` counts; a ``forwarded`` rest outcome counts
    only as forwarded, because the sleep module decides it.
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
        if event_type.startswith("intent.") and rec.get("stream") == UNREALIZABLE_STREAM:
            # Wiring signal only: no effector reads planning.out.
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
            # Honest default, never guess.
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
    report.unrealizable_planning_intents = unrealizable
    for outcome in proposal_outcomes:
        payload = outcome.get("payload") or {}
        if payload.get("reason") == "forwarded":
            report.planning_proposals_forwarded += 1
        elif payload.get("realized") is True:
            report.planning_proposals_realized += 1
        else:
            report.planning_proposals_declined += 1

    for rec in realizations:
        event_type = rec.get("type", "")
        if event_type == REALIZATION_FAILED:
            report.realization_failed_count += 1
            continue
        payload = rec.get("payload") or {}
        if event_type == "vocal.synthesized":
            if payload.get("success") is False:
                report.realization_failed_count += 1
                continue
        kind = _realization_kind(event_type, payload)
        if kind is None:
            continue

        link = payload.get("entry_id")
        if link is None and record_links is not None:
            record_id = payload.get("record_id")
            if record_id is not None and record_id in record_links:
                link = record_links[record_id]

        intent = intent_by_entry.get(link) if link is not None else None
        linked_exactly = intent is not None
        if intent is None and kind == "rest":
            intent = last_by_kind.get(kind)

        intent_payload = (intent or {}).get("payload") or {}
        if intent is not None:
            intent_entry = intent_payload.get("entry_id")
        else:
            intent_entry = link

        # Provenance is attributed only from evidence: the realization's own
        # origin (the language module copies it from the intent it realized), an
        # intent linked exactly by entry_id, or a requested sleep's intent.rest.
        # A speech realization is never marked planning-module-initiated merely
        # because the last intent of that kind in the window had origin "planning".
        if payload.get("origin") == "planning":
            category = "planning"
        elif linked_exactly and intent_payload.get("origin") == "planning":
            category = "planning"
        elif (
            event_type == "sleep.sleep.started"
            and payload.get("trigger") == "requested"
            and intent_payload.get("origin") == "planning"
        ):
            category = "planning"
        else:
            if intent_entry is None:
                category = "self"
            else:
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
            elif category == "planning":
                report.planning_initiated_entry_ids.append(entry_str)
            else:
                report.self_initiated_entry_ids.append(entry_str)
        if category == "input":
            report.input_triggered += 1
        elif category == "drive":
            report.drive_triggered += 1
        elif category == "planning":
            report.planning_initiated += 1
        else:
            report.self_initiated += 1
    return report


# --- operator-speech readout (operator-speech-as-perception) ----------------

#: The window, in entity seconds, after accessed operator speech within which a
#: realized external utterance counts as "spoke after operator speech". A
#: readout constant: nothing in the entity reads it.
OPERATOR_SPEECH_WINDOW_S = 30.0
TRANSCRIPTION_TYPE = "audition.transcription"
EXTERNAL_SPEECH_TYPE = "external_speech"


def _is_operator_speech(type_: Any, payload: Mapping[str, Any], operator_sources) -> bool:
    """A non-empty operator-channel transcription, from labels and counts only."""
    if type_ != TRANSCRIPTION_TYPE or not isinstance(payload, Mapping):
        return False
    if payload.get("source_label") not in operator_sources:
        return False
    chars, _words = spoken_counts(payload)
    return chars > 0


def _wall_ms(entry_id: Any) -> Optional[float]:
    """The wall-clock millisecond of a bus entry id, or None when it is not one."""
    rank, ms, _seq, _rest = entry_id_sort_key(str(entry_id))
    return float(ms) if rank == 0 else None


def operator_speech_readout(
    transcriptions: List[Dict[str, Any]],
    broadcasts: List[tuple],
    realizations: List[Dict[str, Any]],
    *,
    operator_sources=OPERATOR_SOURCES,
    window_s: float = OPERATOR_SPEECH_WINDOW_S,
) -> Optional[Dict[str, Any]]:
    """Content-free counts of operator speech heard, accessed and followed by speech.

    ``transcriptions`` are ``audition.out`` records ``{"entry_id", "type",
    "payload"}`` whose payload holds only labels and counts (the main-bus
    copy: ``source_label``, ``text_chars``); ``broadcasts`` are
    ``(entry_id, snapshot)`` pairs of ``workspace.broadcast`` in stream order;
    ``realizations`` are ``{"entry_id", "type", "payload"}`` records from
    ``language.external``.

    - ``operator_speech_heard``: non-empty operator-channel transcriptions in the window.
    - ``operator_speech_accessed``: how many of those won access (were a member
      of at least one broadcast coalition). Each utterance counts once however
      many broadcasts it won.
    - ``spoke_after_operator_speech``: accessed utterances followed by a
      realized ``external_speech`` within ``window_s`` entity seconds of the
      utterance's first access and before the next accessed utterance's.
    - ``spoke_otherwise``: realized ``external_speech`` in no such window.
    - ``operator_speech_access_share``: accessed / heard.

    Entity time comes from each broadcast's ``published_at`` (entity seconds)
    and ``time_scale``; an utterance's access time is the ``published_at`` of
    the first broadcast it won, and a realization's entity time is
    extrapolated from the latest broadcast at or before it on the wall clock
    (the earliest one after it when there is none before). Returns ``None``
    when no operator speech was heard, so the caller publishes nothing.
    """
    heard_keys: list[str] = []
    for rec in transcriptions:
        if _is_operator_speech(rec.get("type"), rec.get("payload") or {}, operator_sources):
            heard_keys.append(stream_entry_key(AUDITION_STREAM, str(rec.get("entry_id"))))
    if not heard_keys:
        return None
    heard_set = set(heard_keys)

    # (wall_ms, entity_s, scale) per broadcast, and each heard utterance's first access.
    timeline: list[tuple[float, float, float]] = []
    first_access: Dict[str, float] = {}
    for entry_id, snap in broadcasts:
        if not isinstance(snap, Mapping):
            continue
        published_at = snap.get("published_at")
        if isinstance(published_at, bool) or not isinstance(published_at, (int, float)):
            continue
        entity_s = float(published_at)
        scale = snap.get("time_scale")
        scale = float(scale) if isinstance(scale, (int, float)) and not isinstance(scale, bool) and scale > 0 else 1.0
        wall = _wall_ms(entry_id)
        if wall is not None:
            timeline.append((wall, entity_s, scale))
        for member in snap.get("selected") or snap.get("coalition") or []:
            if not isinstance(member, Mapping):
                continue
            key = member.get("entry_id")
            if key in heard_set and key not in first_access and _is_operator_speech(
                member.get("type"), member.get("payload") or {}, operator_sources
            ):
                first_access[key] = entity_s
    timeline.sort()

    def _entity_time(wall: float) -> Optional[float]:
        if not timeline:
            return None
        before = [t for t in timeline if t[0] <= wall]
        ref = before[-1] if before else timeline[0]
        return ref[1] + (wall - ref[0]) / 1000.0 * ref[2]

    speech_times: list[float] = []
    for rec in realizations:
        if rec.get("type") != EXTERNAL_SPEECH_TYPE:
            continue
        wall = _wall_ms(rec.get("entry_id"))
        t = _entity_time(wall) if wall is not None else None
        if t is not None:
            speech_times.append(t)
        else:
            # Unplaceable in entity time: it can only count as "otherwise".
            speech_times.append(float("nan"))

    access_times = sorted(first_access.values())
    spoke_after = 0
    attributed: set[int] = set()
    for i, start in enumerate(access_times):
        end = start + float(window_s)
        if i + 1 < len(access_times):
            end = min(end, access_times[i + 1])
        hit = False
        for j, t in enumerate(speech_times):
            if t == t and start <= t < end:  # t == t is False for nan
                attributed.add(j)
                hit = True
        if hit:
            spoke_after += 1
    heard = len(heard_keys)
    accessed = len(first_access)
    values = (
        heard,
        accessed,
        spoke_after,
        len(speech_times) - len(attributed),
        accessed / heard,
    )
    return dict(zip(OPERATOR_SPEECH_READOUT_FIELDS, values))
