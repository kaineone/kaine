## 1. Backend

- [x] 1.1 `WetwareOscillator` in `kaine_cl1/backends/oscillator.py`: `step`, `phase` (NumPy FFT Hilbert), `set_frequency`, `serialize`, `deserialize`.

## 2. Plugin wiring

- [x] 2.1 `config.py`: `[oscillators]` table (`modules`, `channels_per_module`, default 4).
- [x] 2.2 `plugin.py`: declare `oscillator.<module>` seams; `make_oscillator(module, config, defaults)` using `defaults["plv_window"]` (default 10); territory reuse on repeated calls; total channel budget check in `seams`.
- [x] 2.3 Example config and `docs/cl1.md`: the `oscillators` table and that `[oscillator].enabled` must be true.

## 3. Acceptance (simulator)

- [x] 3.1 Neutral phase before `plv_window` samples; finite phase in [-pi, pi] after.
- [x] 3.2 Shared-drive pair has higher PLV than differently driven pair.
- [x] 3.3 `set_frequency(0.5)` halves the queued stimulation drive.
- [x] 3.4 Seams, `make_oscillator`, budget check; boot through KAINE's loader with `[oscillator].enabled = true` attaches the wetware oscillator to the module.
- [x] 3.5 `openspec validate oscillator-on-wetware --strict` passes (in the plugin's openspec).
