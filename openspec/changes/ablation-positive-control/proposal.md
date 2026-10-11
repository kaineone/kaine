## Why

Paper §6.3 and Appendix A.8 require a positive control before the live runs: for each of Topos, Audition and Soma, a synthetic component that carries known information about the processor's next input is appended to its context and treated as another source's contribution, so the null context replaces it by its mean. The measure passes for a processor when its information gain with the component exceeds its gain without it by at least the control's minimum effect, and the live test runs only after it passes for every processor. Paper §5.4 lists the control as unfinished, and change `ablation-null-context-positive-control` left its tasks open pending design decisions. The project manager settled them on 2026-10-10:

- The component reaches the context in hindsight, through a shadow forward model. The live model forms its prediction before the next input exists, so a shadow (same architecture and weights, context one component wider, trained on the same inputs) forms at each report the prediction the previous report's state would have formed. That is exact, because no weight changes between forming and scoring. The informative component is a seeded projection of the processor's actual input plus seeded noise at a fixed signal-to-noise ratio. A seeded series with the same running mean and variance, built only from earlier inputs' statistics so it is independent of the current input, is the non-informative check.
- The comparison is within one run. "With" is the informative shadow's gain with the component nulled to its running mean; "without" is the live model's own gain on the same reports.
- The minimum effect and the signal-to-noise ratio are configuration keys with no defaults. Without the ratio the control refuses to start; without the minimum effect it records results but refuses a verdict.
- A second lead review (2026-10-10) required: the terminal records published in the cycle's shutdown before the research log stops, with the stream observers draining on stop; the checker failing on any failed record, more than one terminal record, or a record after the terminal one; `min_effect` and `min_reports` required at boot when enabled; the checker recomputing the effects from the IG means; the null component mean taken from earlier components only; and shadow copies that draw no random numbers, built on the event-loop thread.
- Lead review (2026-10-10) made the verdict fail-closed: a required `min_reports` with no default, `min_effect` above 0, the "with" and "without" gains over the live model's mean error as one denominator, a terminal record at clean shutdown that the checker requires, and a checker that re-derives the verdict from the numbers and fails on parse errors.

## What Changes

- `LatentForwardModel`, `AuditoryForwardModel` and `SubstrateForwardModel` gain `widened_copy(extra)`, a copy whose context input is wider with zero weights on the new inputs, and `hindsight_step(...)`, which scores and learns in hindsight as above.
- The Topos and Audition shadows skip a non-finite input without touching their state, as Soma's already does.
- New `kaine/modules/positive_control.py`: settings parsed from `[positive_control]` (`enabled`, `min_effect`, `min_reports`, `snr`, `seed`), the component sources, a shadow probe per component, and a per-processor controller that pairs the shadows' gains with the live gain on awake reports where all three are defined and reports cumulative means, effects and the verdict. A processor passes when the informative effect reaches the minimum effect and the non-informative one does not.
- Topos, Audition and Soma build the controller only when the section enables it, step it after each live report, and publish its running result as `positive_control.result` on `positive_control.out`, a stream the cycle never reads as candidates. Each counts a report only when every gain is finite, and runs the shadows off the event loop. A clean shutdown publishes a terminal record (`final`). A control that raises is logged, publishes a last result marked `failed` and `final` with `passed` false, and is switched off for the run; if that publish fails it is logged at ERROR level and the missing terminal record fails the run.
- The research log records the result fields; the range sweep bounds `n_reports`, `min_reports`, `min_effect` and `snr`.
- `python -m kaine.experiment.positive_control <run_id>` reads a finished run, re-derives each processor's verdict from its last record's numbers (terminal, not failed, finite, `n_reports` at least `min_reports`, `effect` at least `min_effect` above 0, `noise_effect` below it), and exits 0 only when all three pass and no record line failed to parse. No study gate for the planned test's live runs exists in the code, so the verdict is recorded and checked offline, not enforced at boot.
- `config/kaine.toml` ships `[positive_control]` disabled, with `min_effect`, `min_reports` and `snr` unset.

## Capabilities

### New Capabilities

- `information-gain-positive-control`: the positive control of the broadcast information-gain measure.

### Modified Capabilities

- `research-event-log`: the log records the control's results.

## Impact

- `kaine/modules/{topos,audition,soma}/forward.py` and `module.py`, new `kaine/modules/positive_control.py`, `kaine/boot/factories/{topos,audition,soma}.py`, `kaine/boot/registry.py`, `kaine/evaluation/stream_registry.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/log_schema.py`, new `kaine/experiment/positive_control.py`, `config/kaine.toml`, docs, tests.
- With the section disabled (the default) no shadow is built and no code path changes.
- Open: the paper excludes an initial learning period from IG_j. The control counts every awake report from the start, which includes the shadow's own learning of the component and so makes the control conservative. A learning-period setting can be added when that period is fixed with the other settings.
