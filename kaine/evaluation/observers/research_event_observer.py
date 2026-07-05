# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Curated research event observer (export-eligible).

Subscribes to a curated allowlist of bus streams and writes ONE
privacy-filtered record per relevant event to the ``research_events`` sink
under ``data/evaluation/research_events/``. That directory is the sole
export-eligible mechanism (it is listed in
``kaine.research.submission.METRICS_ONLY_DIRS``).

Privacy design
--------------
This observer is **allowlist-based by construction**, on two independent
levels, so a new content field can never leak by default:

1. Stream/type allowlist — only event types present in :data:`_TAXONOMY`
   ever produce a record. ``audition.transcription`` and
   ``mundus.visual.raw`` are deliberately absent, so they are NEVER logged.

2. Field allowlist — every record is first passed through
   :meth:`PrivacyFilter.filter_for_diagnostics` (stripping ``CONTENT_FIELDS``:
   text, body, content, internal_speech, belief_text, memory_text,
   affect_reason, transcription, user_input, faithful_rendering), then ONLY
   the numeric/categorical keys named in the per-type allowlist are copied
   into the record. Anything not named — including any future content field —
   is dropped.

Plus per-type redactions:
- ``mnemos.recall`` / ``mnemos.replay``: ``text`` dropped via the shared
  ``_REDACTED_DROP`` set (also covered by ``memory_text``/``text`` in
  ``CONTENT_FIELDS``); only memory ids + affect intensity + selection scores.
- ``praxis.action``: ``_sanitize`` strips content/body/stdout.
- ``mundus.proprio``: raw coordinates are NEVER logged; only an opaque
  position hash + region label.

Every record carries ``ts`` (ISO-8601 UTC), ``event_type``, ``source``, and
``tick_index`` / ``incident_id`` when present.

READ-ONLY: never publishes to the bus.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event
from kaine.evaluation._base import BaseObserver, BusReader, WorkspaceSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.modules.praxis.audit_log import _sanitize as _praxis_sanitize
from kaine.privacy_filter import PrivacyFilter

log = logging.getLogger(__name__)

# Memory text drop (mirrors replay_observer._REDACTED_DROP). Belt-and-suspenders
# on top of CONTENT_FIELDS (which already strips `text`/`memory_text`).
_REDACTED_DROP = frozenset({"text"})


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Curated taxonomy.
#
# Maps ``event.type`` -> the allowlisted numeric/categorical payload keys that
# may be copied into the record. Keys present in the (privacy-scrubbed) payload
# but NOT in this set are dropped. Event types not present here produce NO
# record at all. `ts`, `event_type`, `source`, `tick_index`/`incident_id` are
# always added on top (when present) and need not be listed.
#
# This is the implementation of the taxonomy table in
# openspec/changes/research-event-log/design.md.
# ---------------------------------------------------------------------------
_TAXONOMY: dict[str, frozenset[str]] = {
    # --- Cycle ---
    "cycle.tick": frozenset(
        {"slip_ms", "wall_duration_ms", "target_duration_ms", "is_experiential", "error"}
    ),
    "cycle.rates": frozenset(
        {
            "processing_rate_hz",
            "experiential_rate_hz",
            "processing_hz",
            "experiential_hz",
            "tick_count",
        }
    ),
    # volition.intent.* handled by prefix match (see _allowed_fields).
    "volition.intent": frozenset({"kind", "about_tag", "effector"}),
    # --- Prediction / precision ---
    "soma.report": frozenset(
        {"prediction_error", "wellness", "fatigue_value", "alerts"}
    ),
    "topos.report": frozenset({"prediction_error", "horizon"}),
    "phantasia.world_error": frozenset({"error"}),
    "nous.belief": frozenset(
        {"kind", "frequency", "confidence", "expected_free_energy", "elapsed_ms"}
    ),
    "nous.policy": frozenset(
        {"kind", "frequency", "confidence", "expected_free_energy", "elapsed_ms"}
    ),
    "nous.error": frozenset(
        {"kind", "frequency", "confidence", "expected_free_energy", "elapsed_ms"}
    ),
    "nous.timeout": frozenset(
        {"kind", "frequency", "confidence", "expected_free_energy", "elapsed_ms"}
    ),
    # --- Affect / motivation ---
    "thymos.state": frozenset(
        {"state", "drives", "emotion", "emotion_category", "valence", "arousal", "dominance"}
    ),
    "thymos.emotion": frozenset(
        {"category", "scores", "norm_compatibility_available"}
    ),
    "thymos.drive": frozenset({"drive", "value"}),
    "thymos.goal": frozenset({"action", "goal_id"}),
    # --- Perception (derived only) ---
    "audition.emotion": frozenset({"category", "confidence", "scores"}),
    "audition.prosody": frozenset(
        {"f0_mean", "f0_std", "f0_voiced_frac", "rms_mean", "rms_std", "tempo_bpm"}
    ),
    "topos.scene_change": frozenset({"change_scalar"}),
    # NOTE: `audition.transcription` is intentionally ABSENT — never logged.
    # --- Memory / sleep ---
    "mnemos.recall": frozenset(
        {"memory_ids", "max_affect_intensity", "selection_scores", "count", "collection"}
    ),
    "mnemos.replay": frozenset(
        {"memory_ids", "max_affect_intensity", "selection_scores", "count"}
    ),
    "hypnos.sleep.started": frozenset({"trigger", "fatigue_at_trigger"}),
    "hypnos.sleep.completed": frozenset(
        {"phases_completed", "replay_count", "consolidation_summary_counts"}
    ),
    # Organ-level consolidation divergence (content-free aggregates only):
    # breadth (rate) + depth (magnitude) of how the entity's conditioned output
    # diverged from its bare language organ this sleep. NO utterance text — the
    # prompt/chosen/rejected stay in the deny-patterned intent log. `embedder`
    # is the embedder-kind disclosure tag (or null when magnitude is null).
    "hypnos.consolidation_divergence": frozenset(
        {
            "records_scanned",
            "usable_pairs",
            "divergence_rate",
            "divergence_magnitude",
            "embedder",
            "sleep_index",
        }
    ),
    "hypnos.fork": frozenset({"snapshot_id", "parent_ids", "strategy"}),
    "hypnos.merge": frozenset({"snapshot_id", "parent_ids", "strategy"}),
    # --- Self / social ---
    "eidolon.drift": frozenset(
        {"score", "drift_scalar", "significant", "recent_count", "historical_count"}
    ),
    "empatheia.agent_model": frozenset({"agent_label", "familiarity_scalar"}),
    "empatheia.social_error": frozenset({"agent_label", "error_magnitude"}),
    # --- Action ---
    "praxis.action": frozenset(
        {
            "action_family",
            "effector",
            "success",
            "duration_ms",
            "elapsed_ms",
            # Provenance-boundary metadata: a forged/unsigned/replayed act intent
            # dropped before any effector ran. Boolean metadata only — never the
            # signature or payload content — so the boundary is observable in the
            # research log and distinguishable from a whitelist refusal.
            "provenance_rejected",
        }
    ),
    # --- Safety / ops ---
    # Spot's structured freeze annotation (run<->incident cross-link). Field
    # names mirror the durable incident_log transition records (incident_log.py
    # / spot.py). `incident_id` and `tick_index` are lifted to the top level by
    # _build_record; the rest are non-sensitive operational metadata. NO content
    # fields, NO operator paths (free-text is path-scrubbed at the producer).
    "spot.incident": frozenset(
        {
            "transition",
            "module",
            "fault_class",
            "fault_type",
            "reason",
            "source",
            "snapshot_id",
            "byte_size",
            "duration_ms",
            "attempt",
            "attempts",
            "max_attempts",
            "path",
            "outcome",
            "latency_ms",
            "last_good_restored",
            "post_assess",
            "final_snapshot_id",
            "poll_index",
        }
    ),
    # Autonomous safety-net monitor records (kaine.cycle.preservation_monitor).
    # The DivergenceMonitor and WelfareProtectiveMonitor publish these on
    # `preservation.out`; they mirror the durable incident_log records. NO content
    # fields — only operational metadata. `incident_id` and `tick_index` are
    # lifted to the top level by _build_record; the rest are listed here.
    # Handled by the `preservation.*` prefix branch in _allowed_fields.
    "preservation.preserved": frozenset(
        {
            "monitor",
            "transition",
            "reason",
            "preservation_id",
            "snapshot_id",
            "world_model_captured",
            "action",
            "poll_index",
            "distress_threshold",
            "distress_duration_s",
        }
    ),
    "preservation.failed": frozenset(
        {
            "monitor",
            "transition",
            "reason",
            "preservation_id",
            "snapshot_id",
            "world_model_captured",
            "action",
            "poll_index",
            "distress_threshold",
            "distress_duration_s",
        }
    ),
    "preservation.skipped": frozenset(
        {
            "monitor",
            "transition",
            "reason",
            "preservation_id",
            "snapshot_id",
            "world_model_captured",
            "action",
            "poll_index",
            "distress_threshold",
            "distress_duration_s",
        }
    ),
    "welfare.protective_action": frozenset(
        {
            "monitor",
            "transition",
            "reason",
            "preservation_id",
            "snapshot_id",
            "world_model_captured",
            "action",
            "poll_index",
            "distress_threshold",
            "distress_duration_s",
        }
    ),
    "welfare.gray_zone": frozenset({"gray_zone_event"}),  # + numeric scalars passthrough
    "individuation.divergence": frozenset({"divergence_scalar", "significant"}),
    "perception.locus.changed": frozenset({"locus", "changed_by"}),
    "perception.locus.denied": frozenset({"locus_requested", "denied_by", "reason_label"}),
    # mundus.proprio handled specially (position hash + region label only).
    "mundus.proprio": frozenset({"region_label"}),
    "mundus.scene": frozenset({"object_count", "scene_change_scalar"}),
    "mundus.notice": frozenset({"notice_kind"}),
}

# EXACT numeric-field allowlist for welfare gray-zone records. This is the
# closed set of numeric scalars/counters the welfare observer emits across all
# four gray-zone categories (replay_overload, unmaintained_fatigue,
# sustained_extreme_vad, sustained_interoceptive_distress). It is an EXACT match
# (not suffix-matching) so a future field added to a gray-zone payload cannot
# smuggle content into the export-eligible research log by accident — only a
# deliberate addition here lets a new field through.
_WELFARE_NUMERIC_FIELDS = frozenset(
    {
        # replay_overload
        "replay_count_in_window",
        "consolidation_window_s",
        "threshold",
        "replay_overload_count",
        # unmaintained_fatigue
        "seconds_since_crossing",
        "maintenance_window_s",
        "unmaintained_fatigue_count",
        # sustained_extreme_vad
        "seconds_sustained",
        "extreme_vad_duration_s",
        "extreme_vad_threshold",
        "sustained_extreme_vad_count",
        # sustained_interoceptive_distress
        "interoceptive_distress_threshold",
        "interoceptive_distress_duration_s",
        "sustained_interoceptive_distress_count",
    }
)

# Curated streams the observer follows (one cursor each). The specific
# `event.type` strings ride on these `<module>.out` streams.
_CURATED_STREAMS: tuple[str, ...] = (
    "cycle.out",
    "volition.out",
    "soma.out",
    "topos.out",
    "phantasia.out",
    "nous.out",
    "thymos.out",
    "audition.out",
    "mnemos.out",
    "hypnos.out",
    "eidolon.out",
    "empatheia.out",
    "praxis.out",
    "spot.out",
    "perception.out",
    "mundus.out",
    "welfare.out",
    "preservation.out",
    "individuation.out",
)


def _opaque_position_hash(payload: dict[str, Any]) -> str | None:
    """Return a stable opaque hash of avatar coordinates, never the raw x/y/z.

    Operator-controlled avatar coordinates are operator-location adjacent, so
    raw coordinates are NEVER logged. A hash lets research correlate
    "did the avatar move?" without revealing the position.
    """
    coords = []
    for key in ("x", "y", "z"):
        if key in payload:
            coords.append(payload.get(key))
    # Some bridges nest coordinates under "position".
    pos = payload.get("position")
    if isinstance(pos, (list, tuple)):
        coords.extend(pos)
    elif isinstance(pos, dict):
        for key in ("x", "y", "z"):
            if key in pos:
                coords.append(pos.get(key))
    if not coords:
        return None
    raw = ",".join(str(c) for c in coords)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ResearchEventObserver(BaseObserver):
    """Curated, privacy-filtered research event recorder.

    Multi-cursor poll loop over the curated streams (mirrors
    ``WelfareObserver._run``) plus an inner ``WorkspaceSubscriberObserver`` for
    ``workspace.broadcast`` metadata. Writes to a single ``AsyncJsonlSink``.
    """

    name = "research_event_log"

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        poll_interval_s: float = 0.5,
        privacy_filter: PrivacyFilter | None = None,
    ) -> None:
        super().__init__()
        self._bus = bus
        self._sink = sink
        self._poll_interval_s = float(poll_interval_s)
        self._privacy = privacy_filter or PrivacyFilter()
        self._cursors: dict[str, str] = {s: "0" for s in _CURATED_STREAMS}
        self._workspace = _WorkspaceMetadataObserver(bus, sink, self._privacy)

    # --- Lifecycle (also drives the inner workspace observer) ------------

    async def start(self) -> None:
        await super().start()
        await self._workspace.start()

    async def stop(self) -> None:
        await self._workspace.stop()
        await super().stop()

    # --- Main loop -------------------------------------------------------

    async def _run(self) -> None:
        import asyncio

        while not self._stopped.is_set():
            for stream in _CURATED_STREAMS:
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        stream, last_id=self._cursors[stream], count=64, block_ms=0
                    )
                except Exception:
                    log.warning(
                        "research_event_log read failed for %s", stream, exc_info=True
                    )
                    entries = []
                    last_scanned = None
                for entry_id, event in entries:
                    self._cursors[stream] = entry_id
                    try:
                        await self._handle(event)
                    except Exception:
                        log.warning(
                            "research_event_log handler raised on %s / %s",
                            stream,
                            entry_id,
                            exc_info=True,
                        )
                if last_scanned is not None:
                    self._cursors[stream] = last_scanned
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._poll_interval_s
                )
            except asyncio.TimeoutError:
                continue

    # --- Record construction --------------------------------------------

    async def _handle(self, event: Event) -> None:
        record = self._build_record(event)
        if record is None:
            return
        await self._sink.write(record)

    def _build_record(self, event: Event) -> dict[str, Any] | None:
        allowed = _allowed_fields(event.type)
        if allowed is None:
            # Not in the curated taxonomy — never logged (covers
            # audition.transcription, mundus.visual.raw, and anything else).
            return None

        # 1) Strip all CONTENT_FIELDS from the raw payload before extraction.
        scrubbed = self._privacy.filter_for_diagnostics(event)
        payload = dict(scrubbed.payload or {})

        # 2) Per-type pre-redactions.
        if event.type in ("mnemos.recall", "mnemos.replay"):
            for f in _REDACTED_DROP:
                payload.pop(f, None)
        elif event.type == "praxis.action":
            payload = _praxis_sanitize(payload)

        record: dict[str, Any] = {
            "ts": _iso_now(),
            "event_type": event.type,
            "source": event.source,
        }
        if "tick_index" in payload:
            record["tick_index"] = payload.get("tick_index")
        if "incident_id" in payload:
            record["incident_id"] = payload.get("incident_id")

        # 3) mundus.proprio: opaque hash + region label only, NEVER coordinates.
        if event.type == "mundus.proprio":
            pos_hash = _opaque_position_hash(payload)
            if pos_hash is not None:
                record["avatar_position_hash"] = pos_hash
            if "region_label" in payload:
                record["region_label"] = payload.get("region_label")
            elif "region" in payload:
                record["region_label"] = payload.get("region")
            return record

        # 4) welfare gray-zone: keep the label + ONLY the exactly-allowlisted
        # numeric scalar fields. Exact-match (not suffix-match) so a future
        # payload field cannot smuggle content through.
        if event.type == "welfare.gray_zone":
            if "gray_zone_event" in payload:
                record["gray_zone_event"] = payload.get("gray_zone_event")
            for k in _WELFARE_NUMERIC_FIELDS:
                v = payload.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    record[k] = v
            return record

        # 5) Generic allowlist copy — ONLY named keys.
        for key in allowed:
            if key in payload:
                record[key] = payload[key]
        return record


def _allowed_fields(event_type: str) -> frozenset[str] | None:
    """Return the allowlisted field set for an event type, or None if the type
    is not in the curated taxonomy (and so must not be logged at all)."""
    if event_type in _TAXONOMY:
        return _TAXONOMY[event_type]
    # volition.intent.* family (forward-compatible; stream may not yet exist).
    if event_type.startswith("volition.intent"):
        return _TAXONOMY["volition.intent"]
    # spot.incident.* family (cross-linked by incident_id).
    if event_type.startswith("spot.incident"):
        return _TAXONOMY["spot.incident"]
    # preservation.* family (the autonomous safety-net monitors, cross-linked by
    # incident_id). Any forward-compatible preservation.* subtype shares the
    # preserved record's operational allowlist — never any content field.
    if event_type.startswith("preservation."):
        return _TAXONOMY["preservation.preserved"]
    return None


class _WorkspaceMetadataObserver(WorkspaceSubscriberObserver):
    """Inner observer: ``workspace.broadcast`` metadata only.

    Extracts tick_index, inhibited flag, salience scores, and per-entry
    {source, type, salience, causal_parent} — NEVER the entry payload field.
    """

    name = "research_event_log_workspace"

    def __init__(
        self, bus: BusReader, sink: AsyncJsonlSink, privacy: PrivacyFilter
    ) -> None:
        super().__init__(bus, start_id="$")
        self._sink = sink
        self._privacy = privacy

    async def handle(self, entry_id: str, payload: dict[str, Any]) -> None:
        snapshot = payload or {}
        record: dict[str, Any] = {
            "ts": _iso_now(),
            "event_type": "workspace.broadcast",
            "source": "syneidesis",
        }
        if "tick_index" in snapshot:
            record["tick_index"] = snapshot.get("tick_index")
        if "inhibited" in snapshot:
            record["inhibited"] = bool(snapshot.get("inhibited"))
        if "salience_scores" in snapshot:
            record["salience_scores"] = snapshot.get("salience_scores")

        # Per-entry metadata ONLY — never the entry `payload`/content.
        entries_meta: list[dict[str, Any]] = []
        for entry in snapshot.get("selected_events", []) or []:
            if not isinstance(entry, dict):
                continue
            meta: dict[str, Any] = {}
            for k in ("source", "type", "salience", "causal_parent"):
                if k in entry:
                    meta[k] = entry[k]
            if meta:
                entries_meta.append(meta)
        if entries_meta:
            record["entries"] = entries_meta

        await self._sink.write(record)
