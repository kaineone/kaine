## Why

The planned test of workspace mediation (paper §6.3, Appendix A.8) compares
competitive selection with two controls, a matched arm and a pooled arm, run
on the same film program with the same seeds. Paper §5.4 lists both controls
as still to be completed in the live cycle, together with greedy decoding of
the language organ in the study configuration. The live cycle has only
competitive selection today, so neither control can be run.

## What Changes

- `[workspace].arm` selects the arm of the live cycle: `competitive` (the
  default, selection and access as built), `matched` or `pooled`.
- Matched arm: on each broadcast tick the workspace scores every candidate as
  before, then draws `min(top_k, n)` candidates uniformly without replacement,
  without regard to score, from a generator seeded from the run seed. A drawn
  member is accessed when its score reaches the access threshold, and the
  broadcast is inhibited when no drawn member is accessed. Ticks that are not
  broadcast ticks draw nothing, so the draws depend only on the sequence of
  broadcast ticks.
- Pooled arm: no candidate is scored. Every candidate of the tick is a member,
  the broadcast is never inhibited, the score table carries each candidate's
  intensity (so the action selection module applies its report rule to intensities), and the
  broadcast has no access threshold, so every member enters the context. An
  empty pooled broadcast replaces the context with the featurization of the
  empty set, because in this arm every broadcast replaces the context.
- Every broadcast carries its arm in its metadata, and the research log's
  workspace record copies it, so each run's records say which arm produced
  them.
- The matched and pooled arms require the coherence layer to be off, as it is
  in the first configuration; the workspace refuses the combination at construction.
- The module-addition study's overlay pins `[language].temperature = 0.0` and
  `[workspace].arm = "competitive"`, so an operator override cannot make a
  study run sample stochastically or run a control arm.
- The `[workspace]` key guard in `kaine/boot/wiring.py` accepts `arm`, and a
  test runs the real boot phase that builds the workspace on the shipped
  configuration and on every study configuration.
- Greedy decoding moves out of the `first_configuration` profile (operator decision,
  matching paper §6.1): ordinary boots sample at the shipped temperature 0.7.
  A new study layer, `config/studies/<name>.toml` selected by `KAINE_STUDY`,
  is applied after the operator config. Three study configurations,
  `workspace_mediation_competitive`, `_matched` and `_pooled`, set greedy
  decoding and the arm. A study file may set only the `[language]`,
  `[workspace]`, `[experiment]` and `[individuation]` tables, and the run
  context and manifest record the study's name. The module-addition runner clears `KAINE_STUDY` for its
  child processes, whose overlay is their study configuration.
- The matched arm refuses a selection whose context does not say whether the
  tick is a broadcast tick. Its generator is not persisted: draws reproduce
  within one uninterrupted run, and a restart or revive restarts the stream
  from the seed.
- The language module no longer lets an empty pooled broadcast replace its cached coalition.
- The individuation probe gets its own decoding temperature,
  `[individuation].probe_temperature` (default 0.0, at least 0), wired from
  the individuation runtime to the language module, so moving greedy decoding out of the
  default profile does not change the probe's conditions.

## Capabilities

### Modified Capabilities

- `workspace`: arm selection, the matched draw, the pooled broadcast, and the
  pooled context rule.
- `research-event-log`: the workspace record carries the arm.
- `configuration-loading`: the study layer.
- `language`: greedy decoding only in study configurations; the cache ignores empty broadcasts.
- `individuation-boundary`: the probe's own decoding temperature.
- `module-ignition-study`: the study configuration sets greedy decoding and the
  competitive arm.

## Impact

- `kaine/workspace/core.py`, `kaine/modules/context.py`,
  `kaine/evaluation/observers/research_event_observer.py`,
  `kaine/cycle/__main__.py`, `kaine/research/ignition_study/overlay.py`,
  `kaine/research/ignition_study/runner.py`, `kaine/boot/wiring.py`,
  `kaine/config.py`, `kaine/modules/language/module.py`,
  `kaine/cycle/individuation_runtime.py`, `kaine/experiment/run_context.py`,
  `config/kaine.toml`,
  `config/profiles/first_configuration.toml`, `config/studies/`, docs, tests.
- The individuation probe decodes at its own temperature,
  `[individuation].probe_temperature` (default 0.0), which the language module's probe
  request uses and its probe conditions report under the existing
  `temperature` key. The voice's temperature never reaches the probe, so a
  reference captured under the old greedy default stays valid after this
  change, and later study or voice settings cannot change the probe's
  conditions. `config/profiles/minimal_experiment.toml` is unchanged.
- With the default arm, selection, access, inhibition and the context are
  unchanged; each broadcast's metadata gains the `arm` key.
- Not covered: the null-context evaluation and the positive control (a
  separate change), and a runner for the ablation itself; an ablation run
  selects its arm with `KAINE_STUDY`.
