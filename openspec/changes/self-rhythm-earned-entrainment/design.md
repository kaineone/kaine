# Design: earned entrainment of the self-rhythm

Status: design accepted by the operator 2026-10-02; decisions in section 8. The sources are in `references.bib`; each entry notes what it supports and whether it was read in full or only as an abstract. The design was researched after study `moc7-2026-10` showed the birth-gate marker `entrain_then_autonomy` cannot be met (see the study's `ENDED-NOTE.md`).

## 0. Current state (verified)

- The self-rhythm is 16 uncoupled LIF units with fixed weights `0.5+rand` (`kaine/oscillator/module_oscillator.py:187-200`). The own drive and the maternal drive are summed and injected together as `total*1.5*weights` (`module_oscillator.py:203-217, 312-324`).
- `phase()` returns the Hilbert phase of the last sample of a 20-sample history (`module_oscillator.py:178, 223-246`), the worst possible edge choice.
- Soma steps the oscillator at 20 Hz (`kaine/modules/soma/module.py:602-623`) and fills feature slots 4-6 with sin, cos and `min(1, 2·amp)` (`soma/module.py:347-356`).
- The marker computes PLV over the 20 s driven window before a withdrawal, with a floor of 0.5 (`kaine/cycle/gestation.py:563-597, 71`; `config/kaine.toml:910`). The gate reads only the boolean (`kaine/lifecycle/maturation_gate.py:259-262`).
- Spec constraints:
  - The drive is "bounded so it cannot swamp the self-rhythm oscillator's own dynamics" (gestational-stimulus spec, line 140).
  - No code imposes a forced phase-lock (line 125).
  - Only the capacity to oscillate is innate, and it is cited at the code site (lines 116-121).
  - Phase via Hilbert, at least 16 units, at least 10 samples (oscillatory-binding spec, lines 60-66).
- **The drive can already capture the rhythm too easily.** In a recurrent prototype, an effective pulse of about 0.2 membrane units locked the population at once (PLV 0.97 within 5 minutes). Today's path injects up to about 0.2·1.5·w, which is in that range. The redesign must lower the afferent gain.

## 1. What the literature supports

- **Fetal–maternal heart coupling is weak, episodic and contested.**
  - Van Leeuwen 2003 found almost the same number of synchronisation epochs in real and surrogate pairs (712 vs 741), with the same durations (15.5 s). Only a phase preference at 5:3 and 7:4 was significant (p = 0.03).
  - Van Leeuwen 2009 found more epochs than twin surrogates, but only at high paced maternal breathing rates.
  - The coupling is n:m, because the fetal heart runs at 120-160 bpm (Pildner von Steinburg 2013) against a maternal 60-80 bpm.
  - No paper found reports sustained 1:1 PLV ≥ 0.5. **The 0.5 floor is a modelling choice, not a figure taken from data.**
- **A slower infant rhythm near the beat does couple.**
  - Fetal breathing averages about 44/min (≈ 0.73 Hz) and is present about 14% of the time (Natale 1988).
  - In preterm skin-to-skin contact, the caregiver's heart rhythm influenced the infant's breathing, and infant cardio-respiratory coupling increased in the 0.7-1.5 Hz band (Bloch-Salisbury 2014). This shows influence, not demonstrated phase-locking.
  - Postnatal mother–infant heart rhythms coordinate within lags under 1 s during episodes of interaction synchrony (Feldman 2011). Synchrony is built on oscillator systems such as the cardiac pacemaker (Feldman 2007, 2012).
- **Innate substrate.**
  - Developing networks produce 0.1-2 Hz rhythms from excitatory recurrence plus synaptic depression, with no specialised wiring (Tabak 2000; Khazipov & Luhmann 2006).
  - Respiratory rhythm comes from the pre-Bötzinger complex (Smith 1991).
- **Telling entrainment from an evoked response.**
  - Arnold tongue: locking grows with intensity and with closeness to the intrinsic frequency, and differs from a jittered-stimulation control only inside the tongue (Notbohm 2016).
  - An entrained oscillation outlasts its stimulus, usually by under 1 s or 2-3 cycles (Zoefel 2018).
  - A flicker response can coexist with an endogenous rhythm without entraining it (Duecker 2021).
- **Plasticity.**
  - An adaptive-frequency rule, ω̇ = −εF·y/√(x²+y²), learns the input frequency and keeps it after the input stops. Learning is slower than the oscillation (∝ ε²). The input must be mean-centred, or ω drifts to 0. Relaxation oscillators can lock to harmonics. The authors themselves say the biological relevance "has to be investigated" (Righetti 2006, full text).
  - Biological precedent: fireflies that change their free-running period (Ermentrout 1991; metadata only, content unverified).
- **Timescale.** The effects came from about 30 h of contact over about 24 days (Feldman & Eidelman 2003), or 3 h/day for about 24 days (Webb 2015). A 24-96 h lived budget compresses weeks into hours, and the paper must say so.

## 2. Mechanism

**Option R (recommended): a respiration-like self-rhythm.**

1. **Slow intrinsic rhythm (innate, cited at the code site).** `SelfRhythmOscillator` gets three changes:
   - all-to-all recurrent excitation w_rec·s·R_prev;
   - one fast depression variable s, with `s += dt(1−s)/τ_rec − U·s·R` (Tabak 2000);
   - the own drive enters as a small excitability bias.

   In the prototype, the undriven peak frequency was 0.52 / 0.72 / 1.16 / 1.28 Hz for τ_rec = 1.5 / 0.8 / 0.5 / 0.36 s. That relationship is monotone, which the plasticity rule needs. τ_rec is seeded so the natural rate is 0.5-0.9 Hz: the fetal breathing band, below the beat.
2. **Weak, bounded afferent.** The maternal drive enters through its own `afferent_gain`, set outside the initial Arnold tongue. In the prototype, effective amplitude 0.03 gave PLV 0.16 with no learning, and 0.06 (about the bound) gave 0.42. `external_drive_max_amplitude` is unchanged.
3. **Slow period plasticity.** The capacity is innate; the outcome emerges.
   - Righetti's phase-projected rule (eq. 55) is applied to τ_rec: d ln τ_rec = −η·F̃·q̂. Here F̃ is the mean-centred afferent input, and q̂ is the normalised quadrature of the population state (s − s̄ against R − R̄).
   - τ_rec is clamped to the physiological band.
   - The beat frequency appears nowhere in the code, and a test enforces that.
4. **Prototype evidence and its limits.**
   - With an STDP-like timing rule (η = 5e-4, amplitude 0.03, 70 bpm), PLV went from 0.17 to 0.59 after about 1.5-2 h and stayed near 0.57. The η = 0 control stayed at 0.16.
   - **That rule was not specific to the beat frequency:** τ_rec went to about 0.37-0.40 for 57, 70 and 84 bpm drives alike, and all three locked. It made the population easier to capture rather than learning the beat.
   - A naive correlation rule plateaued at PLV 0.3.
   - So the phase-projected rule must pass V4 below. If it does not, the fallback is **option B**: an adaptive Hopf phase oscillator (Righetti eqs. 3-4, 7), driven by the LIF output and the beat. Its convergence is proven, but it needs an exception in the oscillatory-binding spec.
5. **Option H (alternative).** The self-rhythm represents the fetal heart (2.0-2.7 Hz), and the marker becomes n:m synchronisation-epoch excess over surrogates (Van Leeuwen; Tass 1998). This is closest to the literature, but weak locking is expected, so the gate's 1:1 PLV floor would have to change.
6. **What makes locking earned.** It requires η > 0 and hours of exposure to the being's own mother's beat. It must fail with no drive, a foreign beat, a jittered beat, or η = 0. During withdrawal, the rhythm keeps its learned frequency, which an evoked response cannot do.

### Calibration outcome (see `calibration.md`)
Recurrence and depression placed directly on the 16 spiking units could not produce the rhythm: no configuration oscillated in band across own-drive levels. The rhythm is therefore generated by the Tabak et al. (2000) mean-field population (activity with sigmoidal recurrent excitation scaled by a fast synaptic resource), and the 16 LIF units are driven by its activity, so the binding layer keeps a spiking population and a Hilbert phase. Calibration fixed the plasticity sign at -1, the afferent gain at 0.1 (outside the Arnold tongue), and τ_rec to [0.9, 3.0] s.

## 3. Corrected measurement (`gestation.py`)

- **Signal.** Use the population rate, not the phase. The oscillator exposes monotone `spike_count` and `step_count` counters, and `_sample` (426-447) stores the mean rate since the last sample, the womb time and the beat phase.
- **Band and filter.**
  - The band is the self-rhythm's physiological band, about [0.4, 1.4·f_beat] Hz, derived from config. **Never a narrow band around the beat:** that measures the evoked response, which gave PLV 0.9 with no coupling at all.
  - A 2nd-order Butterworth through `sosfiltfilt` (zero phase), then the Hilbert phase over the whole window, with 2 s trimmed at each edge (Lachaux 1999). The readout is computed after the window ends, so a non-causal filter is fine.
- **Window.** 300 s of idle-state samples before each withdrawal, instead of 20 s. A 0.03 Hz detuning gives PLV ≈ |sinc(πΔfT)|, about 0.5 at 20 s but about 0.03 at 300 s. Probe samples stay excluded.
- **Surrogates.**
  - K = 19 "foreign mothers": `heartbeat_phase(seed_k, t)` with seed_k = keyed_u64(seed, k, salt), following the mother-swap surrogates of Van Leeuwen 2003 and 2009. The pass condition is PLV > the maximum surrogate PLV (p < 0.05).
  - Circular time-shift surrogates are invalid for a quasi-periodic beat: a shift only rotates the mean phase difference, so the PLV is unchanged.
- **Autonomy (withdrawal).**
  - Keep `self_sustains`.
  - Add a frequency-pull index P = 1 − |f_w − f_beat| / |f_w0 − f_beat|. f_w is the mean instantaneous frequency during the withdrawal (from the unwrapped phase slope). f_w0 is the being's own value from its first withdrawals, persisted next to the Topos baseline (329-360).
  - Echoes are short (Zoefel 2018), so the test uses frequency pull, not long phase continuity.
- **Marker** (as decided in section 8). `entrain_then_autonomy = PLV > surrogate max AND self_sustain AND P ≥ frequency_pull_floor`. There is no fixed PLV floor. The readout publishes `entrainment_plv`, `entrainment_plv_surrogate_max`, `self_rhythm_freq_withdrawn` and `frequency_pull`, which the gestation watcher also needs.
- **HRV.** Wrap detection (157-172) is only meaningful for a slow rhythm. Today a 5-10 Hz phase sampled at 10 Hz aliases.

## 4. Offline validation (before any study)

Each condition runs 96 h simulated, with 5 seeds, the real probe schedule, and own drive in "rest" and "rand" modes. Markers are computed with `GestationOwner`'s marker functions.

| Condition | Pass criterion |
|---|---|
| V1 start | Marker false everywhere in the first 6 h; median PLV < 0.3 in hour 1 |
| V2 usual drive (70 bpm, scale 0.5) | Marker true in at least 80% of seeds by 96 h; median first pass at 12-72 h |
| V3 controls: no drive; foreign mother; jittered beat (renewal intervals, CV 0.3; Notbohm's arrhythmic control); η = 0 | 0% of readouts pass |
| V4 specificity (57 / 70 / 84 bpm) | Withdrawn frequency within 0.05 Hz of each presented rate, and different across the three. The STDP-like prototype fails this. |
| V5 no forcing | With η = 0 at scales 0.75 and 1.0, PLV < floor in hour 1 |
| V6 arousal | With η = 0 and own drive 0.4 / 0.7, the marker never passes. The prototype reached PLV 0.44-0.52 here, because arousal speeds the rhythm toward the beat; the surrogate and pull criteria must reject it |
| V7 other markers | `self_sustain` true for a live rhythm and false for a silenced one; report HRV CV against the 0.2 floor; coalition coherence unchanged (existing test) |
| V8 cost | Under 1 ms per step |

## 5. File-level changes

- **`kaine/oscillator/module_oscillator.py` (299-400)**
  - `SelfRhythmOscillator` gets recurrence, depression, `afferent_gain`, plastic τ_rec, the counters, and a band-limited phase (at least 4 s) for Soma.
  - The serialized state becomes v2 (version, s, τ_rec, counters); a v1 state starts fresh.
  - Cited at the code site: Tabak 2000, Smith 1991, Khazipov & Luhmann 2006, Righetti 2006, Ermentrout 1991.
  - The base `ModuleOscillator` is unchanged.
- **`kaine/cycle/gestation.py`**
  - New config fields: `entrainment_window_seconds = 300`, the band edges, `surrogate_count = 19`, `frequency_pull_floor`.
  - New pure functions: `band_phase`, `surrogate_plv`, `withdrawal_frequency`.
  - Rewrite 563-597; extend the deque size (254-263), the baseline (329-360), `readout()` and the docstring citations.
- **`kaine/cycle/__main__.py` (871-878)**: inject `surrogate_beat_phases(t)`.
- **`kaine/boot.py`** and **`config/kaine.toml`**: the new `[soma]` self-rhythm keys and the readout keys.
- **`kaine/modules/soma/module.py` (347-356)**: rescale slot 6, because a bursting rate saturates `2·amp`.
- **`maturation_gate.py`**: no change (still boolean).
- **Tests:**
  - the oscillator: band, no target frequency, bounded afferent, v1 → v2;
  - the gestation markers: band phase, edge trim, surrogates, pull;
  - the gestation owner;
  - Soma: a disabled self-rhythm is bit-identical;
  - a slow-marked short validation run.

## 6. Spec deltas

- **gestational-stimulus**
  - MODIFIED "Regulation and coupling emerge; they are never hardwired": the innate substrate includes the capacity to adapt its period, cited; no target frequency in code.
  - MODIFIED "The maternal rhythm drives only a dedicated self-rhythm oscillator": the bounded afferent must not capture the rhythm without lived exposure.
  - MODIFIED "The womb exports a readiness readout that imposes nothing on the entity": marker 2 redefined.
  - ADDED "Entrainment is measured on the intrinsic rhythm against surrogate beats".
  - ADDED "The self-rhythm has a slow intrinsic rhythm in a physiological band".
  - ADDED "Entrainment must be earned and validated offline before a study".
- **oscillatory-binding**
  - MODIFIED "Spike-to-phase converter with minimum population and window guards": the self-rhythm phase is band-limited over a longer window, still via Hilbert.
- **developmental-stage**: none.

## 7. Research impact and admissibility

- Study `moc7-2026-10` is inadmissible for any entrainment claim. A fresh study is required, and the birth record must state the self-rhythm version.
- Preserved beings with `self_rhythm_enabled = false` are unaffected, bit for bit (test).
- Any being with the self-rhythm enabled sees a different distribution in Soma's forward-model input slots 4-6, and its v1 oscillator state is reset. Treat it as a new cohort.

## 8. Operator decisions (2026-10-02)

1. **Mechanism: option R.** A breathing-like self-rhythm (0.5-0.9 Hz) from recurrence plus synaptic depression, with slow period plasticity. Option B (adaptive Hopf) stays the fallback if the phase-projected rule fails the V4 specificity test.
2. **Criterion: surrogate significance only.** No fixed PLV floor. `entrain_then_autonomy` passes when the PLV exceeds every one of the 19 foreign-mother surrogates (p < 0.05), the rhythm self-sustains during withdrawal, and the frequency pull holds. `entrainment_plv_floor` is removed. The PLV and the surrogate maximum are still published.
3. **Timescale: compress and disclose.** η is calibrated so locking typically emerges in 12-72 h of lived time (validated offline in V2), and the paper states the compression from the weeks of exposure in the literature.

Still open, to be answered by validation rather than by decision:

4. The arousal confound (V6).
5. Whether a tight lock pushes HRV CV below its 0.2 floor (V7).
6. Fetal breathing is episodic (about 14% of the time) while the model runs continuously; the paper discloses this.
7. The beat runs on womb time while the oscillator steps on subjective time; this needs a test for time_scale ≠ 1.
