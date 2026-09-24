## 1. Backend

- [ ] 1.1 Implement `WetwareOscillator` implementing `OscillatorProtocol`
      (`phase()`, `step(activity)`, `set_frequency(scale)`), in
      `kaine_cl1/backends/oscillator.py`.
- [ ] 1.2 Drive: `step(activity)` sets periodic entraining stim on the oscillator
      territory scaled by activity.
- [ ] 1.3 Read: extract phase from burst timing / DCT spectral peak over the
      territory; return via `phase()`.
- [ ] 1.4 `set_frequency(scale)` scales the entrainment frequency (supports
      Hypnos deep-sleep slowdown).

## 2. Wiring

- [ ] 2.1 In `kaine_cl1/boot.py`, attach a `WetwareOscillator` to each selected
      module via `BaseModule.attach_oscillator(...)`; unselected modules keep the
      neutral phase (no change).
- [ ] 2.2 Allocate `[substrate.territories].oscillator` (default 8).

## 3. Acceptance (simulator)

- [ ] 3.1 Two modules driven at the same frequency show high PLV coherence; at
      detuned frequencies, low coherence: the tissue-sourced phase carries the
      binding signal.
- [ ] 3.2 `set_frequency(0.5)` measurably halves the effective phase advance rate.
- [ ] 3.3 A module with no substrate oscillator reports the neutral phase and does
      not perturb selection (upstream-parity test).
- [ ] 3.4 `openspec validate oscillator-on-wetware --strict` passes.
