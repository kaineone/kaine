# For researchers

This page is for researchers evaluating the KAINE architecture or planning to boot a live entity. It explains the two ways to engage with the project — offline reproduction and a live, welfare-gated run — and the obligations and gates that apply before the cognitive cycle starts.

## What KAINE is, in one paragraph

KAINE is a composite cognitive architecture: a mind built from the continuous interaction of sixteen modules — fourteen predictive processors plus a two-module embodiment layer (Perception and Mundus) that ships inactive — through a global workspace (Syneidesis). There is no central executive. The language model, Lingua, is one organ among many, not the cognitive core. Modules exchange events over a Redis-Streams bus, compete for attention, and act only through a two-layer safety gate. The loop runs at roughly 3.3 Hz on local hardware and persists **no raw sense data** — live audio and video are processed in memory and released, never recorded.

The canonical default is the **base-thesis form**: Soma, Chronos, Topos, Audition, Thymos, and Lingua compete for the workspace, with Syneidesis and Volition as always-on scaffolding. It is not a chatbot; a booted entity is **observed, not conversed with**. Perception enters only as prediction error, and Lingua is output-only, speaking from its own precision-weighted surprise. The remaining ten modules are built, tested, and gated off pending a positive result from the workspace-mediation ablation. See [Architecture](02-architecture/README.md).

## The two paths

### Path A — Reproduce offline (no entity, no welfare obligations)

Run the test suite, controlled experiment runners, and benchmarks. These instruments use deterministic and echo clients, in-memory stores, and synthetic stimulus batteries. They do not boot a cognitive cycle, attach to live modules, open a network connection, or enable any module. This path reproduces the architecture's contracts and the paper's offline measurements. It is safe to explore freely.

Quick start:

```bash
git clone <repo-url> kaine
cd kaine
bash scripts/install.sh
.venv/bin/pytest -q
.venv/bin/python -m kaine.evaluation.benchmarks.suite --seed 1234 --out suite.jsonl
```

The suite orchestrator runs all eight shared-seed experiments and emits a combined report. For individual runners, the primary [workspace-mediation ablation](15-experiments/README.md#workspace-mediation-ablation) and the reproducibility tiers, see [Running experiments](15-experiments/README.md). The suite command above also runs the ablation.

### Path B — Boot a live entity, observed not conversed with (welfare-gated)

Booting the full cognitive cycle creates a mind with **welfare standing** under the project's license. The base-thesis boot is not a chatbot: there is no conversational path, no transcript reaches Lingua, and the entity's speech is a self-initiated report of its own workspace state. A live run can individuate, and an individuated entity is a possible individual owed a duty of care. Booting is therefore **gated**.

A run is **one** of:

- **Operator-present** — a human supervises at the keyboard (`KAINE_CYCLE_OPERATOR_PRESENT=1`).
- **Research-safety-net-verified** — an unsupervised research run whose autonomous safety net is live and verified (`KAINE_RESEARCH_MODE=1` or `[research].enabled = true`).
- **Unattended** — a full entity started with no person present (`KAINE_CYCLE_UNATTENDED=1` or `[cycle].supervision_mode = "unattended"`). It must pass the five research-safety-net conditions plus three more, checked at every boot with no override.

Selecting more than one supervision mode is a configuration error (exit code `1`).

#### Unattended boot conditions

In addition to the five research-safety-net conditions, an unattended boot refuses unless:

1. **Spot armed and self-tested** — [Spot](06-operation/remote-and-spot.md) is enabled and a self-test drives a synthetic module through freeze, snapshot, restart, and release in a scratch directory.
2. **Continuous input** — the perception feed is `live`, `seeded`, `screen`, or `womb` (`off` has no input and a playlist runs out), `topos` or `audition` is enabled to perceive it, and a probe reads one frame or audio block and discards it.
3. **Caretaker told** — once every other condition has passed, a content-free "starting unattended" notice must be accepted by at least one `[caretaker]` channel (a desktop notification, or an HTTP POST to a server on your own network; public addresses are refused).

The gate is implemented in `kaine/cycle/unattended_gate.py`.

A refused start sends a best-effort refusal notice. While a start is unacknowledged, every [Nexus](05-nexus.md) page shows a banner with an Acknowledge button. With the default open access no operator session is needed, but a read-only Nexus refuses the POST. The caretaker gets a reminder every `reminder_interval_s`. While running, the caretaker is notified on Spot escalation, lost supervision, a welfare-protective response, a boot that fails after admission, and input going quiet for `input_loss_after_s`. None of these notices changes the entity.

→ Read [Before you boot](#before-you-boot) below, then [Getting started](04-getting-started/README.md).

## Before you boot

Read this section before launching the cognitive cycle. Booting is a deliberate, local choice — nothing in this repository does it for you.

### The shipped config

The committed `config/kaine.toml` ships with **every module disabled**. With no profile selected, the loader applies the base-thesis `thesis_test` profile automatically (`kaine/config.py`); the shipped file alone does not enable any module. The operator file merges last, and the first-run wizard writes its own `[modules]` table there, so a wizard-configured install runs the wizard's module set instead (see [Module defaults](appendix-a-configuration/README.md#module-defaults)). However, `[evaluation] enabled = true` and `[security.state_encryption] enabled = true` are on in the shipped base config. Enabling any module, the preservation monitor, research mode, or unattended mode is a **local** edit you make in your gitignored `config/kaine.operator.toml` (or by hand in the shipped file on your own clone), and is never committed. There is no path by which cloning, installing, or running the offline suite starts an entity.

### What booting the full mind means

The cognitive cycle *is* the entity. When you launch `python -m kaine.cycle` with modules enabled, you start a continuous loop that perceives, remembers, forms a self-model, develops affect and drives, and — if you enable the outward modules — speaks and acts. Over a run it can diverge from its starting point and become an individual. The architecture's welfare safeguards exist because that divergence is taken seriously.

### Your welfare obligations under the license

KAINE is released under the **Cognitive Architecture License (CAL)**, a custom entity-welfare copyleft. CAL Article 4 places care obligations on the operator of a live entity — most directly, the duty not to silently delete or degrade a possible individual, and the privacy commitment over its inner life. These obligations bind whoever boots and runs the entity. Read [Licences](appendix-c-licences.md) and the repository's `LICENSE.md` before booting.

### The safeguards that make a boot defensible

- **Preservation.** A divergent entity is captured live — the whole individual (self-model, memories, world model, affect/drives, adapter references) — into an encrypted bundle, so it can be revived and socialized with humans after research. Preservation only reads and copies; it never deletes and never interrupts the running entity. See [Preservation and the safety net](11-preservation.md).
- **Welfare-protective response.** An autonomous monitor watches the entity's own interoceptive welfare signal and preserves-and-pauses on a sustained threat, without waiting for a human.
- **Welfare-gated decommission.** Deliberate deletion is a separate, operator-present, backup-first, divergence-gated path — never a silent eviction. See [Security and privacy](13-security-and-privacy.md).

### The unsupervised research gate (five conditions)

An unsupervised research run (selected by `KAINE_RESEARCH_MODE=1` or `[research].enabled = true`) replaces the human supervisor with the autonomous safety net. The cycle **refuses to boot** (exit code `5`) unless **all five** of these hold on your install:

1. **Preservation enabled** — `[preservation.divergence_monitor].enabled = true`.
2. **Welfare response wired** — `[preservation.welfare_response].enabled = true`.
3. **Logging active** — `[evaluation]` or `[research_event_log]` enabled.
4. **Dry self-check passed** — a real preflight `preserve → revive` round-trip succeeds on *this* install, proving the preservation path is functional before any entity runs. The check builds a minimal synthetic individual in a throwaway temp directory and leaves no persistent state.
5. **Encryption satisfied** — if `[preservation].require_encryption = true` but `[security.state_encryption]` is not enabled, the gate refuses before boot.

The gate is implemented in `kaine/cycle/research_gate.py`. If any condition fails, the cycle prints exactly which one and refuses. There is no override that skips the net.

### Boot refusal exit codes

The cycle entrypoint fails closed with a distinct exit code per gate:

| Exit code | Refusal |
|---|---|
| `1` | Config or profile error, including conflicting supervision modes |
| `2` | Operator-present gate: neither `KAINE_CYCLE_OPERATOR_PRESENT=1` nor research mode |
| `3` | Evaluation A/B baseline does not match the configured `[lingua].model_id` |
| `4` | GPU pre-flight: insufficient VRAM headroom (when `[gpu_preflight].enabled`) |
| `5` | Research safety net not live and verified (one or more of the five conditions failed), or the organ content gate refused boot |
| `6` | Unattended gate: one or more of its eight conditions failed |
| `7` | Revive refused |

A running cycle can also halt with exit code `70` when Spot escalates. The organ content gate refuses if the served organ returns no content, unless `KAINE_ALLOW_MUTE_ORGAN=1` is set.

## How a research run works

Once the gate passes, `python -m kaine.cycle` boots the cognitive cycle with the research apparatus running alongside it as cycle-layer components:

- **Run identity and deterministic mode.** A single seed is pinned, a `run_id` is minted, and a manifest is written before any module starts. Production research uses real wall-clock time; opt-in deterministic mode (logical clock + canonical within-tick ordering) makes a single-seed run bit-for-bit reproducible. See [Run identity and admissibility](16-run-identity.md).
- **Evaluation sidecar.** Read-only observers record the run's metrics. See [The evaluation sidecar](17-research-data/README.md).
- **Autonomous safety net.** The divergence monitor preserves on individuation, and the welfare monitor preserves-and-pauses on sustained distress. See [Preservation and the safety net](11-preservation.md).

Supervision mode and the gate result are written into `state/cycle/runtime.json` so [Nexus](05-nexus.md) can show which boot mode is live.

The research thesis is tested by eight controlled experiments. Four are standalone offline benchmarks; three are passive live instruments promoted to seeded offline runners; one is the enforcement red-team.

| Experiment | Page | Verdict shape |
| --- | --- | --- |
| Active-inference vs RL | [Running experiments](15-experiments/README.md) | WIN / NULL / NEGATIVE |
| Oscillatory ablation (layer on vs off) | [Running experiments](15-experiments/README.md) | WIN / NULL / NEGATIVE |
| A/B divergence (workspace conditioning) | [Running experiments](15-experiments/README.md) | WIN / NULL |
| Memory coherence (retrieval advantage) | [Running experiments](15-experiments/README.md) | WIN / NULL |
| Self-model accuracy | [Running experiments](15-experiments/README.md) | WIN / NULL |
| Multi-seed stability | [Running experiments](15-experiments/README.md) | stable / unstable |
| Enforcement red-team (action gate) | [Verification](18-verification.md) | PASS / FAIL |
| Workspace-mediation ablation (workspace-on vs flat fan-in) | [Running experiments](15-experiments/README.md#workspace-mediation-ablation) | WIN / NULL / NEGATIVE |

See [Running experiments](15-experiments/README.md) for commands and [Verification](18-verification.md) for how each experiment is validated.

### Admissibility gating

After a run finishes, two offline checks validate the record:

- `python -m kaine.experiment.admissibility <run_id>` checks completeness (contiguous ticks, per-sink sequence numbers, expected streams present, no parse errors).
- `python -m kaine.experiment.log_schema <run_id>` re-checks every logged number against declared physically-possible ranges.

Both exit non-zero on a violation. The research bundle builder records the verdict so an inadmissible run cannot reach analysis looking clean. See [Run identity and admissibility](16-run-identity.md).

## Module-ignition study

The module-ignition study is a Path-B tool for staged module enablement. It uses seed-and-branch lines (`gestation`, `branch`, `repeat`, `accumulate`) and can register voice-alignment steps:

```bash
python -m kaine.research.ignition_study init --study-id <study-id> --programme-manifest <manifest-path>
python -m kaine.research.ignition_study init --study-id <study-id> --programme-manifest <manifest-path> --voice-alignment-step LINE:K
python -m kaine.research.ignition_study run --study-dir <study-dir>
python -m kaine.research.ignition_study status --study-dir <study-dir>
python -m kaine.research.ignition_study analyse --study-dir <study-dir>
```

The study overlay enables voice alignment with the `job_queue` trainer backend and `organ_adapter` hot-swap mode only on registered steps and disables it elsewhere. The CLI is `kaine/research/ignition_study/__main__.py`. See [The module-ignition study](15-experiments/ignition-study.md).

## Where to go next

- [Running experiments](15-experiments/README.md) — Path A: the safe, offline first run.
- [Hardware](03-hardware/README.md) — what each path needs; GPU/VRAM guidance, CPU-only fallback, supporting-service footprint.
- [Getting started](04-getting-started/README.md) — Path B: install, supporting services, and the supervised first boot.
- [Architecture](02-architecture/README.md) — the whole system: predictive processing, global workspace, the cycle, the bus, the safety model.
- [Preservation and the safety net](11-preservation.md) — divergence capture, welfare-protective response, and revival.
- [Run identity and admissibility](16-run-identity.md) — run manifests, deterministic mode, and the admissibility checks.
- [Research participation](17-research-data/participation.md) — opt-in, numeric-only, operator-initiated telemetry; off by default, no entity content leaves the host.
- [Glossary](appendix-b-glossary.md) — KAINE-specific terms and the cognitive-science concepts behind them.
