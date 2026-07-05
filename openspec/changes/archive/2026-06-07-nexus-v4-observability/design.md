# Design — Nexus v4 observability

## Principle: observational only

Nexus is the operator's read-only window. Nothing in this change publishes to the
bus, mutates module state, or alters selection — it only subscribes, aggregates,
and renders. Every new surface degrades to empty/absent when its source module is
disabled (the shipped default) so the dashboard is never broken by an off module.

## 1. Dark module streams

`kaine/nexus/__main__.py` `DEFAULT_DIAGNOSTICS_STREAMS` gains `empatheia.out`,
`phantasia.out`, and `workspace.broadcast` (the last carries
`metadata['coherence']`). The BusBridge already relays whatever is in that list
to the SSE endpoint; adding the streams is sufficient for the live event feed.
Streams for disabled modules simply produce no events.

## 2. Coherence (PLV) chart

PLV lives in `WorkspaceSnapshot.metadata['coherence']`, copied into the
`workspace.broadcast` payload by the cycle engine. `nexus.js` gains a uPlot series
(`chart-coherence`) fed from the broadcast SSE handler, mirroring the existing
affect/rates charts. When the oscillator is disabled the key is absent and the
chart shows a flat/empty series — no error. `diagnostics.html` gets the chart
container guarded by a "requires oscillator enabled" caption.

## 3. Fatigue trend chart

`soma.report` carries `fatigue_value`; `soma.fatigue` fires on threshold
crossings. `nexus.js` adds a fatigue time-series from the `soma.out` SSE handler,
with the `fatigue_maintenance_threshold` drawn as a reference line so the operator
sees how close the substrate is to triggering maintenance.

## 4. Evaluation-tab observer surfacing (the unmet requirement)

`evaluation-observers` spec already requires welfare and prediction-error counts
to surface on Nexus. Wiring path:
- `build_evaluation_router(...)` gains an optional `registry` (the
  `SidecarRegistry`) argument; `nexus/__main__.py` passes the live registry.
- The evaluation router exposes the observers' public properties
  (`welfare_observer.{unmaintained_fatigue_count,sustained_extreme_vad_count,
  replay_overload_count}`, `prediction_error_observer.event_counts` and its
  per-source mean/p95/p99) via the evaluation JSON.
- `nexus_tab.py` `_aggregate()` additionally reads the `welfare/`,
  `prediction_error/`, and `coherence/` observer JSONL directories (so historical
  rollups survive a Nexus restart even when the live registry is absent, e.g. a
  cold dashboard against a stopped cycle).
- `evaluation.html` gains three sections: **Welfare (Gray-Zone)** with the three
  §5.5 counts, **Prediction error** with per-source sliding-window stats, and
  **Coherence** with the latest/mean PLV. Each renders "no data" when its source
  is absent.

When neither a live registry nor JSONL exists, the sections render "no data" —
never an error.

## 5. FaithfulRenderer templates

Add `_t_*` templates (registered in `TEMPLATES`) for: `nous.timeout`,
`audition.prosody`, `vox.synthesized`, `mnemos.replay`,
`hypnos.sleep.started`, `hypnos.sleep.completed`, `hypnos.association`,
`eidolon.self_model`. Extend `_t_soma_report` to include `prediction_error` and
`fatigue_value`, and `_t_chronos_report` to include `temporal_prediction_error`.
Each template renders human-readable text, never a raw dict, and must not leak raw
sense content (e.g. `mnemos.replay`/`eidolon.self_model` render IDs/labels and
numeric attributes, not transcript text — consistent with the redaction and
zero-raw-persistence invariants).

## 6. Encryption-status probe

A health-board probe reports whether `[security.state_encryption]` is enabled and
a key is resolvable (without ever reading or logging the key) — `at-rest:
encrypted` / `at-rest: plaintext (disabled)` / `enabled but NO KEY (fail-closed)`.
Mirrors the existing dependency-probe pattern in `health.py`.

## 7. Forks panel + cleanup

The forks table renders the `nous.merge_warning` flag (a ⚠ marker + tooltip) when
present on a merge snapshot. `PrivacyFilter.CONTENT_FIELDS` drops the dead
`narsese` entry (Nous no longer emits it post-pymdp-swap); `nous.belief`'s
human-readable `statement` field remains covered by existing content rules.

## Testing

- Stream test: `empatheia.out`/`phantasia.out`/`workspace.broadcast` are in the
  diagnostics stream set.
- FaithfulRenderer: each new event type renders via its NAMED template (not the
  fallback), and the report templates include the new fields; no raw transcript
  text in `mnemos.replay`/`eidolon.self_model` output.
- Evaluation tab: given scripted observer state/JSONL, the welfare/prediction-error/
  coherence sections populate; given none, they render "no data" without error.
- Encryption probe: enabled+key → encrypted; enabled+no key → fail-closed flag;
  disabled → plaintext.
- Privacy: `narsese` removed; existing content redaction unaffected.
- All new panels render with their source module disabled (graceful degradation).

## Out of scope

Re-skinning the dashboard; auth/multi-user; historical long-term storage beyond
the existing sidecar JSONL; charting individuation runs over time (a single
latest-result panel suffices for v1).
