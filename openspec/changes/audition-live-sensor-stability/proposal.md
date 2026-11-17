# Audition live-sensor stability

## Why

Live audition feeds (microphone capture, seeded/playlist audio, stimulus feeds,
and the optional perception preview tap) can degrade in ways the current path does
not distinguish from normal silence or expected surprise. A missing camera-style
availability fallback for sensory capture, untracked feed errors, and unchecked
surprise values let a degraded run look like a calm entity. Operators also
currently have no documented contract that says degraded sensor captures are not
retried at runtime without consent. This package is docs-only and fixes that gap
before any implementation lands.

## What Changes

- **Camera availability fallback.** When a live sensor (physical camera or other
  external capture) is unavailable, audition and the perception feed use a
  documented degraded-mode fallback rather than an unhandled exception or a
  silent drop. The fallback is named in operator notes and is observable.
- **Feed error counters.** Live feed errors (open failure, read timeout, decode
  failure, dropped window, queue overflow) are counted and exposed per feed so a
  run's sensor-health state can be reconstructed from logs. Counters are
  monitoring only; they do not trigger any automatic retry.
- **Sensor health warnings.** Non-fatal sensor degradations emit structured
  warnings to operators and research records. Warnings name the sensor, the
  failure mode, and the fallback in effect.
- **Auditory surprise sanity checks.** Auditory prediction-error and change
  scores are checked for finiteness, range, and plausible magnitude before they
  enter the running means, intensity grading, or alerting. Non-finite or out-of-
  range values are excluded and counted rather than poisoning downstream state.
- **Arousal-to-window guard.** `arousal_to_window` and its callers guard arousal
  inputs (NaN, inf, out of range), window range ordering, and frame-count
  minimums so an arousal edge cannot produce an empty or oversized attended
  window.
- **Operator notes and no runtime retries.** Degraded captures are reported and
  await explicit operator consent. The package documents that no runtime code may
  silently retry a failed live sensor capture.

## Capabilities

### New Capabilities

None. This is a stability/hardening package; it documents guards and counters
rather than new perceptual capabilities.

### Modified Capabilities

None. No requirement-level behavior changes are proposed at this stage; any later
requirement change must amend this proposal.

## Impact

- Affected: `kaine/modules/audition/live.py`, `kaine/modules/audition/acoustic.py`,
  perception feed and camera availability surfaces, operator documentation.
- Docs only at this stage: no source edits, no config changes, no audio
  capture, no retries, no runtime behavior change.
- Explicit non-goal: no automatic runtime retries of failed captures.
