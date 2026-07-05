## Why

The evaluation sidecar is the architecture-thesis instrument — it is how we
measure whether the cognitive architecture changes behavior versus a bare LLM.
On the 2026-06-03 live boot only **2 of 9** observers populated their cards
(`proactive_audit`, `affect_correlation`). The rest were empty, for three
distinct reasons — two of them real bugs in the most research-critical
observers:

1. **`trajectory` and `attribution` read `workspace.broadcast` through the wrong
   decoder.** Syneidesis publishes the broadcast as `{snapshot:<json>, timestamp,
   source}` (verified live), but these observers extend `StreamSubscriberObserver`,
   which decodes entries via the standard `Event` schema (`_decode_event` expects
   `salience`/`type`/`payload`). Every broadcast entry therefore fails to decode
   and is skipped as malformed — `handle()` is never called, so nothing is ever
   written, despite thousands of broadcasts per session. The canonical consumer
   path is `bus.subscribe_workspace()` (used by every module via
   `BaseModule._workspace_loop` → `_snapshot_from_payload`); the observers must
   use it too. `trajectory.handle` already reads the right snapshot fields
   (`tick_index`, `selected`, `salience_scores`); it just never receives them.

2. **`memory_probes` and `eidolon_accuracy` never instantiate.** The registry
   only builds them when a `memory_source` and `cognitive_query_client` are
   supplied (`registry.py:161,174`), but the cycle entrypoint constructs the
   sidecar with only the thymos/sleep providers (`cycle/__main__.py:232`). That
   is why the live log read "sidecar started with 7 observers" against 9 enabled
   flags. The entrypoint is the single allowed coupling point and already builds
   provider adapters (e.g. `_thymos_state_factory`) without the sidecar importing
   `kaine.modules.*`; it must build memory/cognitive adapters the same way.

3. **Expected-empty (not in scope here):** `voice_tracking` follows `hypnos.out`
   and `sleep_snapshots` needs a sleep cycle — both dark because Hypnos is off,
   working as designed. `ab_divergence` is dark for a different reason (the
   speech event lacks the user-input text it needs) and is fixed in the
   `condition-language-organ` change, which already touches that payload.

Without (1) and (2), the trajectory record (the literal record of cognition) and
the memory/identity probes are blind — the meter is broken before the experiment.

## What Changes

- Add a `WorkspaceSubscriberObserver` base that consumes `workspace.broadcast`
  via `bus.subscribe_workspace()` and dispatches the **decoded snapshot payload**
  to `handle()`. `TrajectoryRecorder` and `AttributionRecorder` SHALL extend it
  instead of `StreamSubscriberObserver`. Their existing field reads are unchanged.
- The cycle entrypoint SHALL supply the sidecar with a `memory_source` (Mnemos-
  backed, best-effort age sampling) and a `cognitive_query_client` (recall from
  Mnemos, then ask the LLM — a memory-augmented answer distinct from the bare
  baseline), built as entrypoint adapters (no `kaine.modules.*` import inside
  `kaine.evaluation`), so `memory_probes` and `eidolon_accuracy` instantiate when
  enabled. (Done after `condition-language-organ` landed.)
- No change to `proactive_audit`/`affect_correlation` (already correct), to
  `voice_tracking`/`sleep_snapshots` (correctly Hypnos-gated), or to
  `ab_divergence` (fixed in `condition-language-organ`).
- The sidecar's isolation invariant (no `kaine.modules.*` import) is preserved.

## Capabilities

### Modified Capabilities

- `evaluation-sidecar`: workspace-following observers consume the broadcast via
  the canonical `subscribe_workspace` decoded-snapshot path (not the standard
  Event decode), so `trajectory` and `attribution` record again; and the
  entrypoint wires `memory_source` + `cognitive_query_client` so `memory_probes`
  and `eidolon_accuracy` instantiate.
