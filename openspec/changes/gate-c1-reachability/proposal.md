## Why

Two maturation-gate C1 criteria never passed in the ninth test boot.

**The period-variability floor is at odds with its cited science and cannot be reached.**
- `V_per` is the coefficient of variation of the self-rhythm's wrap intervals over 5 min. The ninth boot ran 0.089 to 0.160 against a floor of 0.2.
- Simulating the shipped oscillator under the shipped maternal drive for 24 h per arm gives a median of 0.06 to 0.09 and a maximum of 0.15. Entrainment pulls it toward the beat's own CV of 0.02 to 0.06, so the floor works against the marker the phase exists to earn.
- The floor was set before the measure existed and never calibrated.
- Fetal heart-rate variability over 5 min (Moraes et al. 2012, Table 2) has an SDNN of 17.6 ms at 143 cpm, a CV of about 0.042. Quiet sleep is about 0.027 (25th percentile about 0.023) and active wake about 0.083.
- A floor of 0.2 is 2.5 to 7 times fetal values. What the science supports is a non-rigidity floor below every fetal five-minute value.

**Entrain-then-autonomy is reachable in a full phase, but a restart can erase a pass run.** The first withdrawal of a boot is scheduled 60 to 510 s after boot (the settling period plus a jittered fraction of the period). The phase-locking value needs 80% of a 300 s idle window, so whenever the withdrawal comes within about 240 s of boot, the pass is undefined and the persisted consecutive-pass count resets to 0. Two things make this worse:
- The jitter counters are not persisted, so every boot of the same seed draws the same offset. The ninth boot's entity got 84 s at both boots.
- The latest markers are not persisted either, so the readout carries no entrainment or self-sustain marker after a restart until the next withdrawal.

Paper A.7 says a restart neither resets nor repeats the pass run.

## What Changes

- The period-variability floor `V^min_per` (`hrv_variability_floor`) becomes 0.02, just below every fetal five-minute value (Moraes et al. 2012). The shipped config and the gate's default both change, and the status is no longer provisional.
- A withdrawal waits, in addition to the existing bounds, until the entrainment window `Delta_E` (`entrainment_window_seconds`) has passed since boot or the last thaw (the end of a pause), so it is never spent on a window that cannot be scored. A perturbation keeps its existing bounds.
- `development_progress.json` also records the two jitter counters, the latest entrain-then-autonomy marker and the latest self-sustain marker, and the owner restores them before it schedules the first probes. Probe draws therefore continue across boots instead of repeating, and the readout carries the latest markers after a restart.
- Migration: a progress file without the new fields loads as before. The counters start at 0 and the self-sustain marker is unknown. The entrainment marker is true when the restored consecutive-pass count already reaches the replication count, and unknown otherwise. The next save writes the new fields.

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: the withdrawal wait after boot or thaw, persistence of the probe draws and latest markers, and the period-variability floor.

## Impact

- Code: `kaine/cycle/development.py`, `kaine/lifecycle/maturation_gate.py`.
- Config: `config/kaine.toml`.
- Tests and docs (`docs/06-operation/development.md`, `docs/appendix-a-configuration/perception-and-sleep.md`, `docs/appendix-a-configuration/lifecycle-and-research.md`, `docs/appendix-b-glossary.md`, and others that quote the floor).
- Paper: A.7 and Table A1, on a separate paper branch.
