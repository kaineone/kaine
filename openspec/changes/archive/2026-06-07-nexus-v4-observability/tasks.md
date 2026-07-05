## 1. Dark module streams

- [x] 1.1 Add `empatheia.out`, `phantasia.out`, and `workspace.broadcast` to `DEFAULT_DIAGNOSTICS_STREAMS` in `kaine/nexus/__main__.py`
- [x] 1.2 Test: the diagnostics stream set includes all four new module streams; disabled-module streams produce no events without error

## 2. Coherence (PLV) chart

- [x] 2.1 `nexus.js`: subscribe the `workspace.broadcast` SSE handler to `metadata['coherence']`; add a `chart-coherence` uPlot series (mirror the affect/rates charts)
- [x] 2.2 `diagnostics.html`: coherence chart container with a "requires oscillator enabled" caption; flat/empty when the key is absent
- [x] 2.3 Test: a broadcast carrying `metadata['coherence']` updates the coherence series; absent key → no error

## 3. Fatigue trend chart

- [x] 3.1 `nexus.js`: fatigue time series from the `soma.out` handler (`fatigue_value`), with `fatigue_maintenance_threshold` as a reference line
- [x] 3.2 `diagnostics.html`: fatigue chart container
- [x] 3.3 Test: `soma.report`/`soma.fatigue` events update the fatigue series

## 4. Evaluation-tab observer surfacing

- [x] 4.1 `build_evaluation_router(...)` accepts an optional `registry` (SidecarRegistry); `kaine/nexus/__main__.py` passes the live registry (and restores `attribution` wiring)
- [x] 4.2 Expose `welfare_observer` counts (unmaintained-fatigue, sustained-extreme-VAD, replay-overload), `prediction_error_observer.event_counts` + per-source mean/p95/p99, and latest/mean coherence via the evaluation JSON
- [x] 4.3 `kaine/evaluation/nexus_tab.py` `_aggregate()` also reads `welfare/`, `prediction_error/`, and `coherence/` observer JSONL directories (survives a cold dashboard)
- [x] 4.4 `evaluation.html`: **Welfare (Gray-Zone)**, **Prediction error**, and **Coherence** sections; each renders "no data" when its source is absent
- [x] 4.5 Test: scripted observer state/JSONL populates the three sections; none present → "no data", no error

## 5. FaithfulRenderer templates

- [x] 5.1 Add named templates for `nous.timeout`, `audition.prosody`, `vox.synthesized`, `mnemos.replay`, `hypnos.sleep.started`, `hypnos.sleep.completed`, `hypnos.association`, `eidolon.self_model`
- [x] 5.2 Extend `_t_soma_report` with `prediction_error` + `fatigue_value`; extend `_t_chronos_report` with `temporal_prediction_error`
- [x] 5.3 `mnemos.replay` and `eidolon.self_model` templates render IDs/labels/numeric attributes only — NO raw transcript/sense text
- [x] 5.4 Test: each new event type renders via its NAMED template (not `fallback_template`); report templates include the new fields; no raw content leaks

## 6. Encryption-status probe

- [x] 6.1 Add a health-board probe reporting `[security.state_encryption]` posture (encrypted / plaintext-disabled / enabled-but-no-key fail-closed) WITHOUT reading or logging the key
- [x] 6.2 Test: enabled+key → encrypted; enabled+no key → fail-closed flag; disabled → plaintext

## 7. Forks panel + privacy cleanup

- [x] 7.1 `diagnostics.html` forks table surfaces the `nous.merge_warning` flag (marker + tooltip) when present on a merge snapshot
- [x] 7.2 Remove the dead `narsese` entry from `PrivacyFilter.CONTENT_FIELDS` in `kaine/nexus/privacy.py`
- [x] 7.3 Surface the latest individuation-boundary result in the evaluation tab when present (single latest-result panel)
- [x] 7.4 Test: merge-warning marker shows only when the flag is set; privacy filter still redacts existing content fields

## 8. Verification

- [x] 8.1 Full unit suite green
- [x] 8.2 `openspec validate nexus-v4-observability --strict` clean
- [x] 8.3 No stale pre-v4 references introduced; all new panels degrade gracefully with their source module disabled (committed config still all-modules-false)
- [x] 8.4 Commit (Kaine.One), branch-per-change, merge, archive
