## Why

KAINE's oscillatory-binding layer attaches a small oscillator to each module and uses phase coherence (the phase-locking value, PLV) among modules to bind co-active coalitions in the workspace. The silicon oscillator is a population of leaky integrate-and-fire units: each time its module publishes, it is driven by that event's salience, records the fraction of units that fired, and reports the instantaneous phase of that spike-rate series through a Hilbert transform. Cortical cultures produce rhythmic activity of their own, so realising this population on a substrate territory reads the rhythm from tissue dynamics rather than from a simulated population.

KAINE accepts a plugin oscillator through the `oscillator.<module>` seam and calls the plugin's `make_oscillator` once per declared seam at boot; restarts re-attach the same object.

## What Changes

- **`WetwareOscillator`** (`kaine_cl1/backends/oscillator.py`) implements KAINE's `OscillatorProtocol` (`step`, `phase`, `set_frequency`, `serialize`, `deserialize`) with the silicon oscillator's semantics:
  - `step(drive)` clamps the drive to [0, 1], stimulates the oscillator's own territory with amplitude proportional to `drive * drive_scale`, runs one substrate tick, and appends the territory's firing fraction (the share of its channels that spiked) to a history of `2 * plv_window` samples;
  - `phase()` returns the instantaneous phase of the de-meaned history through an FFT-based Hilbert transform (NumPy only), and the neutral phase (0.0) until `plv_window` samples exist or when the series is flat;
  - `set_frequency(scale)` sets `drive_scale`, as the silicon oscillator does (Hypnos lowers it during maintenance);
  - `serialize`/`deserialize` carry `drive_scale` only; the phase history is runtime context, as in silicon.
- **One territory per oscillated module.** `[plugins.cl1.oscillators]` lists the modules (`modules = [...]`) and the channels each gets (`channels_per_module`, default 4); each oscillator leases territory `oscillator.<module>`. The plugin declares one `oscillator.<module>` seam per listed module and builds the oscillator in `make_oscillator`. The channel budget across all territories is checked at load time.
- KAINE only attaches oscillators when `[oscillator].enabled` is true and rejects oscillator seams otherwise; the plugin's docs and errors say so.

Earlier drafts described entraining a frequency with periodic stimulation and claimed `set_frequency(0.5)` halves the phase-advance rate. The silicon oscillator does neither: it samples once per publish and `set_frequency` scales the drive. This revision matches the silicon semantics so PLV coherence means the same thing on both substrates.

## Non-goals

- Changing the PLV coherence math or how the workspace uses phase.
- Converting the modules themselves (this is the oscillator seam only).
- A shared cognitive tick: each `step` advances the substrate by one tick window and reads only this oscillator's territory, like the Chronos and Soma backends.
- Real hardware (the plugin is simulator-only).

## Impact

- New code: `kaine_cl1/backends/oscillator.py`; `kaine_cl1/plugin.py` (oscillator seams, `make_oscillator`, budget check); `kaine_cl1/config.py` (the `oscillators` table); example config and `docs/cl1.md`.
- Performance: a step runs on every publish of an oscillated module, so each publish costs one substrate tick; the simulator must stay in accelerated time (already required).
