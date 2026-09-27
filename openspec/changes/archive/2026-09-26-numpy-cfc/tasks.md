## 1. Implementation

- [x] 1.1 `kaine/cfc_numpy.py`: reservoir generation, the NumPy CfC step, the NumPy readout with SGD.
- [x] 1.2 Soma and Chronos take `cfc_backend` and `reservoir_seed`; both backends use the generated reservoir; Chronos's head gets the NumPy path.
- [x] 1.3 Serialise and restore the reservoir seed; older snapshots start a new reservoir and log it.
- [x] 1.4 `config/kaine.toml` (`cfc_backend = "numpy"`), the `kaine/extras.py` rows (`core` needed only for the torch backend), docs.
- [x] 1.5 An unseeded reservoir draws its seed from the ambient NumPy state, so experiment seeding reproduces it; a plugin-injected Chronos network needs no seed.

## 2. Verification

- [x] 2.1 Tests:
  - torch/NumPy parity to 1e-5 over 500 steps with training;
  - the same seed gives the same reservoir, and a different seed a different one;
  - a revive with the seed reproduces the pre-preservation hidden trajectory and predictions from the same inputs;
  - an older snapshot starts a new reservoir and logs it;
  - the numpy backend runs with torch blocked from import;
  - the extras check no longer requires `core` for Soma or Chronos on the numpy backend;
  - the existing Soma and Chronos tests updated where they assert `ncps` types.
- [x] 2.2 Offline suite green; `openspec validate numpy-cfc --strict`.
