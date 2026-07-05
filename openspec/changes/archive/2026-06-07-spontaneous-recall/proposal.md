## Why

Mnemos stores a memory of the conscious snapshot every experiential tick
(`on_workspace`), but **nothing ever triggers recall** in the live loop (audit
finding #4). `recall(query)` exists and publishes `mnemos.recall` events (which
Thymos already consumes to modulate arousal), yet it is only ever called
explicitly in tests. The entity accumulates experience it cannot spontaneously
remember, so past memory never informs ongoing cognition — a core feedback loop
the paper intends (memory contributing to the continuous recurrent process) is
left open.

## What Changes

- Mnemos performs **cue-based recall in the live loop**: on an experiential
  broadcast with a meaningful cue, it derives a query from the conscious
  snapshot, calls `recall(cue)`, and publishes the recalled memories as
  `mnemos.recall` events — which re-enter the workspace next tick and reach
  Thymos. This closes the store→recall→inform loop.
- **Recall before store**, so the cue retrieves *prior* related memories rather
  than trivially matching the snapshot just stored this tick.
- **Throttled** by a cooldown so recall does not fire every tick (avoiding
  retrieval storms / churn); skipped when there is no meaningful cue.
- **Not inhibition-gated.** Recall is internal cognition (like storing), not an
  outward effector action, so it runs regardless of `snapshot.inhibited` — only
  the *action* layer (speech/effectors) is gated by executive inhibition.
- Optional `[mnemos]` knobs: `recall_on_workspace` (default on) and
  `recall_cooldown_s`; reported for the operator to add.

## Capabilities

### Modified Capabilities

- `mnemos`: in addition to storing, Mnemos spontaneously recalls memories
  related to the current conscious content (cue-based, throttled) and publishes
  them, so recalled context informs ongoing cognition and affect.

## Impact

- **Code**: `kaine/modules/mnemos/module.py` `on_workspace` — add cooldown-gated,
  recall-before-store cue retrieval using the existing `recall()`/publish path.
  No change to `recall()` itself, storage, or Thymos.
- **Tests**: unit tests (fakes) — recall fires on a cued experiential tick and
  publishes `mnemos.recall`; cooldown suppresses repeats; no cue → no recall;
  recall runs even when inhibited; store still happens every tick.
- **Config**: optional `[mnemos].recall_on_workspace` / `recall_cooldown_s`
  (reported, not auto-added).
