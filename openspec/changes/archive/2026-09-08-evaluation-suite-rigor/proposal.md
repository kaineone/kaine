# Close the evaluation suite's rigor gaps against the paper's claims

## Why

The research-viability review found several places where the paper's evaluation
framing (§6.4) claims more rigor than the code delivers. Each is a place a
reviewer in the field would push on, so each should be closed before the companion
empirical paper.

1. **"Seven experiments, one shared seed" has no orchestrator.** Each experiment is
   an independent CLI with its own default seed, and the active-inference benchmark
   seeds differently (local `np.random.default_rng`, `active_inference/runner.py:95`)
   from the oscillatory/instrument runners (`set_global_seed`). `RunContext.seed`
   exists but never drives the suite. There is no single entry point that runs the
   seven under one seed.
2. **No GPU determinism.** `set_global_seed` (`kaine/experiment/seeding.py:20-38`)
   sets `random`/`numpy`/`torch` seeds but not `torch.use_deterministic_algorithms`,
   `cudnn.deterministic`, or `cudnn.benchmark=False`. Any CUDA op is non-reproducible
   even with the seed pinned.
3. **The determinism test proves a rule-based fake, and the paper's "reproducible
   from its seed" cannot hold for the live LLM-in-the-loop cycle.** The live cycle
   ships `deterministic=false`, stamps real UTC, and runs a temperature-0.7 LLM whose
   server-side sampling the seed cannot pin. The paper should claim metric-level
   reproducibility of the offline experiment runners and deterministic-mode cycle,
   not bit-level reproducibility of the live cycle.
4. **No multiple-comparisons correction** anywhere across seven verdict-producing
   experiments (no bonferroni/holm/FDR in the tree). For a falsifiability-framed
   paper this is a real omission.
5. **The oscillatory ablation cannot return a result adverse to its hypothesis.**
   `_classify` returns only WIN/NULL, `min_effect` defaults to `0.0`, and the
   stimulus is engineered so the enabled arm always re-ranks. It is a wiring test,
   not the falsification test the paper frames.
6. **The individuation test bypasses its own warm-up by default and has no runner.**
   `IndividuationTest` is constructed only in tests; when a caller omits
   `observations`/`lived_time_s` it forces `warmed_up=True`
   (`individuation.py:383-385`), disabling the paper's central safeguard against
   false individuation on a fresh entity.
7. **The self-model scorer is called "calibrated" but uses hardcoded magic-number
   thresholds** (`eidolon_accuracy.py:143-151`) and scores "no scorable claims" as
   0.0.

## What Changes

**Plan-only. Ships no behavior code.** Design-of-record; see `design.md` for the
per-item approach and the honest paper-wording items.

1. Build a **shared-seed suite orchestrator** that runs all seven experiments from
   one `RunContext.seed`, threading the seed uniformly (including into the
   active-inference benchmark), and emits a combined verdict report.
2. Extend `set_global_seed` with **GPU/cuDNN determinism flags** (opt-in for the
   deterministic experiment path; documented perf cost).
3. Add a **multiple-comparisons correction** across the suite's p-value-producing
   experiments and report both raw and corrected verdicts.
4. Make the **oscillatory ablation able to return NEGATIVE/NULL honestly**: add an
   adverse-outcome class, a non-engineered stimulus battery, and a real `min_effect`
   threshold so a "layer changes nothing / changes the wrong way" outcome is
   reachable and reportable, matching the paper's falsification framing.
5. Give the **individuation test a runner** that always supplies real warm-up
   counters, and make the warm-up floor **fail closed** (never silently `warmed_up=
   True` when counters are missing).
6. **Calibrate the self-model scorer** against a small labeled set, or rename the
   claim to "fixed-threshold" in code and paper; stop conflating "no scorable claims"
   with 0.0 accuracy.
7. **Correct the paper's reproducibility wording** (§6.4/§6) to match code reality:
   metric-level reproducibility of offline runners + deterministic-mode cycle, not
   bit-level reproducibility of the live temperature-0.7 cycle.

## Impact

- Affected specs: `experiment-foundation`, `oscillatory-binding` /
  `enforcement-red-team` (ablation), `individuation-boundary`,
  `self-model-scorer-calibration` (archived — revisit), `evaluation-sidecar`.
- Affected code (later pass): `kaine/experiment/seeding.py`, a new suite
  orchestrator under `kaine/experiment/`, the active-inference runner, the
  oscillatory-ablation runner + stimulus, `kaine/experiment/individuation.py` + a new
  runner, `eidolon_accuracy.py`, and the paper mirror + arXiv manuscript.
- Some items (5, warm-up fail-closed) are safety-relevant: they restore a safeguard
  the paper describes as central.
