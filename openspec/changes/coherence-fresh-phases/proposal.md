## Why

The oscillatory coherence layer (off by default) rewards modules for not publishing. A module's oscillator advances only when that module publishes an event, but the cycle appends every module's current phase to its sliding window on every tick. Between events the phase is frozen, so a module that publishes less than once per `plv_window` ticks (Soma at 1 Hz, Audition per utterance, any module with no history) contributes a constant series, and two constant series have a phase-locking value of exactly 1. Such modules receive the maximum coherence factor, `coherence_ceiling`, whatever their rhythm. A source alone in its cohort is also mapped from PLV 1.0 and boosted to the ceiling. Both are measurement artefacts, not evidence of phase locking. The mathematics review of 2026-10-08 found this.

## What Changes

- **Only fresh phases count.** The scorer records, for each module and tick, whether the phase changed since that module's previous sample (a module's phase changes only when it publishes). The phase-locking value of a pair is computed over the ticks in the window where both modules' samples are fresh.
- **Too little evidence is neutral.** When a pair has fewer than `MIN_FRESH_SAMPLES` (3) jointly fresh ticks in the window, the pair contributes the neutral PLV, the value that maps to a factor of exactly 1.0, `(1 - floor) / (ceiling - floor)` clipped to `[0, 1]`. A source with no informative partner, including a source alone in its cohort, therefore receives a factor of 1.0, neither boosted nor attenuated.
- The bounded gain map `factor_from_plv` is unchanged, and the disabled path stays bit-for-bit identical (the scorer is never constructed).

## Capabilities

### Modified Capabilities

- `oscillatory-binding`: the coherence multiplier counts only fresh phase samples and is neutral without evidence.

## Impact

- **Code:** `kaine/workspace/coherence.py`.
- **Behaviour:** none in any shipped profile, since `[oscillator].enabled` is false everywhere. With the layer on, rarely publishing modules lose an unearned boost of up to 25 percent, and the oscillatory ablation's results change.
- **Docs:** `docs/08-cognitive-cycle/global-workspace.md` describes the freshness rule.
- **Paper:** Appendix A.1 states the rule.
