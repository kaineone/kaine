# Reproducing Results (offline, no entity)

This is **Path A** from [For Researchers](for-researchers.md): a safe first run
that reproduces the architecture's contracts and the paper's offline measurements
without booting a live entity. Nothing here enables a module, starts the
cognitive cycle, attaches to live modules, opens a network connection, or creates
a mind with welfare standing. You can explore freely.

For a live entity run, see **Path B** —
[Before you boot](for-researchers.md#before-you-boot) and
[Getting Started](getting-started.md).

---

## 1. Clone, install, and create the venv

```bash
git clone <repo-url> kaine
cd kaine
bash scripts/install.sh
```

The installer probes for a GPU, picks the matching PyTorch wheel (CUDA, ROCm,
XPU, MPS, or CPU), creates `.venv/`, and installs KAINE with its test extras.
The offline path needs **no GPU and no supporting services** (no Redis, model
server, Qdrant, Speaches, or Chatterbox) — those are only for a live boot. For the full
install detail and accelerator flags, see
[Getting Started — Installation](getting-started.md#installation).

For a **live research run that drives the playlist perception feed**, also install
the perception extras so both sense surfaces can decode media — OpenCV for the
playlist video track and **PyAV (`av`)** for the playlist audio track:

```bash
bash scripts/install.sh --research   # base install + .[perception] (audio+vision incl. PyAV)
# or, into an existing venv:
.venv/bin/pip install -e .[perception]
```

The default install stays lean (no cv2/av/funasr). Without the perception extras,
`seeded`-mode feeds still run (pure-numpy synthesis, no decode dependency), but a
`playlist`-mode audio source fails honestly with an install hint rather than
producing silence. The first-run wizard also implies these extras automatically
when `[perception_feed].mode` is `playlist` or `live`.

Use `.venv/bin/...` for everything below so you run inside the project venv.

---

## 2. Run the test suite

```bash
.venv/bin/pytest -q
```

The suite is the architecture's executable contract. Passing demonstrates that
the module I/O contracts, the bus event schemas, the workspace selection logic,
the safety gates, the boundary constraints (e.g. `kaine.evaluation` never imports
`kaine.modules.*`), and the welfare/preservation machinery all behave as
specified — without any of it being live.

Two registered markers narrow the run:

```bash
.venv/bin/pytest -m systems -q       # per-subsystem I/O contract tests
.venv/bin/pytest -m integration -q   # hits a live authenticated Redis;
                                     # skipped unless KAINE_REDIS_PASSWORD is set
```

The default `.venv/bin/pytest -q` run does not require Redis: the
`integration`-marked tests skip themselves when `KAINE_REDIS_PASSWORD` is unset.
See [Testing Framework](processes/testing-framework.md) for the three validation
layers (instrument controls, experiment determinism/isolation, data integrity)
and how they map to the seven experiments.

---

## 3. Reproduce the paper's measurements (offline runners)

Each runner below is **headless and synthetic**: it drives only deterministic /
echo clients, in-memory stores, and fixed stimulus batteries, and calls
`set_global_seed(seed)` at the start of a run so the same seed reproduces both the
verdict and the metrics. **None of them boots an entity, enables a module,
attaches to the live bus, or opens a network connection.** A verdict is **WIN**,
**NULL**, or **NEGATIVE**, and a NULL/NEGATIVE/unstable result is a first-class,
reportable finding — never a harness failure.

### Controlled instrument runners

Promote the three passive measuring instruments to seeded offline experiments:

```bash
.venv/bin/python -m kaine.evaluation.benchmarks.instrument_runners ab_divergence    --seed 1234 --out ab.jsonl
.venv/bin/python -m kaine.evaluation.benchmarks.instrument_runners memory_coherence --seed 1234 --out mem.jsonl
.venv/bin/python -m kaine.evaluation.benchmarks.instrument_runners self_model       --seed 1234 --out sm.jsonl
```

- **`ab_divergence`** — the A/B divergence meter's *dynamic range*: empty
  conditioning makes both arms byte-identical (divergence ≈ 0), heavy
  conditioning makes them differ, through the production `divergence_control`
  seam with an echo client.
- **`memory_coherence`** — the memory *retrieval advantage*: a full-system arm
  over a real in-memory Mnemos beats a bare (no-memory) arm on planted facts, the
  advantage vanishes against an emptied store, and a never-stored fact yields an
  honest non-recall sentinel.
- **`self_model`** — whether the Eidolon scorer reproduces the expected score on
  a battery of known `(signal, claim, expected-score)` cases. This validates the
  scorer's **fixed-threshold heuristic** arithmetic — the trait thresholds are
  hand-chosen, **not** fitted, so a WIN means "the heuristic behaves as
  specified," explicitly **not** "the scorer is calibrated" and **not**
  predicted-vs-actual self-knowledge. (The scorer also distinguishes "no scorable
  claim" — reported as no evidence — from a wrong claim scored 0.)

See [Controlled Experiment Runners](processes/controlled-experiment-runners.md).

### Oscillatory ablation (coherence layer on vs off)

```bash
.venv/bin/python -m kaine.evaluation.benchmarks.oscillatory_ablation \
    --seed 1234 --ticks 16 \
    --coherence-floor 0.05 --coherence-ceiling 8.0 --plv-window 12 \
    --out oscillatory_ablation.jsonl
```

Runs the cognitive cycle engine twice over a scripted in-memory bus under
`deterministic=True`, toggling **only** the coherence layer, and measures whether
precision modulation changes global-workspace selection. The disabled arm is
asserted bit-for-bit identical to an independently-built layer-absent cycle, so
any difference is attributable to the layer alone.

The verdict is **WIN / NULL / NEGATIVE** and all three are reachable through the
real measurement pipeline — this is a two-sided falsification test, not a wiring
check. A non-zero `--min-effect` (default 0.10) means a layer that barely nudges
selection resolves to **NULL** ("no meaningful effect — removal justified"); a
meaningful re-ranking *away* from the coherent coalition resolves to **NEGATIVE**
(adverse to the hypothesis). Select the battery with `--stimulus`:

- `engineered` (default) — the positive control: the coherent coalition is handed
  lower raw salience so the layer must re-rank to have an effect (**WIN**).
- `neutral` — the non-engineered battery with no coherence contrast (all sources
  equally phase-coherent); an honest layer does essentially nothing (**NULL**),
  proving the runner is not rigged to always WIN.
- `mislabeled` — the adversarial battery: the `coherent=True` ground-truth label
  is put on a high-salience source that is NOT the most phase-locked, while the
  truly-synchronized source is labeled `coherent=False`. The honest layer promotes
  the truly-synchronized source, so relative to the labels it re-ranks *away* from
  the "coherent" source (**NEGATIVE**).

**Honest structural note:** the coherence layer is strictly monotone in PLV
(`floor <= ceiling`), so with a *correctly-labeled* coherent coalition it can only
push more-phase-locked sources up — a correctly-labeled battery can only ever
return WIN or NULL. NEGATIVE specifically probes a **label/reality mismatch** (the
layer tracking a coherence the ground-truth label disagrees with, i.e. a
mis-specified coalition) — which is exactly the "the layer is tracking the wrong
thing" failure the falsification test must be able to report. See
[Oscillatory Ablation](processes/oscillatory-ablation.md).

### Active-inference benchmark (Nous AIF vs RL baseline)

```bash
.venv/bin/python -m kaine.evaluation.benchmarks.active_inference
```

Compares Nous's live pymdp active-inference engine against a tuned tabular
Q-learning baseline, matched on observation model and reward, over bounded
discrete POMDP tasks (including a `tmaze_epistemic` task where information value
should help and an `exploitation` guard task where it should not). Useful flags:
`--seeds N`, `--tasks tmaze_epistemic exploitation`, `--rl-train-episodes N`,
`--eval-episodes N`, `--out PATH`. See
[Active-Inference Benchmark](processes/active-inference-benchmark.md).

### All seven at once: the shared-seed suite orchestrator

One entry point runs all seven experiments from a **single seed** and emits a
combined report — the "seven experiments, one shared seed" the paper frames:

```bash
.venv/bin/python -m kaine.evaluation.benchmarks.suite --seed 1234 --out suite.jsonl
# add --fast for a quick reduced run (tiny active-inference benchmark)
```

From the master seed it derives an independent, reproducible child seed per
experiment via `numpy.random.SeedSequence.spawn`, and threads that seed into every
experiment — **including the active-inference benchmark**, whose env/RL rng is
derived from the master seed (`BenchmarkConfig.master_seed`) rather than an
independent `default_rng`. The combined report carries each experiment's raw
verdict **and** a **Holm–Bonferroni** family-wise correction (FWER control) across
the p-value-producing experiments (the active-inference Mann–Whitney per task, and
an individuation permutation test when folded in): it reports raw p, Holm-corrected
p, and the reject/no-reject decision under the stated `--alpha`. The offline
deterministic path also opts into GPU/cuDNN determinism
(`set_global_seed(seed, deterministic=True)`) so any seeded CUDA op is reproducible
(a perf cost the live cycle does not pay).

### Multi-seed stability (the longitudinal control's machinery)

The multi-seed stability harness (`kaine/experiment/stability.py`) runs the same
configuration under several seeds and asserts the summary statistics are stable
and the verdict does not flip — the control for genuinely nondeterministic live
longitudinal experiments. As exercised offline it runs the deterministic
oscillatory-ablation runner across seeds:

```python
from kaine.evaluation.benchmarks.oscillatory_ablation.stability import (
    run_ablation_stability,
)

report = run_ablation_stability([1234, 2025, 7], ticks=16, tolerance=0.01)
print(report.stable, report.verdict_counts, report.cv)
```

See [Multi-Seed Stability](processes/longitudinal-stability.md).

### Post-run admissibility checks (read-only)

These two tools validate the *record* of a finished run; they never run from the
cognitive cycle and never boot anything. They operate on already-written JSONL
records under an evaluation root (e.g. logs produced by a prior run, or by the
runners above), keyed by `run_id`:

```bash
.venv/bin/python -m kaine.experiment.admissibility <run_id> [--root DIR] [--expected-stream NAME ...] [--json]
.venv/bin/python -m kaine.experiment.log_schema   <run_id> [--root DIR] [--json]
```

`admissibility` gates completeness (contiguous ticks and per-sink `seq`, all
expected streams present, no parse errors); `log_schema` re-checks every logged
number against declared physically-possible ranges, fail-closed. Both exit
non-zero on a violation. See [Run Admissibility](processes/run-admissibility.md).

---

## Reproducibility tiers (what "reproducible" means here)

Reproducibility is not one guarantee — it comes in three tiers, and the paper's
claims are scoped to the right one:

- **Offline experiment runners** (the seven above): **metric-reproducible from the
  seed.** They drive deterministic / echo clients, in-memory stores, and fixed
  batteries; the same seed reproduces both the verdict and the metrics. Adding the
  opt-in cuDNN/deterministic flags to `set_global_seed` closes the GPU gap for any
  torch op they touch.
- **Deterministic-mode cycle** (`deterministic=true`): **exact** — the trajectory
  is a *pure function of the scripted input* (and the logical clock), not a
  function of the seed. The seed is pinned for hygiene, but the rule-based
  Syneidesis/Volition path samples nothing from it (see
  `tests/test_deterministic_cycle.py`).
- **Live cycle** (`deterministic=false`, real UTC, a temperature-0.7 LLM):
  **NOT** bit- or metric-reproducible from a seed. The organ's server-side
  sampling is outside the seed's reach and wall-clock enters timing. Its
  reproducibility story is **distributional**: characterise it with the multi-seed
  stability harness (stable summary statistics + a verdict that does not flip
  across seeds), not point reproduction. The organ is deliberately **not** pinned
  to temperature 0 for these runs — that would change the entity's behaviour and
  measure something other than the real mind.

## What you can — and cannot — conclude from the offline path

The offline path reproduces the architecture's **contracts** (the test suite),
the meters' **controls and dynamic range** (the instrument runners), the
**ablations** (oscillatory on-vs-off), and the **benchmark** comparison (Nous AIF
vs RL) — all under seeded determinism so a result is a function of the experiment,
not of the random universe it landed in.

It does **not** reproduce a live mind's behavior. The runners use echo /
deterministic clients and synthetic stimulus batteries, not a live language organ
or live perception; they prove the *mechanisms* are wired and measurable under
controlled conditions, and quantify their effect *there*. Claims about a booted
entity's emergent behavior, its individuation over a run, or live longitudinal
dynamics belong to **Path B** ([Getting Started](getting-started.md)) and its
welfare obligations ([Before you boot](for-researchers.md#before-you-boot)).
