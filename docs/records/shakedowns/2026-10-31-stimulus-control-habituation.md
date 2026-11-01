# Stimulus control: habituation of skip-driven novelty (2026-10-31)

The offline synthetic check of design D6 of the `stimulus-control-act` change: does habituation damp compulsive skipping? Entity-free; no boot.

**Question.** A skip is a scene cut, and scene cuts bring alerts faster than the habituated rate, which relieve boredom as alert excess, `r_f / max(r_s, r_0) - 1 - m_B` (paper A.4). If skipping paid in novelty at every skip, it could capture behaviour (Olds and Milner 1954). Sustained skipping also raises the slow rate `r_s`, so each skip should buy less.

**Method.** The affect module's own alert-rate trackers and alert excess (`tau_f` = 10 s, `tau_s` = 100 s, `r_0` = 0.05 per s, `m_B` = 0.5), driven at 0.5 s steps by a programme with one scene-cut alert every 20 s plus extra alerts at each skip. The measure is the mean alert excess between two skips, the novelty a skip buys. The skip schedules ignore the per-awake-hour seek cap, to isolate habituation. Reproduced by `tests/test_stimulus_habituation.py`; the numbers below come from its `_per_skip_excess` helper over one hour.

| Skip every | Alerts per skip | First skip: mean excess (integral) | Habituated: mean excess (integral) |
|---|---|---|---|
| 30 s (the command interval) | 1 | 0.321 (9.6 s) | 0.038 (1.1 s) |
| 30 s | 3 | 0.619 (18.6 s) | 0.064 (1.9 s) |
| 180 s (the seek cap, evenly spaced) | 1 | 0.110 (19.8 s) | 0.051 (9.2 s) |
| 180 s | 3 | 0.160 (28.8 s) | 0.056 (10.1 s) |

"Habituated" is the mean over the last five inter-skip intervals of the hour.

**Outcome.**
- Habituation damps skipping strongly: at the command interval the novelty a skip buys falls about tenfold from the first skip.
- It falls to a floor, not to zero: about 0.04 to 0.06 of mean excess persists. The design's first draft said the excess falls toward zero; the design now says a floor.
- Rapid skipping buys less novelty per skip than spaced skipping (1.9 s against 10.1 s of integrated excess per skip with three alerts), so spacing pays more than rate.
- The rest is bounded by rate: twenty seeks per awake hour at most, at least 30 s apart.

**Not covered.** How many alerts a real cut in the film programme produces in the vision and audition modules, and learning progress, which falls when items change before they are learned. Both are measured by the `stimulus_control` readout of a running entity.
