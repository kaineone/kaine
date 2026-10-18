## 1. Implementation

- [ ] 1.1 Add `stimulus_source_seconds` to the stage record (defensive coerce, absent means unrecorded) and have the gate runner record the stimulus source clock's reading on every tick
- [ ] 1.2 Resume the stimulus source clock from `stimulus_source_seconds` at boot, falling back to the awake-time offset when absent, and record the resumed offset in the run descriptor
- [ ] 1.3 Accrue awake time since the last tick and record the stimulus time at gate shutdown, synchronously and only when a tick would run, then persist the stage
- [ ] 1.4 Tests: restart continuity of stimulus time (no jump back, no advance over downtime, old-stage fallback), shutdown accrual (no loss at a clean restart, no double count after a crash, no write after maturation, cancelled task), and the boot wiring
- [ ] 1.5 Docs: `docs/06-operation/development.md`
