# Run identity and admissibility

A cycle run needs a stable identity before its data can be trusted. This page explains how KAINE seeds randomness, mints a run id, stamps every record and writes a manifest, and then how offline admissibility checks establish that the record is complete and its numbers physically plausible. Operators and researchers who export or compare runs need this.

## Global seed

`kaine.experiment.set_global_seed(seed, *, deterministic=False)` pins the legacy `random` and numpy global RNGs and, best-effort, the torch RNG (CUDA included). It never fails when torch is absent or CPU-only, and returns the seed used. With `deterministic=True` it also sets torch's GPU and cuDNN determinism flags; the live cycle calls it without that flag (`[experiment].deterministic` does not pass it), and only the offline suite orchestrator sets it. Per-experiment code still uses `np.random.default_rng(seed)` for local streams; the global seed pins the legacy globals and torch so the cycle path is not silently nondeterministic.

## Run context

[`RunContext`](../kaine/experiment/run_context.py) is an immutable record minted once at boot and held process-globally, mirroring [`kaine.security.crypto.get_state_encryptor`](../kaine/security/crypto.py). Modules and sinks read it through `get_run_context()`, which returns `None` when no run has started (the library and unit-test default). It carries:

- `run_id`: a fresh uuid4 hex, unique per process start.
- `seed`: the integer pinned by `set_global_seed`.
- `started_at`: an ISO-8601 UTC timestamp.
- `git_sha`: a best-effort short git revision. Resolution never raises. When git is unavailable it falls back to the `KAINE_GIT_SHA` environment variable baked into container images at build time (`ARG GIT_SHA` sets `ENV KAINE_GIT_SHA`), so containerized manifests carry provenance without a `.git` directory.
- `model_ids`: the configured model ids from the documented model keys only (`lingua`, `evaluation_chat`, `topos_encoder`, `embedding_backend`, `embedding_model_id`, `audition_stt` and `audition_emotion`), plus `lingua_revision`, the organ repository's commit sha, when the downloader recorded one. Hostnames, paths and voice names are never included.
- `config_digest`: the `sha256` of the resolved config, truncated, so two runs can be compared for "same config" without storing the config itself.
- `kaine_version`.
- `perception_feed`: the reproducible perception-feed descriptor, a small dict shaped `{"mode": "off"|"live"|"seeded"|"playlist"|"womb"|"screen", "regime": ..., ...}` (mode `live` has regime `"camera"`). For `seeded` it carries the seed and schedule parameters, enough to regenerate the stream. For `playlist` it carries the manifest sha256, per-item digests and the transition settings, enough to verify the stimulus without holding its content. `womb` carries the gestational stimulus parameters and the awake-time offset, and `screen` its capture parameters. Mode `off` produces `{"mode": "off"}`. An empty dict means the descriptor was unavailable and carries no feed signature. The caller gathers this at the cycle/boot layer and passes it in as data, keeping `kaine.experiment` boundary-neutral.
- `plugins`: identifiers of loaded plugins, if any.
- `timing`: the timing parameters used by the run.
- `revived_from`: when the run was revived from a preservation, the preservation id, or the bundle name if the id is not set.

## Record stamping

When a run context is set, every record written through `AsyncJsonlSink` carries the run's `run_id` and a per-sink monotonic `seq` starting from 0. One central edit covers the research event log, every sidecar observer, the raw archive and the Spot incident log. Stamping uses a shallow copy, so the caller's dict is never mutated. When no run context is set (the unit-test and library default), records are written unchanged, with neither `run_id` nor `seq` added.

The per-sink `seq` lets completeness gating detect a silent drop within any single stream, complementing tick-index gaps across the cycle.

## Run discovery

`kaine.experiment.run_records.discover_run_ids(root)` enumerates the distinct `run_id` values present in the eval logs under `root`. It scans every `*.jsonl` sink file (the same tree `load_run_records` reads, skipping the `runs/` manifest directory), decrypts and parses each line, and collects every non-empty `run_id`. It returns a `RunDiscovery` with `run_ids` (the sorted set found) and `unreadable_lines` (a count of lines, and whole files on `OSError`, that could not be decrypted or parsed). A non-zero `unreadable_lines` is itself a signal, usually of a wrong or absent state encryption key, so callers fail closed instead of mistaking unreadable logs for an absence of run data. Discovery lets the research bundle builder gate admissibility without the operator knowing or passing a run id, because the runs are found in the tree the bundle is built from.

## Manifest

When `[experiment].write_manifest` is true (the default), the cycle writes the run context once at boot to `data/evaluation/runs/<run_id>/manifest.json` with an atomic write. The `runs` directory is in the metrics-export allowlist (`METRICS_ONLY_DIRS`): the manifest holds only the run id, seed, git sha, model ids, config digest, start time, version, perception feed, plugins, timing and revival source, with no entity interior and no operator-identifying data, so it is export-eligible.

## Deterministic mode

`[experiment].deterministic` (default `false`) is an opt-in mode that makes a cycle run bit-for-bit reproducible: two runs with the same seed and the same input sequence produce an identical cognitive trajectory. The oscillatory ablation depends on it: the cycle runs with the coherence layer on and off from the same seed and the same input, so any difference in behaviour comes from the layer alone. See [Running experiments](15-experiments/README.md) for the experiment runners.

Beyond the global seed, deterministic mode closes two residual sources of run-to-run variation:

- Logical event clock. The engine stamps every event it publishes from a single seam, `CognitiveCycle._now()`. In normal mode this is the injectable `wall_clock` (real UTC by default). In deterministic mode it is a logical clock: tick *k*'s events are stamped `BASE_EPOCH + k * target_tick_period`, where `BASE_EPOCH` is the fixed constant `1970-01-01T00:00:00Z` and the target tick period is the inverse of the processing rate. Logical timestamps are identical across runs. The logical clock is distinct from the engine's monotonic `clock`, which still measures real elapsed time for slip/latency.
- Canonical within-tick event ordering. Before scoring and selection, each tick's gathered events are sorted by a total deterministic key `(source, type, entry_id)`. This pins the selection tie-break input so it does not depend on async-gather or stream-declaration incidentals. The ordering is applied unconditionally: production and deterministic runs share one ordering rule, so the ablation comparison isolates the layer alone. Because the selection score sort is stable and the common case is already ordered, this is a no-op for normal runs.

What is guaranteed: tick by tick, the same coalitions (entry ids, sources, types, scores), the same inhibition decisions, the same volition outputs, and the same logical event timestamps.

What is not guaranteed: wall-clock latency. `wall_duration_ms` and `slip_ms` are physical measurements of the host, inherently variable, and excluded from the reproducibility guarantee. They are still recorded, and two runs are not required to match on them.

Deterministic mode is off by default: production runs use real wall-clock time. The seed is recorded in the manifest as usual, so a deterministic run stays reproducible after the fact.

## Admissibility checks

After a run finishes, two offline checks decide whether its data is trustworthy for analysis. Completeness gating checks that the run's record is whole, and log validation checks that its numbers are physically plausible. Both checks are read-only and never run from the cognitive cycle. They are operator and analysis tools and a hook in the research bundle builder. See [The evaluation sidecar](17-research-data/README.md) for how sidecar observers consume them.

### Shared record loader

`kaine.experiment.run_records.load_run_records(run_id, *, root)` walks every JSONL sink file under the evaluation root, decrypts each line (`get_state_encryptor().decrypt_text`, which transparently passes plaintext through when encryption is off), parses the JSON, keeps the records carrying the target `run_id`, and groups them by source stream (the sink file's `<name>` prefix). A line that cannot be decrypted or parsed is counted as a parse error, never raised: a corrupt record is itself a signal. The `runs/` manifest directory is skipped (it holds `manifest.json`, not record streams).

The loader imports only the standard library and `kaine.security.crypto`. It never imports the evaluation package: callers that need the set of expected streams supply it as data.

### Completeness gating

`kaine.experiment.admissibility.scan_run(run_id, *, root, expected_streams)` returns an `AdmissibilityReport`. A run is admissible only when all four hold:

- Contiguous cycle ticks. `cycle.tick`'s `tick_index` runs `0, 1, 2, …`. A gap (`tick_gaps`) means ticks went missing.
- Contiguous per-sink `seq`. Each stream's `seq` is contiguous. A gap (`seq_gaps`, per stream) means records were silently dropped, which timestamps alone cannot show (`AsyncJsonlSink` sheds its oldest entry under backpressure).
- All expected streams present. Any stream in `expected_streams` that produced zero records this run is listed in `missing_streams` (a silent observer failure).
- No parse errors. Any unparseable line is counted in `parse_errors`.

`report.reasons()` summarizes why a run failed. The CLI

```
python -m kaine.experiment.admissibility <run_id> [--root DIR] [--expected-stream NAME ...] [--json]
```

prints the report and exits non-zero when the run is inadmissible.

### Restart and multi-process detection

A finished run's completeness scan also treats a restart or overlapping process as inadmissible, via two signals on `AdmissibilityReport`:

- `restart_seq_resets`: maps a stream name to the `seq` values observed after a backward jump in that stream's raw `seq` sequence. A per-sink `seq` is a single process's monotonic counter; a later value that drops back below the running maximum (typically to 0) means a fresh `AsyncJsonlSink` instance started stamping again: the process restarted mid-run without minting a new `run_id`. This is invisible to the contiguity check, which treats `seq` as a set and tolerates duplicates.
- `related_run_ids`: additional `run_id`s the operator (or the bundle builder, via auto-discovery) declares as a continuation of the same logical run, e.g. a crash/resume where the resumed process minted a fresh `run_id` (a fresh `RunContext` never reuses one). `scan_run(run_id, ..., related_run_ids=...)` merges their records into the scan by stream; declaring any related run id is itself a restart/multi-process signal, so a non-empty `related_run_ids` always makes the run inadmissible.

The `python -m kaine.experiment.admissibility <run_id>` CLI exposes this as a repeatable `--related-run-id RUN_ID` flag for standalone completeness scans.

### Log range validation

`kaine.experiment.log_schema.sweep_run(run_id, *, root)` re-checks the run's logged numbers against a declared schema of physically-possible ranges and returns a list of `Violation`s (`stream`, `field`, `value`, `bound`, `event_type`, `seq`). It is fail-closed: any out-of-range value is a violation; an empty list means every declared field is within range. The CLI

```
python -m kaine.experiment.log_schema <run_id> [--root DIR] [--json]
```

prints violations and exits non-zero if any exist.

The ranges are taken from the producing modules and the research event taxonomy. Where a field has no well-defined hard upper bound it uses a generic `>= 0` (`NONNEG`); where a field has no defined bound at all it is omitted instead of guessed, so the schema has no rule for it.

### Declared ranges

| Field | Range | Source |
| --- | --- | --- |
| `salience` | `[0, 1]` | bus schema |
| `prediction_error` | `[0, ∞)` | clamped `max(0.0, e)` at the soma producer |
| coherence PLV (per pair) | `[0, 1]` | phase-locking value |
| `valence` | `[-1, 1]` | thymos affect state |
| `arousal` | `[0, 1]` | thymos affect state |
| `dominance` | `[-1, 1]` | thymos affect state |
| `confidence` (nous) | `[0, 1]` | `1 - normalised_entropy`, clamped |
| drive `value` | `[0, 1]` | thymos drives |
| `familiarity_scalar` | `[0, 1]` | empatheia |
| `wellness` | `[0, 1]` | soma report |
| `fatigue_value` | `[0, ∞)` | soma report |
| `error_magnitude`, `phantasia.world_error.error` | `[0, ∞)` | non-negative magnitudes |
| `unexpected_error` | `[0, ∞)` | non-negative magnitude |
| `cycle.tick` `access_drive` | `[0, 1]` | cycle access drive |
| `cycle.tick` `experiential_rate_hz` | `[0, ∞)` | cycle timing |
| `cycle.tick` `processing_rate_hz` | `[0, ∞)` | cycle timing |
| `nous.proposal` `preference` | `[0, 1]` | nous proposal |
| `audition.emotion` `confidence` | `[0, 1]` | audition emotion |

Omitted as undefined: `expected_free_energy` (a signed scalar with no documented range), and latency / elapsed / duration / count fields beyond the generic non-negative case.

### Bundle integration

`kaine.research.submission.build_research_bundle` runs both the completeness gate (`scan_run`) and the log-range sweep (`sweep_run`) over the run(s) present in `eval_root` and records both verdicts in the bundle manifest, so an inadmissible run cannot reach analysis looking clean.

`require_admissible` defaults to `True`: a run that fails either check is blocked from export (`AdmissibilityError` is raised and no partial bundle is left behind). Passing `require_admissible=False` turns the gate into a non-blocking annotation.

The runs to gate are discovered automatically: `discover_run_ids` scans every `*.jsonl` sink file under the whole `eval_root` tree and gates every distinct `run_id` it finds there, so the guarantee holds at the real operator entry point (`python -m kaine.research`) even when no run id is passed. `admissibility_run_id` is optional and only narrows the gate to one pinned run without replacing discovery: any other `run_id` still found under `eval_root` and not explicitly acknowledged via `admissibility_related_run_ids` is folded in as a restart/multi-process signal, and a pin that matches zero discovered records is itself inadmissible.

### Override escape hatch

There is one explicit, operator-only way to export a run that failed admissibility: pass `admissibility_override=True` and a non-empty `admissibility_override_reason`. Both are required together: a bare `admissibility_override=True` with an empty or blank reason raises `AdmissibilityOverrideError` before anything is built, so the override cannot fire by accident. When used correctly, the manifest records an `admissibility_override` block (`overridden: true` plus the reason) so an overridden export can never be mistaken for a clean one. The `python -m kaine.research` CLI surfaces this as `--admissibility-override-reason "<why>"`.

### Range admissibility in the manifest

Alongside the `admissibility` block, the bundle manifest carries a `range_admissibility` block: the log-range sweep (`sweep_run`) run over every `run_id` in the logical run (the primary run plus any `related_run_ids`), giving `admissible` (bool) and the list of `violations` found across all of them. An out-of-range value in a restarted or related run therefore blocks the export even when the primary run's own numbers are clean.

## Configuration

```toml
[experiment]
# A fixed integer makes a run reproducible. Leave blank to generate a fresh seed
# each boot; the manifest always records whatever seed was used.
seed = ""
# Write data/evaluation/runs/<run_id>/manifest.json at boot.
write_manifest = true
# Opt-in deterministic mode: logical event clock + canonical within-tick event
# ordering so a run is reproducible bit for bit (same seed and input give the
# same trajectory). Off in production; used by the oscillatory-ablation runner. Does
# NOT make wall-clock latency reproducible.
deterministic = false
```

See [Lifecycle, evaluation and research configuration](appendix-a-configuration/lifecycle-and-research.md) for the full `[experiment]` reference.

## Shared verdict schema

`kaine.experiment.verdict` provides one outcome vocabulary every experiment reports through: `Outcome` (WIN, NULL and NEGATIVE for comparative experiments, PASS and FAIL for enforcement gates) and a frozen `Verdict` (outcome, detail, metrics) with a stable `to_dict()`. The active-inference benchmark and the enforcement red-team each include a `verdict` object using this schema alongside their existing fields, so downstream tooling has one shape to read. See [Running experiments](15-experiments/README.md) and [Verification](18-verification.md).
