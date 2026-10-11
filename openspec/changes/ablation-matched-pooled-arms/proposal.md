## Why

The planned test of workspace mediation (paper §6.3, Appendix A.8) compares
competitive selection with two controls, a matched arm and a pooled arm, run
on the same film program with the same seeds. Paper §5.4 lists both controls
as still to be completed in the live cycle, together with greedy decoding of
the language organ in the study configuration. The live cycle has only
competitive selection today, so neither control can be run.

## What Changes

- `[syneidesis].arm` selects the arm of the live cycle: `competitive` (the
  default, selection and access as built), `matched` or `pooled`.
- Matched arm: on each broadcast tick Syneidesis scores every candidate as
  before, then draws `min(top_k, n)` candidates uniformly without replacement,
  without regard to score, from a generator seeded from the run seed. A drawn
  member is accessed when its score reaches the access threshold, and the
  broadcast is inhibited when no drawn member is accessed. Ticks that are not
  broadcast ticks draw nothing, so the draws depend only on the sequence of
  broadcast ticks.
- Pooled arm: no candidate is scored. Every candidate of the tick is a member,
  the broadcast is never inhibited, the score table carries each candidate's
  intensity (so Volition applies its report rule to intensities), and the
  broadcast has no access threshold, so every member enters the context. An
  empty pooled broadcast replaces the context with the featurization of the
  empty set, because in this arm every broadcast replaces the context.
- Every broadcast carries its arm in its metadata, and the research log's
  workspace record copies it, so each run's records say which arm produced
  them.
- The matched and pooled arms require the coherence layer to be off, as it is
  in the base-thesis form; Syneidesis refuses the combination at construction.
- The module-addition study's overlay pins `[lingua].temperature = 0.0` and
  `[syneidesis].arm = "competitive"`, so an operator override cannot make a
  study run sample stochastically or run a control arm.

## Capabilities

### Modified Capabilities

- `syneidesis`: arm selection, the matched draw, the pooled broadcast, and the
  pooled context rule.
- `research-event-log`: the workspace record carries the arm.
- `module-ignition-study`: the study configuration sets greedy decoding and the
  competitive arm.

## Impact

- `kaine/workspace/syneidesis.py`, `kaine/modules/context.py`,
  `kaine/evaluation/observers/research_event_observer.py`,
  `kaine/cycle/__main__.py`, `kaine/research/ignition_study/overlay.py`,
  `config/kaine.toml`, tests.
- With the default arm, selection, access, inhibition and the context are
  unchanged; each broadcast's metadata gains the `arm` key.
- Not covered: the null-context evaluation and the positive control (a
  separate change), and a runner for the ablation itself.
