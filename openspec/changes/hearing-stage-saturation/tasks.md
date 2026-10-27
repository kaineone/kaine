## 1. Stage owner and watch

- [x] 1.1 Hearing band parameters: saturation window, minimum and maximum dwell; retire `maturation_seconds`; stage edges by stage
- [x] 1.2 `HearingStageState`: decision rule, persistence, thread-safe stage read
- [x] 1.3 The watch drives the state from awake time and audition's learning progress; the affect module exposes it gated on the stage
- [x] 1.4 Tests: saturation advance, d_min, d_max cap, missing reading, window reset, restart, rests

## 2. Readers

- [x] 2.1 Audio stream and visual source read the owner's stage; colour k/5; retire `colour_ramp_seconds`
- [x] 2.2 Boot builds the owner from the stage path and shares it
- [x] 2.3 Tests: filter by stage, colour per stage, boot wiring

## 3. Gate and surfaces

- [x] 3.1 C3 is schedule completion; retire `min_lived_seconds`; wire the owner to the gate
- [x] 3.2 Config defaults and comments, dashboard hearing display, docs and appendix
- [x] 3.3 Tests: C3 held, failing and failing closed; retired key warning
- [x] 3.4 Mutation checks on the new rules
