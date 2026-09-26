## Why

The paper and the poster say the rate of conscious access is not fixed: it sits at the
resting P3b rate (~3.33 Hz) and rises toward the 10 Hz processing rate when predictions
fail or modules report something salient, as arousal and surprise speed access in the
brain. The code does not do this. `[cycle].experiential_rate_hz` is a fixed 3.333 Hz that
only the operator's rate control changes, and the shipped config says so ("modelling that
variability ... is deliberate future work"). Thymos arousal is already driven by
perceptual surprise, but nothing connects it, or the salience of what modules report, to
the broadcast rate.

The neuroscience gives the link. The P3 is read as the cortical signature of the locus
coeruleus–noradrenaline (LC-NE) phasic response to salient, task-relevant or unexpected
events (Nieuwenhuis, Aston-Jones & Cohen 2005). LC-NE runs in a tonic mode tracking arousal
and a phasic mode triggered by salient events (Aston-Jones & Cohen 2005), and phasic bursts
reset and re-engage cortical networks (Bouret & Sara 2005). An innate arousal-to-access
coupling is therefore grounded, not a hardwired behaviour, and what drives it stays
emergent: arousal comes from Thymos's own appraisal of surprise, and salience comes from
the modules' own reports.

## What Changes

- The experiential (conscious-access) rate becomes adaptive between a **resting rate** (the
  existing `experiential_rate_hz`, 3.333 Hz) and a **ceiling** equal to the processing rate
  (10 Hz: every tick broadcasts).
- Each tick the cycle computes an **access drive** in [0, 1] from two parts:
  - **tonic**: Thymos arousal above its resting baseline, normalised to [0, 1];
  - **phasic**: the highest salience among this tick's module reports above a floor,
    normalised to [0, 1], held as a peak that decays with a subjective-time constant.
  The drive is the larger of the two. The effective rate is
  `resting + (ceiling − resting) × drive`.
- The drive and the effective rate are published on every `cycle.tick` event and in
  `runtime.json`, and Nexus shows both the resting and the effective rate.
- New `[cycle.access_rate]` config: `enabled` (ships **true**, matching the paper),
  `salience_floor`, `phasic_decay_s`, `baseline_arousal`. With `enabled = false` the cycle
  is a fixed-rate cycle at the resting rate (now the configured rate; see the bug fix below).
- The operator's rate control and fork timing profiles keep setting the **resting** rate;
  adaptation never goes below it or above the processing rate.
- Deterministic mode stays deterministic: the drive is a pure function of the tick's events,
  the affect snapshot and subjective time.
- The shipped config comment and the docs describe the adaptive rate as current behaviour.
- **Bug fix:** the promotion accumulator clamped to 1.0 before subtracting, dropping the
  fractional carry, so the shipped 3.333 Hz resting rate actually broadcast at 2.5 Hz.
  It now keeps the carry, so the resting rate is the configured rate.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `cognitive-cycle`: adds adaptive conscious-access rate requirements.

## Impact

- `kaine/cycle/engine.py` (drive and effective rate before `_advance_experiential`,
  telemetry), `kaine/cycle/access_rate.py` (new, pure drive computation),
  `kaine/cycle/__main__.py` (wiring the affect provider and config), Nexus rate display.
- `config/kaine.toml`, `docs/processes/cognitive-cycle.md`, `docs/configuration.md`.
- Research: runs after this change differ from earlier fixed-rate runs; the run manifest's
  `config_digest` and `git_sha` distinguish them, and `[cycle.access_rate].enabled = false`
  reproduces the fixed-rate behaviour.
- Not in scope: the poster's further claim that the 10 Hz processing rate also rises with
  arousal. That is a separate decision (host headroom, alpha-frequency evidence) and is
  recorded as an open question.
