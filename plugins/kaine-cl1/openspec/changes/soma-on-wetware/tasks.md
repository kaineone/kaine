## 1. Backend

- [x] 1.1 `WetwareInteroceptiveModel` in `kaine_cl1/backends/soma.py`: substrate hidden state, NumPy readout, silicon-equivalent `step` and `prediction_error_to_salience`.
- [x] 1.2 Suspension: no readout change and no `adaptation_steps` advance while suspended.
- [x] 1.3 Shape-checked `state_dict` / `load_state_dict`.

## 2. Wiring

- [x] 2.1 `WETWARE_BACKENDS["soma"]` injecting through `forward_model`; remove Soma from `PENDING_CONVERSIONS`.
- [x] 2.2 Update tests that used Soma as the example of an unimplemented backend.

## 3. Acceptance (simulator)

- [x] 3.1 `soma.out` schema equality with silicon (torch-gated, booted through kaine's loader).
- [x] 3.2 Suspension verified.
- [x] 3.3 Predictive-work check: a load excursion raises the error above the steady-state level.
- [x] 3.4 Snapshot shape check.
- [x] 3.5 Chronos and Soma converted together boot through kaine and both publish.
- [x] 3.6 `openspec validate soma-on-wetware --strict` passes.
