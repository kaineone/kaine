## Design: stimulus change tools and maternal colour

### Context

These are small correctness and recovery surfaces around stimulus and maternal audio.
They must be easy to audit, default-safe, and independent of the larger stirring
implementation.

### Decisions

#### D1. Maternal loudness/attenuation config check

The maternal stream's configured loudness and attenuation are checked against a
6 dB baseline in tests. A run that cannot satisfy the baseline fails the check
before playback starts.

#### D2. Hearing stage gain colour as gate 1/5 etc

Hearing-stage gain is described as a gate colour: `1/5`, `2/5`, through `5/5`.
The colour names the gate the stage is passing and is used in records and review
output. No open gain range is reported.

#### D3. Optional planned added sounds only

Added sounds are optional and must be listed in the run's planned set. A run does
not pick up implicit or unplanned additions; missing entries mean the addition is
absent rather than defaulted.

#### D4. Real-time interrupt no-op until stirring

Until stirring is implemented, a real-time interrupt command is a documented
no-op: it records the request, changes nothing, and returns success. It is not wired
to any act path.

#### D5. Freeze-recovery registry and restart

A frozen entity is registered by id with the reason and timestamp. Restart (or
resume) looks up the registry and resumes that entity without a full boot, clearing
or updating the registry entry on success.

### Risks

- A no-op interrupt may look like a stalled path; it must be labelled in records.
- Freeze recovery must not bypass preservation or welfare checks; those remain
  mandatory before resume.

### Migration

All five are additive and default-safe. Off/missing config keeps existing behaviour.
