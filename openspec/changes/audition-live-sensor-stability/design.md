# Design — audition live-sensor stability

## Context

Live audition consumers range from the physical microphone (`LiveMicrophone`) to
seeded/playlist feeds and external callers feeding `Audition.process_audio`.
Each path assumes frames arrive; a failure (missing device, read timeout, decode
error, queue overflow) currently surfaces inconsistently, and some failures
could corrupt running statistics (NaN prediction error, invalid window lengths).
This package defines the stability contract without changing those consumers yet.

## Goals / Non-Goals

**Goals:**
- Define a single degraded-mode contract for unavailable or failing sensors.
- Make feed failures observable through counters and structured operator
  warnings.
- Bound and validate auditory surprise inputs before they affect running means,
  intensity, or alerts.
- Harden `arousal_to_window` against invalid arousal and window-range inputs.
- Document that runtime retries require explicit operator consent.

**Non-Goals:**
- No source edits in this package.
- No automatic retry, reconnect, or alternate-device selection at runtime.
- No new perception capability or change to normal-window behavior.
- No reconfiguration of capture defaults.

## Decisions

1. **Fallback is named, not invented.** Camera/sensor availability fallback
   names an existing degraded mode (no capture, last known good state where
   applicable, or an explicitly disabled sensor). No new fallback source is
   allocated.
2. **Counters are read-only diagnostics.** Feed error counters increment on
   failure and are never used as retry triggers or health thresholds for
   automatic action.
3. **Sanity checks are exclusion, not correction.** Non-finite or out-of-range
   surprise values are excluded from running statistics and counted; they are
   never clamped into a plausible value silently.
4. **Guard preserves documented behavior.** `arousal_to_window` already clips
   arousal to `[0, 1]`; the guard additionally rejects malformed ranges and
   guarantees a non-empty attended window.
5. **Consent boundary.** A retry of a failed live capture requires an explicit
   operator action recorded in operator notes; the runtime may not retry on its
   own schedule.

## Risks / Trade-offs

- Adding guards can mask environmental misconfiguration unless warnings are
  visible; operator notes must therefore accompany every guard.
- Skipping automatic retries means an operator may need to intervene manually
  to restore capture after a transient failure.
- Counting excluded values changes reported statistics; those counts must be
  part of run review.
