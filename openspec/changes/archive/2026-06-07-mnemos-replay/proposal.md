## Why

`KAINE_Paper_v4.md` §3.3.2 / §3.3.5 require Mnemos to **participate in replay**:
during offline consolidation it re-injects selected memory traces into the
workspace for re-processing by other modules, and affect intensity tags memories
and biases recall. Today Mnemos recalls-before-store correctly, but recall
publishes **metadata only** (counts, not the traces), there is **no re-injection
path**, and although the storage schema has an `affect` field, **nothing populates
it** in the live loop.

Replay is the heart of the paper's consolidation model and a prerequisite for the
Hypnos restructure (`hypnos-restructure`) and Phantasia scenario seeding.

## What Changes

- **Affect tagging:** Mnemos subscribes to `thymos.state` and caches the latest
  affect; when storing a memory, it tags the trace with that affect (intensity +
  VAD). Recall continues to bias by affect intensity.
- **Replay re-injection:** add a replay method that, given a selection policy
  (affect intensity × recency, following emotionally-significant-memory
  preferential replay), publishes selected traces as `mnemos.replay` events that
  the workspace processes during maintenance. These carry the trace content for
  re-processing (Nous re-evaluates, Thymos re-appraises, Eidolon observes,
  Phantasia extends) — emitted **only during an active Hypnos replay window**. If
  called outside such a window, `replay()` refuses to emit events and raises a
  precondition error rather than publishing silently.
- **Redact-content option:** a `redact_content` flag (default on) controls what
  the sidecar replay observer receives. When enabled, the observer sees only memory
  IDs, not the text of replayed traces, keeping memory content out of operational
  logs.
- **Replay cue for Phantasia:** each `mnemos.replay` doubles as the seed cue
  Phantasia uses to roll out scenarios.
- `[mnemos]` config gains `[mnemos.replay]`: `selection_top_k`,
  `affect_weight`, `recency_weight`, `redact_content` (default `true`).

## Capabilities

### New Capabilities

- `mnemos-replay`: affect-tagging on store, affect/recency replay selection, and
  workspace re-injection of memory traces during maintenance.

### Modified Capabilities

None expressed as deltas (recall-before-store unchanged; this adds tagging +
replay).

## Impact

- **Depends on:** `mnemos` (shipped), `thymos` (affect state). Drives
  `hypnos-restructure` (phase 2/3) and `phantasia-dreamerv3` (replay cue).
- **Repo:** updates `kaine/modules/mnemos/`, tests, `config/kaine.toml`.
- **Privacy:** replay traces are stored memory content (already derived, not raw
  sense data); they re-enter the workspace only during the maintenance window with
  external perception suspended (paper §3.3.5).
