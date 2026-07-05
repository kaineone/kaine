## Why

The v4 build added a predictive/affective/social nervous system (forward models,
fatigue, Empatheia, Phantasia, pymdp-Nous, the oscillatory layer, eight sidecar
observers) but the **Nexus operator dashboard was not updated to match it**. An
audit of `kaine/nexus/` against the merged v4 specs found an operator running a v4
entity is blind to most of the new signals:

- **Two of the four new modules are dark:** `empatheia.out` and `phantasia.out`
  are not in `DEFAULT_DIAGNOSTICS_STREAMS`, so the SSE bridge never relays
  `empatheia.social_error` (social surprise) or `phantasia.world_error`
  (world-model surprise).
- **Unmet spec requirement:** `evaluation-observers` SHALL surface
  `prediction_error_observer` and `welfare_observer` counts on Nexus diagnostics.
  The counters exist on `SidecarRegistry` but are not wired into the evaluation
  router or rendered — §5.5 Gray-Zone welfare events are invisible.
- **No coherence view:** the oscillatory layer's PLV in
  `WorkspaceSnapshot.metadata['coherence']` has no chart and is not subscribed to.
- **No fatigue trend:** `soma.fatigue` renders as a text line but the accumulator
  has no time-series gauge — a welfare-critical signal with no trend view.
- **FaithfulRenderer gaps:** `nous.timeout`, `audition.prosody`, `vox.synthesized`,
  `mnemos.replay`, all `hypnos.*`, and `eidolon.self_model` fall back to raw-dict
  rendering; `soma.report` and `chronos.report` templates omit the new fields
  (`prediction_error`, `fatigue_value`, `temporal_prediction_error`).
- **Minor:** `nous.merge_warning` is never shown in the forks panel; the retired
  `narsese` field lingers in the privacy content-field list; encryption status and
  individuation-boundary results are not surfaced.

This change brings Nexus to deep parity with the v4 architecture so the operator
can actually observe a running entity — load-bearing for the operator-supervised
first boot.

## What Changes

- **Live streams:** add `empatheia.out`, `phantasia.out`, and the workspace
  broadcast (for coherence) to the diagnostics SSE bridge.
- **Evaluation tab:** pass the sidecar observer registry into the evaluation
  router; render `welfare_observer` Gray-Zone counts, `prediction_error_observer`
  sliding-window statistics, coherence summaries, and individuation-boundary
  results.
- **Diagnostics charts:** a PLV/coherence time series and a Soma fatigue-accumulator
  trend chart in `nexus.js`/`diagnostics.html`.
- **FaithfulRenderer:** templates for `nous.timeout`, `audition.prosody`,
  `vox.synthesized`, `mnemos.replay`, `hypnos.sleep.started`/`hypnos.sleep.completed`/
  `hypnos.association`, and `eidolon.self_model`; extend `soma.report` and
  `chronos.report` templates with the new v4 fields.
- **Health board:** a state-encryption status probe (enabled/keyed/at-rest).
- **Forks panel:** surface the `nous.merge_warning` flag.
- **Cleanup:** drop the dead `narsese` entry from `PrivacyFilter.CONTENT_FIELDS`.
- Everything read-only/observational; no change to the cognitive loop. New panels
  degrade gracefully when their source module is disabled or absent.

## Capabilities

### New Capabilities

- `nexus-observability`: the operator dashboard's coverage of v4 signals — live
  streams for all modules, coherence and fatigue charts, welfare/prediction-error
  surfacing, encryption status, and graceful degradation when modules are off.

### Modified Capabilities

- `faithful-renderer`: named templates for the remaining v4 event types and the
  new fields on existing report templates.

## Impact

- **Depends on:** all merged v4 changes (the signals exist). No runtime/loop
  behavior change — Nexus is observational.
- **Repo:** `kaine/nexus/` (__main__.py, diagnostics, evaluation router wiring,
  health.py, privacy.py, templates, static js/css), `kaine/faithful/templates.py`,
  `kaine/evaluation/nexus_tab.py`, tests.
- **Privacy:** new panels show derived/numeric signals and IDs only; the
  replay/redaction and zero-raw-persistence invariants are unchanged.
