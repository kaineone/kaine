## 1. Self-rhythm (option R)
- [ ] 1.1 `SelfRhythmOscillator`: recurrent excitation, fast depression, own drive as excitability bias, `afferent_gain`, spike/step counters; cited at the code site.
- [ ] 1.2 Slow period plasticity (Righetti phase-projected rule on τ_rec, mean-centred input, clamped band); no beat frequency in code (test).
- [ ] 1.3 Band-limited phase for Soma; serialized state v2 (v1 states start fresh); Soma slot 6 rescaled.

## 2. Measurement
- [ ] 2.1 `gestation.py`: rate sampling, band filter, 300 s window, edge trim, 19 foreign-mother surrogates, frequency pull; readout publishes the four numbers.
- [ ] 2.2 Marker = beats every surrogate AND self-sustain AND pull ≥ floor; `entrainment_plv_floor` removed; config keys added.
- [ ] 2.3 `cycle/__main__.py`: surrogate beat phases injected.

## 3. Validation (before any study)
- [ ] 3.1 Offline runs V1-V8 (`design.md` section 4) with the real classes; report stored in this change.
- [ ] 3.2 If V4 (specificity) fails, switch to option B and repeat.
- [ ] 3.3 Calibrate η so V2's median first pass is 12-72 h; record the compression for the paper.

## 4. Tests
- [ ] 4.1 Oscillator: band, no target frequency, bounded afferent, v1 → v2, disabled is bit-identical.
- [ ] 4.2 Markers: band phase, edge trim, surrogates, pull; evoked-only and foreign-mother cases fail.
- [ ] 4.3 A short slow-marked validation run in the suite.

## 5. Docs
- [ ] 5.1 Gestation and Soma chapters; configuration appendix; the paper's methods notes (compression and episodic-breathing disclosures).
