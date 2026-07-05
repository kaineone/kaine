# Experiment run identity, seeding, and manifest

## Why

The research logs the system now produces (research event log, trajectory/observer
sidecars, the Spot incident log) are keyed only by timestamp and written to
daily-rotated files. There is no per-run identity: `cycle.tick`'s `tick_index`
resets to 0 every process start, two runs on the same day interleave in one file,
and nothing records *which seed*, *which code*, or *which models* produced a given
dataset. Without that, a result is not reproducible or admissible: an analyst
cannot group one run, detect missing pieces, or attribute a number to a
configuration.

This is the foundation the rest of the research-testing work (completeness gating,
deterministic ablation, freeze annotation) builds on. It does three things:

1. A single **global seed** entry point so a run's randomness is pinned by one
   integer (numpy / random / torch).
2. A per-process **run/session id** minted at startup and stamped on every durable
   record, plus a **run manifest** capturing the seed, git commit, model ids, and
   config digest.
3. A shared **verdict vocabulary** so every experiment reports outcomes the same
   way (the AIF benchmark uses WIN/NULL/NEGATIVE; the red-team uses PASS/FAIL +
   POSITIVE/NEGATIVE — these should derive from one schema).

## What Changes

- New boundary-neutral package `kaine/experiment/` (importable by both the cycle
  and the evaluation sidecar without crossing the sidecar boundary, like
  `kaine/persistence/`):
  - `seeding.py` — `set_global_seed(seed)` seeds `random`, `numpy`, and `torch`
    (torch best-effort/optional); returns the seed used.
  - `run_context.py` — `RunContext` (run_id, seed, started_at, git_sha,
    model_ids, config_digest, kaine_version) + process-global
    `set_run_context()` / `get_run_context()` (mirrors `get_state_encryptor()`).
  - `manifest.py` — write the manifest to `data/evaluation/runs/<run_id>/manifest.json`.
  - `verdict.py` — a `Verdict` schema (WIN / NULL / NEGATIVE for comparative
    experiments; PASS / FAIL for safety gates) with a stable serialization.
- `AsyncJsonlSink` stamps `run_id` and a per-sink monotonic `seq` into every
  record when a run context is set (one central place → covers research log,
  trajectory/observer sinks, raw archive, and the incident log). Records written
  with no run context (pure unit tests) are unchanged.
- The cycle entrypoint (`kaine/cycle/__main__.py`) mints the run context at boot:
  reads `[experiment].seed` (or a fresh seed), calls `set_global_seed`, builds the
  `RunContext` (git sha via best-effort `git rev-parse`, model ids from config),
  sets it process-global, and writes the manifest.
- `config/kaine.toml`: new `[experiment]` block — `seed` (optional; blank → a
  fresh per-boot seed is generated and recorded), `write_manifest` (default true).
- `kaine/research/submission.py`: add `runs` to `METRICS_ONLY_DIRS` so manifests
  are export-eligible (they contain only ids/seed/sha/model-ids/config-digest —
  no entity content; the git sha and model ids are not operator-identifying).
- The AIF benchmark and red-team reports adopt the shared `Verdict` schema for
  their emitted verdict field (additive — existing fields preserved).

## Impact

- Affected: new `kaine/experiment/` package; `kaine/persistence/jsonl_sink.py`
  (record stamping); `kaine/cycle/__main__.py` (boot wiring); `config/kaine.toml`;
  `kaine/research/submission.py`; light touch on the two experiment reports.
- Ships safe: with no `[experiment].seed` set, a fresh seed is generated and
  recorded (reproducible after the fact via the manifest). No module enables; the
  all-off first-boot posture is unchanged. Run stamping is inert when no run
  context is set (so the 1900+ unit tests are unaffected).
- Enables the follow-on changes: `deterministic-cycle-mode`,
  `run-completeness-gating`, `freeze-run-annotation`.
