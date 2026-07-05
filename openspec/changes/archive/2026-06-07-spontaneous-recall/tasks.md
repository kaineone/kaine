## 1. Cue-based recall trigger

- [x] 1.1 In `kaine/modules/mnemos/module.py` `on_workspace`, derive a cue from
      the snapshot (reuse `_serialize_snapshot`); when non-empty and the recall
      cooldown has elapsed, call `recall(cue)` (which publishes `mnemos.recall`)
      BEFORE storing the snapshot.
- [x] 1.2 Add a monotonic-clock cooldown (`recall_cooldown_s`, sensible default)
      so recall fires at most once per window; skip when no cue.
- [x] 1.3 Do NOT gate recall on `snapshot.inhibited` (recall is cognition).
      Keep the per-tick store unchanged.
- [x] 1.4 Add ctor kwargs `recall_on_workspace` (default True) and
      `recall_cooldown_s`; default on in code; report the `[mnemos]` knobs for
      the operator (do not edit config/kaine.toml).

## 2. Tests (fakes only — no live boot)

- [x] 2.1 Cued experiential tick + cooldown elapsed → recall called + one
      `mnemos.recall` published.
- [x] 2.2 Rapid ticks → recall at most once per cooldown window.
- [x] 2.3 No cue → no recall.
- [x] 2.4 Inhibited cued tick (cooldown elapsed) → recall still fires.
- [x] 2.5 Store still occurs every experiential tick (recall on or off).
- [x] 2.6 `recall_on_workspace=False` → store-only behavior (no recall),
      matching prior behavior.

## 3. Verify

- [x] 3.1 Full suite green — no skips/xfails added; fix root causes.
- [x] 3.2 `openspec validate "spontaneous-recall"` passes.
