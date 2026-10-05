## The test

- **Task.** A peak-interval procedure on Chronos's own input path. Feed snapshot sequences in which a marker event recurs at a fixed interval T, for several T spanning about 1–60 s of entity time. Then omit the marker and read Chronos's predicted timing: the forward head's prediction error over time, or a readout trained offline on the hidden state.
- **Measure.** For each T, the mean and standard deviation of the response peak time.
- **Pass.** The coefficient of variation (sd/mean) is approximately constant across T: no significant slope against T, at a pre-registered tolerance, following the arXiv 2608.16666 protocol.
- **Fail.** The CV falls or rises with T.
- **Conditions.** Offline and seeded, with no entity, on Chronos as shipped (NumPy CfC, the thesis-profile forward head).

## If Chronos fails

Two mechanisms from the cited lineage:
1. **The striatal beat-frequency model** (Matell and Meck 2004, Cogn Brain Res 21:139–170): a cortical oscillator bank read out by coincidence detection. It is small enough to write directly.
2. **Laplace-transform time cells** (Shankar and Howard 2012, Neural Comput 24:134–193), which are scale-invariant by construction and reimplemented.

Either replaces or augments the reservoir only through its own change, with a paper note.

## Gate

The test can run any time, because it is offline and needs no entity. Acting on its result waits for the ablation.
