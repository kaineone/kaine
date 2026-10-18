## 1. Implementation

- [ ] 1.1 Hearing band module: parameters from `[perception_feed.stimulus_source.hearing]`, the stepwise edge schedule on Hepper and Shahidullah's tone grid, and the band-pass design
- [ ] 1.2 The stimulus-source audio stream filters the bed and voice through the band over a recomputed history; boot reads the table, loads the voice with the 3,000 Hz low-pass when the band is on and passes the awake-time provider
- [ ] 1.3 Config keys and the colour ramp with Table A1 values, and docs
- [ ] 1.4 Tests: schedule shape, determinism, byte-identical audio with the band disabled, independence from earlier blocks and restart continuity, spectrum under the moving edges
- [ ] 1.5 Offline calibration recorded in the PR (learning progress, curiosity, goal stalls and the vision gate over 30 awake hours, 3 seeds, frozen control)
