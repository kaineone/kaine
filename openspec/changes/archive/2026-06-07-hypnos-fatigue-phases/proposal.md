## Why

`KAINE_Paper_v4.md` §3.3.5 restructures Hypnos maintenance around physiological
sleep pressure. Today Hypnos fires on a wall-clock timer with no awareness of
substrate load. The paper specifies five ordered phases; the first and most
structurally important are: (1) fatigue-triggered entry, (2) phase reorder/rename
to the paper's five, (3) global activation downscaling + perception suspension
during replay, and (4) wiring the Phase-1 oscillator frequency-reduction call.

This change lands Phase 4 (no high-risk dependencies). The consolidation
integrations that require `nous-pymdp-swap` + `phantasia-dreamerv3` +
`mnemos-replay` are separated into `hypnos-consolidation`.

## What Changes

- **Trigger:** Hypnos subscribes to `soma.fatigue` and triggers a maintenance
  cycle on `crossed == true`. The existing `interval_seconds` becomes a
  **max-interval safety net** (fires even if fatigue never crosses). Deferral,
  non-interruptibility, and operator-freeze preemption are retained.
- **Phase 1 — light consolidation:** weak traces decay; strong traces tagged for
  deep consolidation. **Oscillator frequency reduction call**: invoke
  `ModuleOscillator.set_frequency(scale)` across all active modules (a no-op hook
  until `oscillatory-layer` ships; once it ships, modules slow their LIF
  oscillators during sleep, matching the paper's sleep-state frequency reduction).
- **Phase 2 — deep consolidation + downscaling:** global activation downscaling
  (Tononi & Cirelli 2014) — scale all memory activation weights by
  `downscale_factor` preserving relative ordering; open `replay_window`; suspend
  external perception (freeze/locus machinery); drive `mnemos.replay` re-injection
  (no-op stub until `mnemos-replay` ships).
- **Phases 3–5 stubs:** associative replay (phase 3), affective + fatigue reset
  (phase 4), voice alignment (phase 5) wired as no-op stubs behind their
  respective feature flags so the correct ordering is defined now.
- **Phase 4 — fatigue reset:** explicitly resets Soma's fatigue accumulator after
  affective-reset.
- `[hypnos.consolidation]` config: `fatigue_triggered` (bool), `downscale_factor`,
  `replay_window_s`; `interval_seconds` retained as safety net.

## Capabilities

### New Capabilities

- `hypnos-fatigue-phases`: fatigue-triggered five-phase Hypnos with global
  activation downscaling, perception suspension during phase-2 replay window, and
  the Phase-1 `ModuleOscillator.set_frequency` hook (no-op until
  `oscillatory-layer` merges).

## Impact

- **Depends on:** `hypnos` (shipped), `soma-forward-model-fatigue` (`soma.fatigue`
  trigger).
- **No high-risk deps:** `mnemos-replay`, `phantasia-dreamerv3`, and
  `nous-pymdp-swap` are each behind stub flags; this change lands independently.
- **Welfare:** maintenance becomes emergent (sleep pressure driven), matching the
  paper's right-to-offline-maintenance; perception suspended during replay protects
  privacy boundary. Freeze/operator supervision unchanged.
- **Repo:** updates `kaine/modules/hypnos/`, tests, `config/kaine.toml`.
