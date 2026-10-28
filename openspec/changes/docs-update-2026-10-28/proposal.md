## Why

A documentation audit against the code merged since 2026-10-19 found pages that no longer match it:
- The sleep panel's description says the sleep module names a trigger only for a state-cycle rest or a requested sleep. Since sleep-trigger-per-sleep every sleep records one. The panel itself had no label for three of them, so a fatigue, maintenance-request or emotion-regulation sleep showed `not known`.
- Six pages still say voice alignment trains on preference pairs. Since voice-adaptation-idle, `preference_source` accepts only `"none"`, and the phase trains nothing.
- The sleep chapter leaves out the state-cycle rest hold and housekeeping.
- The development page still speaks of a colour ramp, says colour is full after the last hearing step, and omits the hearing-stage event's `dwell_seconds`.
- The language page lists a persona name the organ no longer receives, and mentions a "situation is due" rule that does not exist.
- A few pages still use "Dashboard" as a proper noun, left over from the rename.

## What Changes

- Add the `fatigue`, `maintenance request` and `emotion regulation` labels to the sleep panel, with harness cases.
- Correct the pages listed above against the code.
- Tick the documentation tasks of graded-intensity-alert-phasic (3.3) and broadcast-context (4.1), which the audit found already done, and archive both changes.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: the sleep panel names every recorded trigger.

## Impact

`kaine/dashboard/static/dashboard_sleep.js`, `tests/js/dashboard_sleep_harness.js`, and documentation pages. No change to the cycle or the modules.
