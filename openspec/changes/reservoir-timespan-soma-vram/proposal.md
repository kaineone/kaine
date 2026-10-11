## Why

Two findings of the mathematics review of 2026-10-08.

- **The continuous-time reservoirs never see time.** Soma and Chronos use closed-form continuous-time (CfC) cells (Hasani et al. 2022). In a CfC the gate between the cell's two candidate states is `sigmoid(t_a * ts + t_b)`, with `ts` the elapsed time since the previous observation; that is what lets the cell handle irregularly spaced input. The NumPy port and both modules run with `ts = 1` on every step (`kaine/cfc_numpy.py` "no timespans (ts = 1.0)"), so the gate is one more fixed random function and the reservoirs are discrete-time maps. Soma's reads drift with load and Chronos ticks per broadcast at an access rate that varies from 3.3 to 10 Hz, so elapsed time carries real information the cell discards.
- **Soma's eighth input is always zero.** Slot 7 of Soma's interoceptive feature vector is reserved at 0.0, and slots 4 to 6 are filled only when the self-rhythm runs, so in the base-thesis profile half of Soma's input is constant. VRAM utilisation, which Soma already reads and holds a hard threshold for (92 percent), is not predicted at all.

## What Changes

- **Real timespans, normalised to the nominal cadence.** `numpy_cfc_step(w, x, h, ts=1.0)` computes the gate as `sigmoid(t_a * ts + t_b)`, matching `ncps.torch.CfC` with timespans; the torch backends pass the same `ts`. Soma passes `ts = dt / read_interval_s` (subjective seconds since its previous read); Chronos passes `ts = dt / mean(dt)` over its last 32 broadcasts, the running-ratio convention the modules already use. Both are clipped to `[0, 10]` and are 1.0 on the first step. At the nominal cadence `ts` is about 1, so readouts trained with `ts = 1` stay calibrated; only irregular gaps change the gate.
- **Plugins are unaffected.** Built-in forward models declare `accepts_timespan = True`; the modules pass `timespan=` only to models that declare it, so plugin seams keep their signatures and their `ts = 1` behaviour.
- **VRAM in slot 7.** `metrics_to_feature_vector` fills slot 7 with the highest `gpu_<i>_vram_percent / 100`. Soma's snapshot records `feature_layout = 2`; a snapshot without it restores with layout 1 (slot 7 kept at 0.0), so a preserved being's learned readout and expected-error state stay consistent with what it was trained on.

## Capabilities

### Modified Capabilities

- `soma-predictive`: the reservoir timespan and the VRAM feature.
- `chronos-predictive`: the reservoir timespan.

## Impact

- **Code:** `kaine/cfc_numpy.py`, `kaine/modules/soma/{forward,module}.py`, `kaine/modules/chronos/{network,module}.py`.
- **Behaviour:** Soma's and Chronos's prediction errors now respond to irregular timing; at steady cadence they are close to before. On GPU hosts Soma's raw error now includes VRAM, so model loads and unloads are interoceptive events. Soma salience feeds the self-rhythm's own drive, so the live gestation markers see a slightly different signal; the archived offline gestation validation does not use these paths and is re-run in the follow-up validation step.
- **Docs:** `docs/09-modules/soma.md`, `docs/09-modules/chronos.md`.
- **Paper:** §3.5 and Appendix A.5 (the reservoir timespan) and Table A1 (`n_x` note).
