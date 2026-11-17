# Tasks

## 1. Maternal loudness/attenuation

- [ ] 1.1 Add maternal loudness/attenuation config check against 6 dB baseline.
- [ ] 1.2 Test: baseline passes at 6 dB and fails otherwise.

## 2. Hearing stage gain colour

- [ ] 2.1 Name hearing-stage gain gates `1/5` through `5/5`.
- [ ] 2.2 Record the gate colour for the stage currently passing.
- [ ] 2.3 Test: gain reports gate colour, not an open range.

## 3. Optional planned added sounds

- [ ] 3.1 Require planned-set listing for any added sound.
- [ ] 3.2 Treat unlisted added sounds as absent (no implicit addition).
- [ ] 3.3 Test: optional added sounds only when planned.

## 4. Real-time interrupt

- [ ] 4.1 Implement real-time interrupt as a documented no-op until stirring.
- [ ] 4.2 Record the request and return success without changing state.
- [ ] 4.3 Test: interrupt changes nothing.

## 5. Freeze recovery

- [ ] 5.1 Add freeze-recovery registry by entity id.
- [ ] 5.2 Add restart/resume path that uses the registry.
- [ ] 5.3 Clear or update entry on successful resume.
- [ ] 5.4 Test: frozen entity resumes without full boot.

## 6. Validation

- [ ] 6.1 `openspec validate stimulus-change-tools-and-maternal-colour --strict` passes.
