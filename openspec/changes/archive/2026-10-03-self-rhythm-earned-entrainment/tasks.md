## 1. Self-rhythm (option R)
- [x] 1.1 `SelfRhythmOscillator`: mean-field generator (Tabak 2000) with recurrent excitation and fast depression, own drive as excitability bias, weak `afferent_gain`, LIF readout and counters; cited at the code site (calibration showed recurrence on the 16 spiking units cannot produce the rhythm).
- [x] 1.2 Slow period plasticity (Righetti phase-projected rule on τ_rec, mean-centred input, clamped band); no beat frequency in code (test).
- [x] 1.3 Band-limited phase for Soma from the generator activity; serialized state v2 (v1 states start fresh). Slot 6 (2·amplitude) needed no rescale: the band-passed amplitude is 0.17-0.29.

## 2. Measurement
- [x] 2.1 `gestation.py`: rate sampling, band filter, 300 s window, edge trim, 19 foreign-mother surrogates, frequency pull; readout publishes the four numbers.
- [x] 2.2 Marker = beats every surrogate AND self-sustain AND pull ≥ floor, replicated over `entrainment_replications` (3) consecutive withdrawals; `entrainment_plv_floor` removed; config keys added.
- [x] 2.3 `cycle/__main__.py`: surrogate beat phases injected.

## 3. Validation (before any study)
- [x] 3.1 Offline runs V1-V8 (`design.md` section 4) with the real classes; report stored in this change.
- [x] 3.2 V4 (specificity) passed with option R; option B was not needed.
- [x] 3.3 Calibrate η so V2's median first pass is 12-72 h; record the compression for the paper.

## 4. Tests
- [x] 4.1 Oscillator: band, no target frequency, bounded afferent, v1 → v2, disabled is bit-identical.
- [x] 4.2 Markers: band phase, edge trim, surrogates, pull; evoked-only and foreign-mother cases fail.
- [x] 4.3 The validation runs are reproducible from `validation/` (96 h runs take about 40 min, too long for the suite); the suite covers the mechanics, and `validation/fidelity.py` ties the class to the prototype.

## 5. Docs
- [x] 5.1 Gestation and Soma chapters; configuration appendix; the paper's methods notes (compression and episodic-breathing disclosures).
