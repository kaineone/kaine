## Why

The eighth test boot (2026-10-18b) gave 0 own curiosity reliefs per awake hour and all three curiosity goals stalled, although the audition forward model really learned: its raw error halved, 1.05 to 0.56, over the first hour. A replay with the live classes traced it to the learning-progress horizons. Learning progress was the relative fall of a 10 s mean of each perceptual source's raw error against a 100 s mean. Development at about 1 percent per 100 s sits under the 0.05 floor, so these horizons see only transients such as the re-adaptation after a speech episode. The paper's A.7 calibration of 7.5 reliefs an hour held only for a forward model pretrained 12 h on the voice-free feed with zero context; a fresh model with the voice from the first boot gives none.

In the intrinsic-motivation literature learning progress is the decrease of the mean prediction error between two windows of the learner's recent history (Oudeyer, Kaplan and Hafner 2007, Eqs. 1-2, the mean over the last theta errors against the same mean delayed by tau), or between the two halves of a sliding window (Baranes and Oudeyer 2013). The windows have to span the learner's learning curve. Here the forward models learn over minutes (vision) to hours (audition), so the horizons must be of that order. A frozen or converged model has a flat error, so it gives no sustained progress (Gottlieb et al. 2013; Schmidhuber 2010), and the floor keeps its job.

## What Changes

- Learning progress, the curiosity relief `lp+`, becomes windowed (paper A.4, Table A1). Each perceptual source's raw errors, counted from its first positive error, are summed into consecutive bins of `learning_progress_bin_s` (60 s). With `k` the number of the latest completed bins, at most `learning_progress_span_s / learning_progress_bin_s` (90) and rounded down to an even number, the source's progress is `clip(1 - mean_new / mean_old, -1, 1)`, where `mean_old` and `mean_new` are the report-weighted mean errors of the older and newer halves of those `k` bins. The source is undefined while `k < 2`, while either half holds no report, or while `mean_old <= 1e-9`. The pooled `lp` is the mean over defined sources, 0 if none, and `lp+ = max(0, lp - learning_progress_floor) / (1 - learning_progress_floor)` relieves curiosity and sets its build input as before. The span grows with the history until it reaches 90 min, so progress is defined two minutes after the first report.
- The fast and slow time-decayed means are unchanged and keep their other roles. Their pooled relative fall (now called the error dynamics `ed`, published as `signed_progress`) still sets the pleasantness check and so valence; the alert rates and the wellness means keep `fast_time_constant_s` and `slow_time_constant_s`. Valence dynamics are unchanged.
- New `[affect]` keys `learning_progress_span_s = 5400.0` and `learning_progress_bin_s = 60.0` (Table A1 `T_lp`, `Delta_lp`), validated: both finite and positive, and the span an even whole number of bins (at least 2).
- The bins, the current partial bin and the time elapsed in it persist in the affect snapshot under `learning_progress_bins` and carry through sleep like the error means. An old snapshot without the key, or one saved with a different bin width, starts the bins fresh; a snapshot with more bins than the span keeps the newest.
- `affect.state` and its research record add `vision_learning_progress`, `audition_learning_progress` (each source's windowed progress, null while undefined) and `signed_learning_progress` (the pooled `lp`). `learning_progress` keeps its meaning, `lp+`, now from the windows.

- The run manifest gains `learning_progress_scheme = 2` (`LEARNING_PROGRESS_SCHEME`, the `config_key_scheme` convention): the research-log field `learning_progress` keeps its name, and a manifest without the field marks a run whose `learning_progress` came from the fast and slow means (scheme 1), so analyses can tell the estimators apart.
- A restored bin whose count is 0 must have an error sum of 0; otherwise the source's bins start empty.

Calibration (offline, 16 awake hours, 3 seeds, the live audition path with a fresh forward model, the voice from the first boot, the real broadcast-context featurizer fed with accessed broadcasts matched to the eighth boot, and a vision proxy fitted to its live error course): with these defaults curiosity's median is 0.1 to 0.75 over the first six hours while the forward models learn, held below threshold so it rarely crosses, then near 0.9; a phase-randomized voice and the voice-free feed match the voice, and a frozen forward model gives 0.04 own reliefs an hour. With the old horizons curiosity's median stays near 0.9 throughout and the voice feed gives 7.7 own reliefs an hour from hour 6 on (phase-randomized 8.5, voice-free 2.0, frozen 0.36): those reliefs are the re-adaptation transients after each speech episode, and the first hours, when the models learn most, give 0.3 to 2.7.

## Capabilities

### New Capabilities

### Modified Capabilities

- `affect`: learning progress is computed from windowed error means over the forward models' learning curves; the new estimator state persists; the state event carries the windowed progress terms.
- `research-event-log`: the curated `affect.state` record keeps the windowed progress terms.

## Impact

- `kaine/modules/affect/learning_progress.py` (new), `kaine/modules/affect/module.py`, `kaine/boot/factories/affect.py`, `config/kaine.toml`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/log_schema.py`, `kaine/experiment/run_context.py`, `docs/09-modules/affect.md`, `docs/16-run-identity.md`, `docs/appendix-a-configuration/modules.md`, `docs/17-research-data/event-streams.md`, tests.
- Behaviour: curiosity's relief and build input change for every entity, the kept seed included (high risk, second review). A converged entity sees little progress, as before; a learning one sees it for hours. Valence, boredom, arousal and the alert rates are unchanged. The persisted state adds at most 91 pairs of scalars per perceptual source, no sense data.
- Paper: A.4 learning progress, Table A1 (`T_lp`, `Delta_lp`), A.7 calibration sentence, on branch `paper-lp-horizons`.
