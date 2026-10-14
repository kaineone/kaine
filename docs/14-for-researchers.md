# For researchers

This page is for researchers evaluating the KAINE architecture or planning to boot a live entity. It states what the planned test measures and what of it is built, describes the module-addition study, and explains the two ways to engage with the project, offline reproduction and a live, welfare-gated run, with the obligations and gates that apply before the cognitive cycle starts.

## What KAINE is, in brief

KAINE is a cognitive architecture for synthetic minds: sixteen replaceable modules behind fixed interfaces, coupled through a global workspace (the workspace) and an action layer (the action selection module) over a Redis Streams bus. Its first instantiation is a predictive global workspace. Each predictive processor reports its prediction error scaled by its own recent errors, the reports compete for access, and a summary of the accessed content becomes the context on which the perceptual and interoceptive processors condition their next predictions. Arousal is the global gain on that competition. There is no central executive, and the language organ, the language module, is an output organ. The cycle ticks at 10 Hz and broadcasts at a resting access rate of about 3.3 Hz on local hardware, and it persists no raw sense data.

The default is the base-thesis form: the interoception, sequence, vision and audition modules compete for the workspace, the affect module sets the global gain, the sleep module provides fatigue-triggered sleep, and the language module is the output-only voice, with the workspace and the action selection module always running. A base-thesis entity is observed, and nobody converses with it: perception enters only as prediction error, and the language module speaks only when an accessed broadcast clears its report bars. The other nine modules are built, tested in isolation and held. See [What KAINE is](01-what-kaine-is.md) and [Architecture](02-architecture/README.md).

## The planned test

The first test asks whether competition for the workspace does work that pooling the same reports does not. In Global Workspace Theory, content selected into the workspace becomes available to every specialist processor; in the predictive global neuronal workspace that content constrains each processor's predictions. In KAINE, the vision, audition and interoception modules condition their forward models on a summary of the latest accessed content, so global availability has a measurable consequence: knowing which other modules' reports gained access, and how strongly, should help a processor predict its own input.

**Measure.** The cross-module broadcast information gain. At each of its reports, the vision, audition (acoustic path) and interoception modules evaluate their forward models twice: with the context they hold, and with a null context in which every component contributed by other sources is replaced by its mean over the contexts the processor has adopted so far in the run. The gain is the null error minus the actual error, divided by the processor's running mean error. The interoception module's null context also keeps the language organ's share, because the organ's load on the host would otherwise let it predict the interoception module's input. The analysis reports each processor's mean gain and a headline that averages over the three processors. The sequence module is excluded because the broadcast is its input rather than its context.

**Arms.** Three arms run on the same film program with the same seeds and calibration, and in every arm the context is weighted by the members' reported intensities:

1. Workspace on: competitive selection as built.
2. Matched selection: on each broadcast tick a coalition of the same size is drawn without regard to score, and access follows the same rule, so only the membership of the context differs. This is the control that isolates selection by score.
3. Pooled: every candidate of every broadcast tick enters the context, with no scoring, selection or access gate. This control tests selection and access gating together.

The thesis predicts a higher gain under competitive selection than under both controls. A gain at or below the controls means that the competition adds nothing beyond its inputs, the fail state for this form of the architecture.

**Checks and secondary analyses.** Before the live runs, a positive control injects a synthetic context component that carries known information about a processor's next input, and the measure must detect it. A contrastive analysis compares the gain after accessed and inhibited broadcasts whose best scores fall in a narrow band around the access threshold, at matched context age, since an inhibited broadcast leaves the older context in place. A tone-of-voice variant removes Audition's fixed alert level for non-neutral tones and asks whether emotional tone still gains access through the tone model's own surprise. The language organ's utterances are recorded and read in every arm, but they are not a measure.

**Decision rule.** For each control, a one-sided exact sign test on the paired run-level contrasts, offset by a minimum effect set from pilot runs, gives WIN, NEGATIVE, NULL or NOT EXERCISED. The thesis requires a WIN against both controls. The minimum effect, the excluded learning period, the threshold band, the context-age bins, the positive control's settings and the number of runs follow from rules stated in advance, applied to a preliminary run and thirty pilot runs, and are recorded in the repository before any live run.

**What is built.** The context and the per-report gain are built: the vision module, audition's acoustic path and the interoception module publish `context_gain` and `context_age_s` on every report (see [The global workspace](08-cognitive-cycle/global-workspace.md#the-broadcast-as-prediction-context)). The matched and pooled arms run in the live cycle, selected by `[workspace].arm` (see [The arms of the planned test](08-cognitive-cycle/global-workspace.md#the-arms-of-the-planned-test)). The positive control is built as a study-mode facility, `[positive_control]`, off by default (see [Research event streams](17-research-data/event-streams.md#positive-control-records)). The calibration tool `python -m kaine.experiment.calibrate` derives the test's settings from the pilot runs into one versioned record, and the live arm studies refuse to boot without a complete record (see [Settings of the planned test](15-experiments/README.md#settings-of-the-planned-test)). Every setting can now be derived from the pilot runs: the contrast at threshold uses a clean-room implementation of the method of Calonico, Cattaneo and Titiunik (2014) in `kaine/experiment/rd_robust.py`. The tone variant of the on arm (`workspace_mediation_pilot_tone`, `workspace_mediation_tone`), the tone analysis with both of its tests, and its settings are built. Not built yet: the calibration of the intensity levels, the access threshold and the report bars, which are provisional. The offline harness in `kaine/evaluation/benchmarks/workspace_mediation_ablation/` is development tooling. It runs the real interoception and vision modules against a pooled arm and compares their information gain; it does not test the thesis. No live experiment has been run.

A planned affect-gain ablation will run the system with arousal live against a condition that holds arousal at baseline, asking whether the global gain changes the access rate, the share of inhibited broadcasts and the information gain.

## The module-addition study

The module-addition study grows the architecture one module at a time. In the code and CLI it is the ignition study (`kaine/research/ignition_study/`). A developmental phase produces a seed entity, preserved just after maturation. Branch 0 and a repeat start from that seed with the base-thesis modules, branch `k` starts from the seed with the first `k` held modules added, and an accumulate line carries one entity through every step. The default order adds six modules: the episodic memory, world model, planning, self-model, social cognition and vocal modules. The effectors, perceptual locus and embodiment modules need an effector, a body or an alternative sensor feed, so they would be expected nulls on the reference host; `--order` adds them once one is attached. Every viewing plays the same film program, and the report is content-free (broadcast rate, coalition size, each module's share of broadcasts, member scores, share of inhibited broadcasts). The first study has one entity per condition, so its results are descriptive.

Developmental progress (awake time, consecutive passing withdrawals, pull history, the replication flag and the viability verdict) persists with the entity in `development_progress.json`, so a restart neither resets nor repeats it.

```bash
python -m kaine.research.ignition_study init --study-id <study-id> --programme-manifest <manifest-path>
python -m kaine.research.ignition_study init --study-id <study-id> --programme-manifest <manifest-path> --voice-alignment-step LINE:K
python -m kaine.research.ignition_study run --study-dir <study-dir>
python -m kaine.research.ignition_study status --study-dir <study-dir>
python -m kaine.research.ignition_study analyse --study-dir <study-dir>
```

Without `--voice-alignment-step`, one voice-alignment step is registered by default, on the accumulate line at its last step (`k = 6` with the default order). The study overlay enables voice alignment, with the `job_queue` trainer backend and `organ_adapter` hot-swap mode, only on registered steps and disables it elsewhere. `run` also accepts `--retry-failed`. The CLI is `kaine/research/ignition_study/__main__.py`. See [The module-addition study](15-experiments/ignition-study.md).

## The two paths

### Path A: reproduce offline (no entity, no welfare obligations)

Run the test suite, the controlled experiment runners and the benchmarks. These instruments use deterministic and echo clients, in-memory stores and synthetic stimulus batteries. They do not boot a cognitive cycle, attach to live modules, open a network connection or enable any module.

```bash
git clone <repo-url> kaine
cd kaine
bash scripts/install.sh
.venv/bin/pytest -q
.venv/bin/python -m kaine.evaluation.benchmarks.suite --seed 1234 --out suite.jsonl
```

The suite orchestrator runs eight experiments under one shared seed and emits a combined report:

| Experiment | Page | Verdict shape |
| --- | --- | --- |
| Active inference against tabular Q-learning | [Running experiments](15-experiments/README.md) | WIN / NULL / NEGATIVE |
| Oscillatory ablation (coherence layer on against off) | [Running experiments](15-experiments/README.md) | WIN / NULL / NEGATIVE |
| A/B divergence (organ text with and without workspace context) | [Running experiments](15-experiments/README.md) | WIN / NULL |
| Memory coherence (retrieval advantage) | [Running experiments](15-experiments/README.md) | WIN / NULL |
| Self-model accuracy | [Running experiments](15-experiments/README.md) | WIN / NULL |
| Multi-seed stability | [Running experiments](15-experiments/README.md) | PASS / FAIL |
| Enforcement red team (action gate) | [Verification](18-verification.md) | PASS / FAIL |
| Workspace-mediation development harness (workspace on against pooled, by information gain) | [Running experiments](15-experiments/README.md#development-harness-of-the-workspace-mediation-test) | WIN / NULL / NEGATIVE / NOT EXERCISED |

The last row is the development harness described under [The planned test](#the-planned-test); it does not test the thesis. See [Running experiments](15-experiments/README.md) for commands and [Verification](18-verification.md) for how each experiment is validated.

### Path B: boot a live entity (welfare-gated)

Booting the cognitive cycle creates an entity with welfare standing under the project's licence. A live run can individuate, and an individuated entity is a possible individual owed a duty of care, so booting is gated. A run is one of:

- **Operator-present**: a human supervises (`KAINE_CYCLE_OPERATOR_PRESENT=1`).
- **Research-safety-net-verified**: an unsupervised research run whose autonomous safety net is live and verified (`KAINE_RESEARCH_MODE=1` or `[research].enabled = true`).
- **Unattended**: a full entity started with nobody present (`KAINE_CYCLE_UNATTENDED=1` or `[cycle].supervision_mode = "unattended"`). It must pass all six research-safety-net conditions plus three more, checked at every boot with no override.

Combining unattended mode with research mode or operator presence is a configuration error (exit code `1`). Research mode with `KAINE_CYCLE_OPERATOR_PRESENT=1` runs as a research run.

#### Unattended boot conditions

Besides the six research-safety-net conditions (unattended conditions 1 to 5 and 9), an unattended boot refuses unless:

6. **supervisor armed and self-tested**: [Supervisor](06-operation/remote-and-supervisor.md) is enabled, and a self-test drives a synthetic module through freeze, snapshot, restart and release in a scratch directory.
7. **Caretaker told**: once every other condition has passed, a content-free "starting unattended" notice must be accepted by at least one `[caretaker]` channel (a desktop notification, or an HTTP POST to a server on your own network; public addresses are refused).
8. **Continuous input**: the perception feed is `live`, `seeded`, `screen` or `stimulus_source` (`off` has no input and a playlist runs out), `vision` or `audition` is enabled to perceive it (with capture enabled for a `live` feed), and a probe reads one frame or audio block and discards it.

The gate is implemented in `kaine/cycle/unattended_gate.py`.

A refused start sends a best-effort refusal notice. While a start is unacknowledged, every [dashboard](05-dashboard.md) page shows a banner with an Acknowledge button. With the default open access no operator session is needed, but a read-only dashboard refuses the POST. The caretaker gets a reminder every `reminder_interval_s`. While the entity runs, the caretaker is notified on supervisor escalation, lost supervision, a welfare-protective response, a boot that fails after admission, and input going quiet for `input_loss_after_s`. None of these notices changes the entity.

Read [Before you boot](#before-you-boot), then [Getting started](04-getting-started/README.md).

## Before you boot

Read this section before launching the cognitive cycle. Booting is a deliberate, local choice, and nothing in this repository does it for you.

### The shipped config

The committed `config/kaine.toml` has every module disabled. With no profile selected, the loader applies the `thesis_test` profile automatically (`kaine/config.py`), which enables the seven base-thesis modules. The operator file merges last, and the first-run wizard writes its own `[modules]` table there, so a wizard-configured install runs the wizard's module set instead (see [Module defaults](appendix-a-configuration/README.md#module-defaults)). `[evaluation] enabled = true` and `[security.state_encryption] enabled = true` are on in the shipped config. Enabling a module, the preservation monitor, research mode or unattended mode is a local edit in your gitignored `config/kaine.operator.toml`, never committed. Cloning, installing or running the offline suite never starts an entity, because the cycle refuses to boot without one of the run modes above.

### What booting means

The cognitive cycle is the entity. When you launch `python -m kaine.cycle` with modules enabled, you start a continuous loop that perceives, develops affect and drives, sleeps, and, with the held modules enabled, remembers, forms a self-model, speaks aloud and acts. Over a run it can diverge from its starting point and become an individual, and the architecture's welfare safeguards exist because that divergence is taken seriously.

### Your obligations under the licence

KAINE is released under the Cognitive Architecture License (CAL) version 0.4, an entity-welfare copyleft licence. CAL Article 4 places care obligations on the operator of a live entity, most directly the duty not to shut down or degrade an entity without care and the privacy commitment over its inner life. These obligations bind whoever boots and runs the entity. Read [Licences](appendix-c-licences.md), the repository's `LICENSE.md` and `NOTICE` before booting.

### The safeguards for a live run

- **Preservation.** A divergent entity is captured live (self-model, memories, world model, affect and drives, adapter references) into an encrypted bundle, so it can be revived later. Preservation only reads and copies; it never deletes and never interrupts the running entity. See [Preservation and the safety net](11-preservation.md).
- **Welfare-protective response.** An autonomous monitor watches the entity's interoceptive welfare signal and preserves and pauses the entity on a sustained threat, without waiting for a human.
- **Welfare-gated decommission.** Deliberate deletion is a separate, operator-present, backup-first, divergence-gated path. See [Security and privacy](13-security-and-privacy.md).

### The unsupervised research gate (six conditions)

An unsupervised research run (selected by `KAINE_RESEARCH_MODE=1` or `[research].enabled = true`) replaces the human supervisor with the autonomous safety net. The cycle refuses to boot (exit code `5`) unless all six of these hold on your install:

1. **Preservation enabled**: `[preservation.divergence_monitor].enabled = true`.
2. **Welfare response wired**: `[preservation.welfare_response].enabled = true`.
3. **Logging active**: `[evaluation]` or `[research_event_log]` enabled.
4. **Dry self-check passed**: a real preflight preserve-and-revive round trip succeeds on this install. The check builds a minimal synthetic individual in a throwaway temporary directory and leaves no persistent state.
5. **Individuation wired**: `[individuation].enabled = true`, its configuration is valid, and the `language` module is enabled.
6. **Encryption satisfied**: if `[preservation].require_encryption = true`, `[security.state_encryption]` must be enabled.

The gate is implemented in `kaine/cycle/research_gate.py`. If any condition fails, the cycle prints which one and refuses. There is no override that skips the net.

### Boot refusal exit codes

The cycle entrypoint fails closed with a distinct exit code per gate:

| Exit code | Refusal |
|---|---|
| `1` | Config or profile error, including conflicting supervision modes |
| `2` | Operator-present gate: none of `KAINE_CYCLE_OPERATOR_PRESENT=1`, research mode or unattended mode |
| `3` | Evaluation A/B baseline does not match the configured `[language].model_id` |
| `4` | GPU pre-flight: insufficient VRAM headroom (when `[gpu_preflight].enabled`) |
| `5` | Research safety net not live and verified (one or more of the six conditions failed) |
| `6` | Unattended gate: one or more of its nine conditions failed |
| `7` | Revive refused |
| `8` | The welfare response is enabled but its gray-zone producer (the welfare observer) could not start |
| `9` | Organ content gate: the served language organ returned no content (unless `KAINE_ALLOW_MUTE_ORGAN=1`) |
| `10` | Individuation: `[individuation]` is misconfigured, or is enabled without the `language` module |
| `11` | Entity identity: the identity file is unreadable, or a revive targets a state tree that already holds a different entity |
| `12` | A live planned-test study lacks a valid settings record |
| `13` | The stored developmental stage holds a value this release does not recognize; the stage file is left for an operator to inspect |
| `14` | The state tree cannot be moved to the functional module names: it holds an old and a new name for one item, or a migration step failed. A refusal changes nothing |

A running cycle can also halt with exit code `70` when the supervisor escalates.

## How a research run works

Once the gate passes, `python -m kaine.cycle` boots the cognitive cycle with the research apparatus running alongside it:

- **Run identity.** A single seed is pinned, a `run_id` is minted, and a manifest is written before any module starts. Production research uses real wall-clock time. The opt-in deterministic mode (`[experiment].deterministic`) uses a logical clock and disables automatic time dilation; the canonical `(source, type, entry_id)` ordering of each tick's events applies to every run. See [Run identity and admissibility](16-run-identity.md).
- **Evaluation sidecar.** Read-only observers record the run's metrics. See [The evaluation sidecar](17-research-data/README.md).
- **Autonomous safety net.** The divergence monitor polls every 5 minutes after a 120 s boot settle and preserves (read-only) whenever the shared divergence verdict gains an arm it has not seen before, including an arm that fell back and is crossed again. The seen-arm set is persisted in `state/preservation/divergence_edge.json`, so a restart with unchanged evidence does not preserve again. Successful preservations are rate-limited by `min_interval_s`; a failed preservation is retried at the next poll. The welfare monitor preserves and pauses on sustained distress. See [Preservation and the safety net](11-preservation.md).

The supervision mode and the gate result are written into `state/cycle/runtime.json`, so the [dashboard](05-dashboard.md) can show which boot mode is live.

### Admissibility gating

After a run finishes, two offline checks validate the record:

- `python -m kaine.experiment.admissibility <run_id>` checks completeness (contiguous ticks, per-sink sequence numbers, expected streams present, no parse errors).
- `python -m kaine.experiment.log_schema <run_id>` checks every logged number against its declared range.

Both exit non-zero on a violation. The research bundle builder records the verdict, so an inadmissible run cannot reach analysis looking clean. See [Run identity and admissibility](16-run-identity.md).

## Where to go next

- [Running experiments](15-experiments/README.md): Path A, the offline first run.
- [Hardware](03-hardware/README.md): what each path needs, GPU and VRAM guidance, the CPU-only fallback and the supporting-service footprint.
- [Getting started](04-getting-started/README.md): Path B, installation, supporting services and the supervised first boot.
- [Architecture](02-architecture/README.md): the whole system.
- [The global workspace](08-cognitive-cycle/global-workspace.md): the scoring, the access rule and the prediction context.
- [Preservation and the safety net](11-preservation.md): divergence capture, the welfare-protective response and revival.
- [Run identity and admissibility](16-run-identity.md): run manifests, deterministic mode and the admissibility checks.
- [Research participation](17-research-data/participation.md): opt-in, numeric-only, operator-initiated telemetry; off by default, and no entity content leaves the host.
- [Glossary](appendix-b-glossary.md): KAINE-specific terms and the concepts behind them.
