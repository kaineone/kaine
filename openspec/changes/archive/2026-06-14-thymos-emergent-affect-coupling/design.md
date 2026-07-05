# Design: emergent affect coupling

## Principle

The speaker's emotion is something the entity **perceives and appraises**, not
something written onto it. Resonance must be an output of the entity's own
appraisal, modulated by its goals, its relationship to the speaker (familiarity),
and its current state — so whether/how the entity is moved emerges.

## Current flow (to remove)

```
audition.emotion ──► _apply_coupling_nudge ──► state.nudged(toward EMOTION_VAD[cat])
                     (bypasses appraisal; DriftSafeguard caps the rate)
```

## New flow

```
audition.emotion ──► record perceived-emotion signal (category→pleasantness/intensity,
                     familiarity-weighted, timestamped)        [transient, decays]
                          │
cognitive tick ──► _score_snapshot(snapshot) folds the *current* perceived signal
                   into the appraisal dimensions ──► classify ──► existing bounded
                   appraisal→state nudge (the entity's own response)
```

### What enters which appraisal dimension

The `EMOTION_VAD` table is reused only to derive the *perceived other's*
pleasantness/intensity (not as a state target):

- **intrinsic_pleasantness** gains a contribution from the perceived speaker's
  pleasantness (valence sign of `EMOTION_VAD[category]`), weighted by
  `w = compute_coupling(base, familiarity_gain, familiarity, ceiling)` and by the
  decayed recency of the signal. This is the core of resonance: perceiving a
  distressed/joyful other shifts how the entity appraises the moment — but the
  entity's *own* goal-significance, coping, and novelty still co-determine the
  classified emotion and the resulting state nudge.
- **novelty** gains a small contribution from the perceived emotional intensity
  (arousal of `EMOTION_VAD[category]`), so a sudden strong other-emotion reads as
  more salient to appraisal.

Crucially, these are **additive inputs into appraisal**, clamped to the existing
`[-1, 1]` dimension range, and then the *existing* appraisal→state path applies
the (already small, `0.05×`) nudge. There is no path that sets the state toward a
mirror target.

### Decay / boundedness

- The perceived-emotion signal carries a timestamp; its weight decays to zero over
  a short window (config `decay_s`, default ~10 s, mirroring Vox mirroring), so a
  speaker who stops talking stops influencing appraisal.
- Influence is bounded by `coupling_ceiling` (the appraisal-weight clamp), so the
  `DriftSafeguard` rolling-rate machinery is no longer needed and is removed.
- Because the contribution flows through appraisal (not a direct write) and the
  existing drift/hysteresis still pulls state toward baseline, sustained extreme
  input cannot pin the dimensional state.

### Familiarity

Unchanged source (`empatheia.agent_model` → familiarity cache, persisted across
fork restore). It now scales how strongly the perceived other-emotion enters
appraisal — you appraise the feelings of those you are close to as more
significant. This is itself a relational, emergent quality.

### Config

`[thymos.coupling]` keys are kept (no migration): `enabled` (ships `false`),
`coupling_base`, `coupling_familiarity_gain`, `coupling_ceiling` become the
appraisal-influence weight parameters; `coupling_max_rate_per_s` is removed
(safeguard gone) — its key, if present, is ignored with a one-line note rather
than erroring, to avoid breaking existing local configs.

## Why not keep it as cited contagion

Emotional contagion (Hatfield, Cacioppo & Rapson 1994) is real and a-cognitive in
humans, so "cite it and keep the direct write" was a legitimate option. The
operator chose emergence: a substrate that *affords* resonance through the
entity's own appraisal is more faithful to the architecture-as-substrate thesis
and avoids predetermining an outcome the research means to observe. The appraisal
route still reproduces contagion-like behavior when the weights are non-zero — it
just isn't hardwired to.

## Test strategy

- Perceiving a positive-valence speaker raises the entity's appraised
  pleasantness (and, downstream, valence) — but only when `enabled`.
- Higher familiarity ⇒ strictly larger appraisal contribution.
- The perceived-emotion contribution decays to zero after `decay_s` with no new
  events (state returns toward baseline via existing drift).
- Disabled ⇒ appraisal is identical to the no-perceived-emotion case.
- No code path writes the dimensional state toward `EMOTION_VAD` directly
  (assert `_apply_coupling_nudge` is gone; appraisal is the only route).
- Familiarity-cache persistence round-trip still holds.
</content>
