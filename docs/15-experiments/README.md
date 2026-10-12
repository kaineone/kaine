# Running experiments

KAINE's research programme has two live parts and a set of offline instruments. The live parts are the planned workspace-mediation test, which asks whether competition for the workspace does work that pooling the same reports does not, and the module-addition study, which grows an entity one module at a time. The offline instruments measure specific mechanisms without booting an entity: the controlled instrument runners, the active-inference benchmark, the oscillatory ablation, the development harness of the workspace-mediation test, the shared-seed suite and the multi-seed stability harness. Use the offline instruments when you need reproducible numbers, a seeded null result, or a check that a nondeterministic process is stable across seeds.

No live experiment has been run yet. Live runs are recorded by the evaluation sidecar and the study's broadcast log; see [The evaluation sidecar](../17-research-data/README.md).

## The live programme

### The module-addition study

The module-addition study seeds an entity through a developmental phase and preserves it just after maturation. `branch 0` and a `repeat` start from that seed with the base-thesis modules, and `branch k` starts from the seed with the first k held modules added in a fixed order. An accumulate line carries one entity forward through every step. The first study adds six modules, in the default order the episodic memory, world model, planning, self-model, social cognition and vocal modules. The effectors, perceptual locus and embodiment modules need an effector, a body or an alternative sensor feed, so they join once one is attached. Every viewing plays the same film programme, and the report is content-free and descriptive, with one entity per condition.

The code and the configuration call it the ignition study (`kaine/research/ignition_study/`). [The module-addition study](./ignition-study.md) covers running it, resuming it and reading its report.

<a id="workspace-mediation-ablation"></a>

### The planned workspace-mediation test

The planned test runs before any held module joins. It follows the paper's §6.3. Each perceptual and interoceptive processor (the vision module, the audition module, the interoception module) conditions its forward model on the broadcast context: a 24-component summary of the accessed members of the latest accessed broadcast (which modules' reports gained access, which event types, how strongly and how recently), weighted by the intensity each member reported. If global availability does work, knowing which other modules' reports gained access should help a processor predict its own input.

**Primary measure: cross-module broadcast information gain.** At each report, the vision, audition (its acoustic path) and interoception modules evaluate their forward models twice: once with the context they hold and once with a null context in which every other source's share is replaced by its mean over the contexts the processor has adopted so far in the run. The gain is the null error minus the actual error, divided by the processor's running mean error. The interoception module's null context also keeps the language module's share, because the language organ's load on the host would otherwise predict the interoception module's input. The sequence module is excluded, since the broadcast is its input and not its context. The analysis reports each processor's mean gain and a headline that averages over reports and then over the three processors. The processors publish the per-report gain as `context_gain`, with `context_age_s`, on their report events; see [Research event streams](../17-research-data/event-streams.md#processor-report-fields).

**Arms.** Three arms run on the same film programme with the same seeds and calibration, and the context is weighted by reported intensity in all three.

1. Workspace on: competitive selection as built. The top-ranked candidates (up to five) form the coalition, and the members whose scores reach the access threshold are accessed and enter the context.
2. Matched selection: a coalition of the size competitive selection would keep, drawn without regard to score, under the same access rule. Only this arm isolates selection by score.
3. Pooled: every candidate of every broadcast tick enters the context, with no scoring, selection or access gate. This arm tests selection and access gating together.

The thesis predicts a higher information gain under competitive selection than under both controls. A gain at or below the controls means the competition adds nothing beyond its inputs, which is the fail state for this form of the architecture.

**Positive control.** Before the live runs, a synthetic context component that carries known information about a processor's next input is injected, and the measure must detect it. The component is the next input projected on its first principal component, estimated from a preliminary run, plus noise set from the pilot runs so that its expected effect equals the smaller minimum effect. A measure that fails this check cannot support a null.

**Secondary analyses.** A contrastive analysis compares the gain after broadcasts just above the access threshold (accessed) with the gain after broadcasts just below it (inhibited), at matched context age, since an inhibited broadcast leaves the previous context in place. A tone variant of the workspace-on arm sets every tone event's intensity from the tone model's error ratio alone and asks whether emotional tone is still accessed more often than neutral speech. The language organ's utterances are recorded and read in every arm but are not a measure.

**Decision rule.** For each run and each control, the paired contrast is the headline gain of the workspace-on arm minus that of the control. A one-sided sign test on the run-level contrasts, offset by a minimum effect, gives WIN, NEGATIVE or NULL against each control, and the thesis needs a WIN against both. The verdict is NOT EXERCISED when the workspace-on arm never has more candidates than the coalition holds. The minimum effect, the initial learning period excluded from each run, the analysis bands and bins, and the number of runs follow from rules stated in advance and are recorded in the repository before the live runs (see [Settings of the planned test](#settings-of-the-planned-test)).

**What is built.** The context and the measure's inputs are built: the workspace records `access_threshold` in every broadcast's metadata, `kaine/modules/context.py` computes the context and the null context, the vision, audition and interoception modules learn the context online as an extra forward-model input, and the three processors publish `context_gain` per report. The three arms are built and selected by `[syneidesis].arm`; every broadcast records its arm. The positive control is built and off by default (`[positive_control]`; check complete control runs with `python -m kaine.experiment.positive_control <run_id> [<run_id> ...]`). The calibration tool and the boot check of the live runs are built (below). The live calibration of the processors' intensity levels, the access threshold and the report bars is not built yet. In general use the organ samples; in the planned runs its decoding is greedy, set by the study configuration. A live workspace-mediation run selects its arm and greedy decoding together with `KAINE_STUDY=workspace_mediation_competitive`, `workspace_mediation_matched` or `workspace_mediation_pooled`, and pins its seed with `[experiment].seed`; the module-addition study's overlay pins greedy decoding with the competitive arm. The planned affect-gain ablation (arousal live against arousal held at baseline) is also not built.

### Settings of the planned test

Paper Appendix A.8 fixes every remaining setting of the test from one preliminary run and thirty paired pilot runs, by rules stated before any of them runs. The code follows those rules in this order.

1. **Preliminary run.** `KAINE_STUDY=workspace_mediation_preliminary`, on a seed never used again. The positive control runs in mode `estimate_pc` and, at shutdown, writes each processor's first principal component and input mean under `data/evaluation/positive_control/<run_id>/`.
2. **Pilot runs.** Set `principal_components_run` in `config/studies/workspace_mediation_pilot_competitive.toml` to the preliminary run's id. Then run each pilot as three runs on one seed, with `KAINE_STUDY=workspace_mediation_pilot_competitive`, `_pilot_matched` and `_pilot_pooled`. The competitive pilot also carries the positive control's SNR ladder. A pilot that is NOT EXERCISED is replaced until thirty count. No pilot seed is used again.
3. **Calibration.** List the preliminary run and every attempted pilot, in the order attempted, in a plan file:

```json
{"preliminary_run": "<run id>",
 "pilots": [{"competitive": "<run id>", "matched": "<run id>", "pooled": "<run id>"}]}
```

and run

```bash
python -m kaine.experiment.calibrate plan.json --out config/studies/workspace_mediation_settings.json
```

The tool checks each run's study, seed and film program and writes one versioned settings record with its inputs (run ids, seeds, manifest and record hashes), the tool version, the fixed constants and every derived value: the NOT EXERCISED fraction r_NE and the planned run count ceil(102 / (1 - r_NE)); the learning period T_learn (MSER-5 on the cross-pilot average gains in batches of five, searching truncation points 0 <= d <= b - 5; the largest median entity time of the truncation point over arms and processors, rounded up to a second; the pilots are too short when, for any arm and processor, there are fewer than ten batch means or d* > b/2); the pilot standard deviation of each control's contrast and the minimum effect, half of it; the positive control's target theta_PC (the smaller minimum effect), its minimum effect theta_PC / 2, each processor's SNR (interpolated in log SNR on the ladder), and its report count n_PC (Currie's detection limit with Browne's upper confidence factor). The paper names the run-level variance at SNR_j, but the variances are measured only on the ladder's rungs, so the tool takes the larger variance at the two rungs that bracket SNR_j; this is an approximation that errs on the side of more reports. The fixed constants and rules live in `kaine/experiment/calibration_rules.py`, each with its source. It prints the record's digest, `record_sha256`, which goes into the preregistration, and every run that the record gates writes the same digest into its run manifest as `settings_record_sha256`. It exits 0 when the record is complete, 1 when it wrote an incomplete record, and 2 when an input is wrong (it then writes nothing). A ladder that is malformed, used another principal component or did not finish cleanly blocks the SNR and the report count rather than stopping the tool.

The arms of a pilot must differ only in the workspace manipulation, and the on arm's pilot also carries the positive control's ladder. The control therefore runs after each report is published, off the report path, and the tool records every pilot run's report rate per processor (reports per entity second). It also records, for each processor and control arm, the on arm's and the control arm's mean rates, the control arm's run-to-run standard deviation, and whether the difference exceeds it (`report_rate_check`). These are recorded for inspection only: the paper has no rule on report rates, and nothing is blocked on them.

A rule that cannot be applied fails closed: its value is null, `blocked` gives the reason, and the record is incomplete. No setting is blocked by design any more; a record is complete when the pilot data let every rule be applied.

The contrast at threshold (paper A.8) is a sharp regression discontinuity in the on arm: the running variable is a broadcast's best score minus the access threshold, and the outcome is the mean gain of the included reports whose prediction followed that broadcast (`prediction_broadcast_tick`), grouped by the age of the context they used (`prediction_context_age_s`). The tool takes theta_band and b_band, the MSE-optimal bandwidths of the local-linear jump estimate and of its local-quadratic bias correction, from the pooled on-arm pilot broadcasts (one observation per broadcast with a following included report). The age bins are the quintiles of the age over the reports that follow broadcasts within theta_band of the threshold, and the contrast's minimum effect is c_eff times the standard deviation of the run contrast over the counted pilots. The run contrast is the mean, over the age bins whose two sides can be fitted, of the bias-corrected jump. A side can be fitted when it holds at least ten distinct scores within each bandwidth and both of its weighted least-squares problems have a condition number of at most 10^8 (paper A.8).

The estimator and the bandwidth selector are in `kaine/experiment/rd_robust.py`, written only from Calonico, Cattaneo and Titiunik (2014) and its supplement. The authors' own package is licensed GPL-3.0-only, which CAL 0.4 cannot take as a dependency, so it is not used. The supplement prints the selector's regularization terms with the variance of a derivative where they are added to a squared coefficient; the module uses the variance of the coefficient, the scale on which the selector reproduces the paper's reported average bandwidths. `kaine/experiment/threshold_contrast.py` reads the logs, computes each run's contrast, the sign tests, and, for each bin, the robust interval of the estimate pooled over runs with standard errors clustered by run (Liang and Zeger, joint over both sides of the threshold, with the residuals of the local-quadratic fit and the CR1 small-sample adjustment of Cameron and Miller 2015, K = 6). These intervals are reported and do not enter a test.

The tone analysis's settings come from a tone-variant run in every pilot (`"tone"` beside the three arms in the plan, study `workspace_mediation_pilot_tone`, the pilot's seed). The tone bins are the quintiles of the tone error ratio over all classified tone events, emotional and neutral together, of the counted pilots' tone runs. The minimum effect of each of the two tone tests, on the difference and on the adjusted difference over the bins, is c_eff times the standard deviation of its run-level statistic over those runs, leaving out runs where it is undefined. Run r of the live tone variant (`workspace_mediation_tone`) uses the seeds of run r of the arms; the variant is planned with the arms' run count, and runs are added until at least 102 give a defined difference. The tool refuses an arm pilot whose tone events carry the variant's rule.

4. **Positive control.** With a complete record, run `KAINE_STUDY=workspace_mediation_positive_control` over complete runs of the film program and check them with `python -m kaine.experiment.positive_control <run ids>`.
5. **Live runs.** `KAINE_STUDY=workspace_mediation_competitive`, `_matched` and `_pooled` refuse to boot (exit code 12) without a valid, complete settings record, or with a seed that the preliminary or a pilot run used. The record is valid only when its constants are the paper's (n_cal 30, c_eff 0.5, q_pow 0.65, power 0.9, alpha 0.05, the MSER settings, five bins and the SNR ladder), thirty pilots counted and n_exact is 102. Each workspace-mediation study must declare the role that matches its name, any configuration with `[planned_test].role = "test"` or `"positive_control"` needs the record whatever the study is called, and a live test run may carry the positive control only in mode `control`. The record lists its run set: thirty counted pilots with distinct seeds, every attempted pilot that was NOT EXERCISED, and a sha256 of each run's manifest and research-log records. At boot the gate recomputes those hashes when the run data is on the host and refuses a mismatch; when the data is absent it records that in the run manifest and lets the run start. Runs are added until at least 102 enter each control's test.

## What the offline instruments share

Every instrument below is headless and synthetic. None boots an entity, attaches to a live module, starts a real bus connection or opens a network connection. Each run pins the global seed with `set_global_seed(seed)` and writes seeded JSONL. WIN, NULL and NEGATIVE are reportable outcomes in their own right. NOT EXERCISED (`NOT_EXERCISED` in the shared vocabulary) says that a comparison did not take place; it is neither a WIN nor a NULL and counts as evidence for nothing.

## Controlled instrument runners

Three measuring instruments that normally run as passive live sidecars can be run as seeded offline experiments of the same shape. The runner is the package [`kaine/evaluation/benchmarks/instrument_runners/`](../../kaine/evaluation/benchmarks/instrument_runners/). Run any one with:

```bash
python -m kaine.evaluation.benchmarks.instrument_runners ab_divergence   --seed 1234 --out ab.jsonl
python -m kaine.evaluation.benchmarks.instrument_runners memory_coherence --seed 1234 --out mem.jsonl
python -m kaine.evaluation.benchmarks.instrument_runners self_model       --seed 1234 --out sm.jsonl
```

Each runner uses a fixed stimulus battery and the shared `Verdict` (WIN or NULL).

### A/B divergence runner

The runner measures the dynamic range of the production `divergence_control` seam. A fixed battery of `(utterance, conditioning)` cases runs through that seam with a deterministic echo client that returns its prompt verbatim. Empty conditioning makes both arms byte-identical, so divergence is about 0. Heavy conditioning makes them differ by the conditioning block, so divergence is large.

The verdict is WIN when every empty case stays near 0 and every conditioned case exceeds the floor. NULL means the meter is flat on that battery.

The embedder is the dependency-free `HashEmbedder` (blake2b token buckets). Blake2b is deterministic across processes, so a seeded run reproduces its metrics on any machine.

Because the runner uses an echo client and no live language organ, it shows the meter's dynamic range on the production path. Measuring a live model's divergence is left to the live observer.

### Memory coherence runner

The runner measures retrieval advantage. A fixed battery of unique fabricated facts is planted into a real in-memory `MnemosCore` (`FakeEmbedder` with `InMemoryStorage`). A full-system arm, whose answer comes from what the episodic memory module returns, is scored against a bare arm with no memory using the production `score_async`.

The verdict is WIN only when all of these hold:

- full-system retrieval accuracy exceeds the bare arm by at least the floor on the planted battery;
- a fact that was never stored yields the `NON_RECALL_MARKER` (scored 0, never a confabulated positive);
- the advantage vanishes when the same client runs against an emptied episodic memory module, which shows the advantage comes from retrieval and is not hard-coded.

Otherwise the verdict is NULL.

`kaine.evaluation` does not import `kaine.modules.*` at module top level. The real episodic memory module is built by an injected `mnemos_builder` callable, and the CLI default uses a function-local import inside `_default_mnemos_builder`, so the import never runs when the module is imported.

### Self-model accuracy runner

The runner checks whether the self-model module scorer's fixed-threshold heuristic reproduces the expected score. A fixed battery of `(planted-signal, claim, expected-score)` cases plants known affect and activity signals into a temporary evaluation-logs directory and runs the real `EidolonAccuracyRunner` scorer on a self-description carrying a known claim.

The verdict is WIN when the scorer reproduces every expected score, and NULL otherwise.

A WIN means that the scorer's fixed-threshold arithmetic behaves as specified. It says nothing about calibration or about whether the entity knows itself, and the verdict detail, the JSONL `validates` field and the printed summary all say so. A result with no scorable claim is recorded as no evidence (aggregate `null`), which is distinct from a claim scored 0.

### Reproducibility and null results

Given the same `--seed` and battery, each runner reproduces its verdict and its metrics. A NULL is a reportable result: the meter was flat, the retrieval advantage did not hold, or the scorer mismatched.

## Active-inference benchmark

The active-inference benchmark tests one of the paper's falsifiable claims about the planning module. The planning module's bounded discrete active-inference decisions are compared with a reinforcement-learning baseline, matched on observation model and reward, over bounded discrete tasks. The benchmark reports decision quality, sample efficiency and the value of epistemic action, and emits WIN, NULL or NEGATIVE per task.

The benchmark lives in [`kaine/evaluation/benchmarks/active_inference/`](../../kaine/evaluation/benchmarks/active_inference/). It constructs discrete POMDP environments and runs both agents on them. It does not boot an entity, attach to the event bus or run a cognitive cycle, and it enables no module.

### What the benchmark compares

The active-inference agent drives the live planning module's [`PymdpEngine`](../../kaine/modules/nous/engine.py), the default expected-free-energy engine in the cognitive loop (the `[nous].backend = "numpy"` engine is not exercised here). It receives the environment's generative model (`A`, `B`, `C`, `D`) and at each step runs pymdp belief updating and computes each policy's expected free energy `G`. It samples its policy from the posterior `softmax(γ·(−G) + ln E)` with γ = 16, the value the NumPy engine uses. The engine's pymdp `Agent` is built with pymdp's default precision of 1.0, so the benchmark computes the posterior itself, using a generator derived from each evaluation seed so that runs reproduce. Belief persists between steps.

The baseline is tabular Q-learning with ε-greedy exploration, keyed by the history of observations in the current episode (by default the whole episode, `memory = horizon`). That gives it the same information as a belief-keeping agent without a model: on the T-maze it can carry the cue to the arm, which a memoryless learner cannot (its best expected return there is 0). `memory = 0` keeps the memoryless learner as an explicit control. The baseline has no belief state. Its hyperparameters are tuned per task by a small grid on held-out seeds, and the chosen values are recorded.

The two agents share the same observation model and the same reward: the preference vector `C` encodes the reward the Q-learner receives. Every result record carries `reward_matching`.

### The task suite

1. `tmaze_epistemic`: a 5-location T-maze whose rewarding arm is hidden until the agent visits a cue location, at the cost of a timestep. A correctly wired expected-free-energy agent with planning depth `policy_len=4` visits the cue first.
2. `exploitation`: a fully observed contextual task with a fixed optimal mapping from observation to action. Seeking information has no value here, so model-free learning is expected to be competitive.

Both tasks are parameterised over noise, horizon and information cost, so sensitivity runs are possible. Sweeping `cue_validity` on the T-maze, for example, shows the value of epistemic action falling as the cue becomes noisier.

### How to run the benchmark

```bash
.venv/bin/python -m kaine.evaluation.benchmarks.active_inference
```

Useful flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--seeds N` | `8` | Number of evaluation seeds. |
| `--rl-train-episodes N` | `800` | Q-learning training episodes per seed. |
| `--eval-episodes N` | `100` | Evaluation episodes per seed for both agents. |
| `--tasks` | both | Run a subset, for example `tmaze_epistemic exploitation`. |
| `--alpha` | `0.05` | Verdict significance level. |
| `--min-effect` | `0.3` | Minimum effect size. |
| `--out PATH` | `data/evaluation/benchmarks/active_inference.jsonl` | JSONL output path. |

The benchmark prints a summary table and writes seeded, reproducible JSONL: one record per task, seed and agent, plus a verdict record per task and a suite summary. Each record carries the task, seed, agent, the baseline's hyperparameters, raw per-episode returns, the computed metrics and the verdict.

### How to read a null or negative result

The per-task verdict is a two-sided Mann-Whitney U test across seeds on the two agents' decision-quality distributions, gated by a minimum effect size (rank-biserial `|r|`).

- WIN: the active-inference agent scores significantly higher than the baseline, beyond the effect-size floor.
- NULL: the two distributions cannot be separated at the significance level and effect size. This is a finding and not a failed run. On the exploitation task it is expected once the baseline has converged. A NULL on the epistemic task would mean the information-value machinery did not help where it should.
- NEGATIVE: the active-inference agent scores significantly lower than the baseline, which would be direct evidence against active inference as a sufficient bounded decision engine.

A NULL or NEGATIVE on the epistemic task would motivate a complementary reasoning module (paper §4).

The suite verdict aggregates conservatively: a mix of WIN and NEGATIVE across tasks is reported as NULL, so always read the per-task rows. Every verdict is computed from the raw per-seed returns by a standard test.

## Oscillatory ablation

The oscillatory-ablation runner measures whether the oscillatory coherence layer changes [workspace selection](../08-cognitive-cycle/global-workspace.md). It runs the cognitive cycle twice under identical conditions, toggling only the coherence layer, and emits WIN, NULL or NEGATIVE.

The runner lives in [`kaine/evaluation/benchmarks/oscillatory_ablation/`](../../kaine/evaluation/benchmarks/oscillatory_ablation/). It drives only the cycle engine and the workspace over a scripted in-memory bus.

### The determinism guarantee

Both arms run with the same `set_global_seed(seed)`, the same scripted stimulus, and `deterministic=True` (logical timestamps and canonical ordering within a tick). Under those conditions a run is reproducible bit for bit.

The enabled arm carries a real `CoherenceScorer` whose multiplier on an event's score lies in `[coherence_floor, coherence_ceiling]`. The disabled arm passes `coherence=None`, the baseline with the layer absent. A test asserts that the disabled arm equals, bit for bit, an independently built cycle without the layer, so any difference between the two trajectories comes from the coherence layer alone.

### The scripted stimulus

Four sources emit one event per tick:

| Source | Phase relation | Raw intensity |
| --- | --- | --- |
| `lock_a`, `lock_b` | phase-locked, PLV near 1 | `0.40` |
| `drift_a`, `drift_b` | desynchronized, low PLV | `0.60` |

With the layer absent, the drift sources rank first on every tick because their intensity is higher. With the layer enabled, the sliding windows of phase-locking values fill over the first several ticks. Once they do, the desynchronized sources' coherence factor falls toward the floor while the phase-locked sources' factor rises toward the ceiling, and a phase-locked source overtakes a drift source.

### Effect metrics and verdict

| Metric | Meaning |
| --- | --- |
| `selection_divergence_fraction` | Fraction of ticks where the top selected entry differs between arms. `0` means the layer never changed the leader. |
| `mean_ranking_divergence` | Mean normalised Spearman footrule distance between the arms' rankings on each tick. |
| `coherence_alignment_delta` | Fraction of ticks where the enabled arm's top source is phase-coherent, minus the same fraction for the disabled arm. Positive means enabling the layer moved selection toward coherent coalitions, and negative means it moved selection away. It is `0` on the neutral battery. |

The verdict is three-way:

- NULL: `selection_divergence_fraction` is at or below `--min-effect`, so the layer made no meaningful change.
- NEGATIVE: the change is meaningful but adverse, with `coherence_alignment_delta` at or below `-min_alignment` (selection moved away from the coherent coalition).
- WIN: the change is meaningful and not adverse.

A correctly labelled battery can only return WIN or NULL, because the coherence factor rises monotonically with PLV. NEGATIVE is reachable only through the `mislabeled` adversarial battery.

### The mislabeled adversarial battery

`--stimulus mislabeled` puts the `coherent=True` ground-truth label on a high-intensity source that is not the most phase-locked one, and labels the truly synchronized source `coherent=False`. The coherence layer still promotes the truly synchronized source over the decoy, which produces a negative `coherence_alignment_delta`. The battery probes a mismatch between label and reality: the layer tracks a coherence the label disagrees with.

### Running the ablation

```bash
python -m kaine.evaluation.benchmarks.oscillatory_ablation \
    --seed 1234 --ticks 16 \
    --coherence-floor 0.05 --coherence-ceiling 8.0 --plv-window 12 \
    --min-effect 0.10 --stimulus engineered \
    --out data/evaluation/benchmarks/oscillatory_ablation.jsonl
```

The values shown are the defaults. The other batteries are `neutral` (no coherence contrast) and `mislabeled`.

The same seed reproduces the verdict and the effect metrics exactly; only the wall-clock `ts` field differs between runs. The CLI prints the verdict and writes a JSONL record with per-arm trajectory digests, the effect and the verdict.

The stimulus is synthetic. The runner exercises selection and coherence under controlled phase schedules and claims no magnitude for live operation.

## Development harness of the workspace-mediation test

[`kaine/evaluation/benchmarks/workspace_mediation_ablation/`](../../kaine/evaluation/benchmarks/workspace_mediation_ablation/) is development tooling that exercises the test's pipeline offline. It is not the planned test and does not test the thesis. It runs a reduced pair of real processors, the interoception and vision modules, over an in-memory bus, compares the workspace-on arm with the pooled arm only, and measures the cross-module broadcast information gain. It boots no entity, opens no network connection and does not use the language organ.

Its two arms run from the same seed and stimulus with identically initialized modules:

- workspace on: on each tick the workspace selects a coalition of at most `top_k` candidates, and each processor adopts as its context the members whose scores reach `access_threshold`;
- pooled: every candidate of the tick enters the context, weighted by its reported intensity, with no scoring, selection, access threshold or inhibition.

The candidates on each tick are the interoception module's report, the vision module's report and `n_background` scripted background events, so the candidate count exceeds `top_k` and selection excludes. The interoception module reads scripted host metrics through a `ScriptedMetricsReader`. The vision module sees synthetic frames through a vector encoder double whose latent is the frame itself, and the harness gives its forward model a higher learning rate (`topos_lr`) so that a short run shows learning. Both modules run on an injected clock.

The measure is the one the planned test uses, read from each processor's report. The interoception and vision modules evaluate their forward models with the context they hold and with the null context and publish the per-report gain as `context_gain`. The harness averages each processor's gain over its reports after the initial learning period (`warmup_ticks`) to get `IG_j`, averages the two processors to get the headline `IG`, and reports `dIG`, the workspace-on headline minus the pooled one. The verdict is WIN when `dIG` is at least `min_effect`, NEGATIVE when it is at most `-min_effect`, and NULL otherwise. A run is NOT EXERCISED when the workspace-on arm never had more candidates than `top_k`, had no accessed broadcast, or left the gain undefined. Its verdict outcome is then `NOT_EXERCISED`, and the reason is in the detail and in `not_exercised_reason`.

```bash
python -m kaine.evaluation.benchmarks.workspace_mediation_ablation \
    --seed 1234 --ticks 160 --warmup-ticks 40 --top-k 2 \
    --access-threshold 0.05 --min-effect 0.05 --stimulus coupled \
    --out data/evaluation/benchmarks/workspace_mediation_ablation.jsonl
```

The values shown are the defaults. The `coupled` battery makes each processor's input follow events the other processor reported two ticks earlier, which is the delay with which a report reaches the context that conditions a prediction. The `independent` battery has no relation between the two inputs, so the gain should stay near zero in both arms. At the default sizes the forward models have not yet learned the relation in the `coupled` battery either: the gain stays within about 0.005 of zero in both arms and the verdict is NULL. The harness checks that the pipeline runs and reproduces; whether the measure detects information it should is the job of the planned test's positive control. The same seed reproduces the per-report gains, the verdict and the JSONL record apart from its timestamp.

## Shared-seed suite orchestrator

The suite orchestrator runs eight offline experiments under one master seed, derives an independent child seed for each, and emits a combined report with each experiment's verdict and a family-wise Holm-Bonferroni correction.

```bash
python -m kaine.evaluation.benchmarks.suite
```

Useful flags:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--seed N` | `1234` | Master seed for the whole suite. |
| `--alpha` | `0.05` | Family-wise significance level. |
| `--fast` | off | Reduced sizes for a quick smoke run. |
| `--out PATH` | `data/evaluation/benchmarks/suite.jsonl` | Combined report path. |

### What the suite runs

1. `active_inference`: the benchmark above, giving one p-value per task.
2. `oscillatory_ablation`: the coherence layer on against off.
3. `ab_divergence`: the dynamic-range battery.
4. `memory_coherence`: the retrieval-advantage battery.
5. `self_model`: the fixed-threshold scorer battery.
6. `multi_seed_stability`: the stability harness, run offline on the oscillatory ablation.
7. `enforcement_red_team`: the real enforcement layer against a case battery.
8. `workspace_mediation`: the development harness above, run over several seeds. Two one-sided sign tests on the per-seed `dIG`, offset by the minimum effect, give WIN or NEGATIVE when their p-value is at most `alpha`, and NULL otherwise. Only seeds that were exercised enter the tests, even when an unexercised seed's `dIG` is defined, and the verdict is NOT EXERCISED when no seed was exercised.

The orchestrator calls `set_global_seed(master_seed, deterministic=True)` once at the start to request GPU and cuDNN determinism on the offline path. It then spawns an independent child seed per experiment with `numpy.random.SeedSequence.spawn`, so each experiment stays reproducible. The active-inference benchmark receives its child seed through `BenchmarkConfig.master_seed`, which also seeds the environments and the Q-learner.

### Family-wise correction

The suite collects the p-values of the active-inference benchmark (one per task) and of the development harness (the p-value of the sign test that the per-seed `dIG` exceeds the minimum effect). It applies the Holm-Bonferroni correction across them at level `alpha` and reports, for each, the raw p-value, the corrected p-value and a reject or no-reject decision; a test is rejected when its corrected p-value is at most `alpha`. Each experiment's own verdict is kept unchanged, and the family-wise view is reported beside it. The family is fixed before the run. An experiment whose verdict is NOT EXERCISED ran no test, so it stays in the family with a p-value of 1 and the family does not shrink once the outcomes are known. Its own verdict stays NOT EXERCISED, and the report lists it under `not_exercised`. An individuation result can be passed to the orchestrator's API and joins the family when it is; individuation evidence needs a live entity and is collected by the cycle's individuation producer.

Everything in the suite runs offline with deterministic or echo clients, in-memory stores, scripted buses and the real headless enforcement layer.

## Multi-seed stability

Single-seed experiments rely on determinism: the same seed, the same input and `deterministic=True` give identical results. Live runs are stochastic, and the matching control is to run one configuration under several seeds and check that the summary statistics are stable.

The harness is [`kaine/experiment/stability.py`](../../kaine/experiment/stability.py). It imports nothing from `kaine.evaluation`, so both the cognitive cycle and the evaluation sidecar may use it, and it takes a callable instead of an experiment object.

### What the harness computes

`run_multi_seed(run_fn, seeds, *, metric_fn, tolerance=0.0)` runs `run_fn(seed)` once per seed, calling `set_global_seed(seed)` before each call. It reads each seed's headline metric with `metric_fn` and returns a `StabilityReport`:

| Field | Meaning |
| --- | --- |
| `seeds` | The seeds run, in order. |
| `values` | The headline metric for each seed, aligned with `seeds`. |
| `mean` / `std` | Mean and population standard deviation of `values`. |
| `cv` | Coefficient of variation, `std / \|mean\|`. |
| `verdict_counts` | How the verdicts were distributed across seeds, for example `{"WIN": 5}`. |
| `tolerance` | The CV tolerance the verdict was evaluated against. |
| `stable` | Whether the ensemble passed the stability criterion. |

`verdict_unanimous` and `reasons()` explain the verdict. `to_dict()` is JSON-safe: an infinite CV serialises as `null` with a `cv_is_infinite` flag.

### The stability criterion

The ensemble is `stable` only when the metric's coefficient of variation is within `tolerance` (an infinite CV never is) and the verdict is the same on every seed. A flipped verdict makes the ensemble unstable even when the CV is within tolerance, because a WIN on one seed and a NULL on another is a qualitative instability that the scalar spread would hide.

`assert_stable(...)` runs the ensemble and raises `StabilityError` with `report.reasons()` unless it is stable.

### Example with the oscillatory ablation

[`kaine/evaluation/benchmarks/oscillatory_ablation/stability.py`](../../kaine/evaluation/benchmarks/oscillatory_ablation/stability.py) runs the oscillatory ablation across several seeds and reports the stability of its `selection_divergence_fraction` and whether the verdicts agree:

```python
from kaine.evaluation.benchmarks.oscillatory_ablation.stability import run_ablation_stability

report = run_ablation_stability([1234, 2025, 7], ticks=16, tolerance=0.01)
assert report.stable
print(report.verdict_counts)  # {"WIN": 3}
print(report.cv)              # 0.0: the effect is identical on every seed
```

The ablation is deterministic per seed and its scripted stimulus does not depend on the seed, so the effect is identical across seeds and the verdict is unanimous.

For live runs, raise `tolerance` to the spread the live process admits and run more seeds. As used in this codebase the harness runs offline deterministic runners, which checks the stability machinery itself; it does not collect long live runs, which is the operator's job once an entity is running. Whether the running workspace itself stays stable over long runs (arousal, the access rate and the processors' errors free of runaway excursions) is a separate, planned check.

## See also

- [The module-addition study](./ignition-study.md): running the live study and reading its report.
- [The evaluation sidecar](../17-research-data/README.md): how live runs are recorded.
- [Research event streams](../17-research-data/event-streams.md): the event fields behind live analysis.
- [Research participation](../17-research-data/participation.md): submitting results back to the project.
- [For researchers](../14-for-researchers.md): reproducing and citing KAINE results.
- [Planning](../09-modules/planning.md): the module whose engine the active-inference benchmark exercises.
