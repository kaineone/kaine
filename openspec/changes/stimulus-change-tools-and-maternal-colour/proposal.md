## Why

This change packages five small, mutually supportive stimulus and recovery
services that the entity uses while the larger maternal-voice and stimulus-control
surfaces settle:

- Maternal loudness/attenuation must be checkable against a 6 dB baseline before a
  run accepts its maternal stream.
- Hearing-stage gain is a gate (1/5 and following), not an open range: the gain colour
  names the gate the stage is passing.
- Added sounds are optional and planned, so a baseline run contains exactly the
  planned additions and no implicit ones.
- A real-time interrupt is a no-op until stirring is implemented, so it cannot
  become an accidental act path.
- Freeze recovery needs its own registry and restart path, so a frozen entity can
  be resumed without re-running the whole boot.

### What Changes

1. Maternal loudness/attenuation config check with a 6 dB baseline test.
2. Hearing stage gain colour as gate 1/5 etc.
3. Optional planned added sounds only.
4. Real-time interrupt is a documented no-op until stirring is implemented.
5. Freeze-recovery registry and restart.

### Capabilities

### New Capabilities
- `freeze-recovery`: a registry of frozen entities and a restart path that
  resumes them without a full boot.

### Modified Capabilities
- `audition`: maternal loudness/attenuation config check and 6 dB baseline test.
- `maternal-voice`: optional planned added sounds and hearing stage gain colour gates.
- `stimulus-control`: real-time interrupt remains a no-op until stirring exists.

### Impact

- Code: config checks, hearing-stage gain naming, optional added-sound manifest, no-op
  interrupt, freeze-recovery registry and restart command. No change to the entity's
  stimulus actions in this change.
- Docs: this package and a short operator note.
- Tests: config baseline, gate colour, planned-sound manifest, no-op interrupt,
  freeze registry.

## Estimate (LLM-agent terms)

Size S. Docs-first; code follows after review.
