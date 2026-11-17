## 1. Sensor availability and feed health

- [ ] 1.1 Document the camera/sensor availability fallback contract, including
      the degraded mode name and its observable signal.
- [ ] 1.2 Define feed error counters for live audition feeds (open failure,
      read timeout, decode failure, dropped window, queue overflow).
- [ ] 1.3 Define structured sensor-health warnings for non-fatal degradations,
      including sensor identity, failure mode, and active fallback.
- [ ] 1.4 Add operator notes stating that counters and warnings are
      diagnostics only and trigger no automatic retry.

## 2. Auditory surprise sanity checks

- [ ] 2.1 Specify finiteness, range, and magnitude checks for auditory
      prediction-error and change scores before they enter running means.
- [ ] 2.2 Define exclusion and counting behavior for invalid surprise values.
- [ ] 2.3 Verify sanity checks do not alter valid score values or normal alerts.

## 3. Arousal-to-window guard

- [ ] 3.1 Specify guards for NaN/inf arousal, out-of-range arousal, malformed
      window ranges, and empty attended windows.
- [ ] 3.2 Document minimum frame count and non-empty-window guarantees.
- [ ] 3.3 Preserve existing documented narrowing behavior for valid inputs.

## 4. Operator consent and verification

- [ ] 4.1 Document the no-runtime-retries-without-consent rule and its review
      checklist.
- [ ] 4.2 Define how degraded capture is reported and how consent is recorded.
- [ ] 4.3 Add validation/gate steps once implementation begins.
