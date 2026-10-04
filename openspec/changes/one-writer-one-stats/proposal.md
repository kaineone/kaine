# One set of summary statistics and one embedder fallback

## Why

The complexity audit of 2026-10-03 (W12) found two kinds of duplication in the research instruments.

- **Summary statistics.** Three modules each defined their own mean, standard deviation or percentile:
  - `kaine.experiment.stability` (`_mean`, `_std`);
  - `kaine.research.ignition_study.analysis` (`_percentile`, `_mean`);
  - `kaine.evaluation.observers.prediction_error_observer` (`_percentile`).

  The copies agree today. A fix to one would not reach the others, and the instruments would quietly report different numbers for the same data.
- **Embedder fallback.** `SidecarRegistry` held the fail-closed refusal and the logged `HashEmbedder` fallback twice, in `_resolve_embedder` and `_embedder_default`.

The audit also asked whether the hand-rolled JSONL writers should share one writer. They should not, and this change records why (see Out of scope).

## What changes

- A new stdlib-only module, `kaine/experiment/stats.py`, holds `mean`, `std` and `percentile`:
  - `std` is the population standard deviation;
  - `percentile` uses linear interpolation;
  - each returns 0.0 on empty input, and `std` returns 0.0 for fewer than two values.

  `kaine.experiment` is boundary-neutral, so core, evaluation and research code can all import it.
- The three modules import these helpers instead of defining their own.
- `SidecarRegistry._embedder_fallback()` holds the refusal and the fallback once, and both embedder paths call it. The error message, the log level and the lexical-similarity warning stay the same.

## Out of scope: one JSONL writer

The plaintext JSONL writers (benchmark results, the red-team report and study `steps.jsonl`) stay as they are, and are not routed through `AsyncJsonlSink`.

- That sink encrypts each line when state encryption is on. These files are operator and research records, not the being's data, and their readers (the CLI summaries, `load_run_records` and the study analysis) expect plaintext.
- The sink is asynchronous, drops the oldest records under backpressure and deletes old files under retention. These writers are synchronous, one-shot and must never lose a line.
- Each writer is a few lines over `json.dumps`. Sharing one would add coupling without removing a real hazard.

## Impact

- **Behaviour:** none. Every statistic keeps its definition. The one numeric difference is in the ignition-study mean, which used `statistics.mean`; `sum / len` can differ from it in the last bit of a float.
- **Research:** no study is running, and no recorded result depends on the last bit of that mean.
