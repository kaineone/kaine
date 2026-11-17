# Audition salience recompute protocol and command plan — 2026-11-16

Docs-only. This record proposes how to recompute the normalisation, alert
factor, and floor for OpenSpec task 6.7, using the latest bake-off evidence.
It does **not** implement 6.7, tick task boxes, or change config. Task 6.6
remains open.

## Inputs (latest records)

- `docs/records/audition-encoder-bakeoff.json` — 600 × 8000-sample seeded
  synthetic feed, seed 42, cuda:0.
- `docs/records/audition-encoder-bakeoff-1200blocks.json` — 1200-block
  snapshot (stdout capture, not JSON).
- `docs/records/audition-encoder-decision-note-2026-11-16.md` — single-feed
  provisional ordering; AUC ordering swaps between 600- and 1200-block runs.
- `docs/records/audition-feed-variant-readiness-2026-11-16.md` — feed
  loaders not yet usable.
- `docs/records/audition-sensor-feed-checklist-2026-11-16.md` — required
  evidence schema and pending gates.
- `docs/records/audition-salience-recalibration-2026-11-16.md` — proposed 6.7
  procedure that this command plan executes.

Recorded absolute change shoulders (`p95_threshold`), useful only as scale
anchors because the units are encoder-specific:

| encoder | 600-block | 1200-block p95 latency (ms) |
|---|---:|---:|
| spectral | 1.398 | 3.09 |
| wavjepa | 3.119 | 6.24 |
| dasheng | 3.136 | 3.86 |

The operational false-alert metric must be defined explicitly before
recomputation: `non-surprise blocks > factor after normalisation`, not the
internal 95th-percentile-of-negatives artefact used by the bake-off script.

## Before recomputation

Run and record these gates; no recompute begins until all are true.

1. Disk and resource check:

   ```bash
   df -h /var/home/erik /run/media/erik/2TBm2Store
   .venv/bin/python - <<'PY'
   import resource
   print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
   PY
   ```

2. Branch and tree state:

   ```bash
   cd /var/home/erik/Projects/kaineone/kaine
   git status --short
   git rev-parse --abbrev-ref HEAD
   ```

3. Confirm 6.6 prerequisites (currently not complete):
   - seeded, playlist, and stimulus-source feed records exist;
   - stimulus-source label rule (recommended heartbeat-thud onsets) approved;
   - all three records use the common evidence envelope from the sensor-feed
     checklist.

4. Preserve immutable baselines before any rerun:

   ```bash
   cp docs/records/audition-encoder-bakeoff.json \
     docs/records/audition-encoder-bakeoff-600blocks-baseline-$(date -u +%Y%m%dT%H%M%SZ).json
   ```

## Instrumentation blocker

Neither `scripts/bench_audition_encoders.py` nor `scripts/bench_audition_feeds.py`
currently emits the per-block quantities needed for a window fit:

- raw `change`
- forward-model prediction error
- `normalised_change` under each candidate window
- `normalised_error` under each candidate window
- ROC AUC / false-alert / missed-onset values at each candidate factor and
  floor

Therefore the first implementation-level prerequisite is a **read-only analysis
flag** in the bench scripts, not a production code change:

```text
--dump-analysis-json PATH
```

The flag writes a RAM-only JSON containing per-block metrics and no PCM, no
decoded samples, and no embeddings. Zero-persistence invariant remains
unchanged. Until that flag exists, the command plan below is a specification,
not a runnable calibration.

## Recomputation protocol

For each feed, each encoder, and each candidate window, recompute offline:

1. Build the per-block series `change[i]`, `prediction_error[i]`.
2. Compute rolling means for window `w` in `{8, 16, 32, 64}`.
3. Compute:
   - `normalised_change[i] = change[i] / mean(change[max(0,i-w+1):i+1])`
   - `normalised_error[i] = prediction_error[i] / mean(prediction_error[max(0,i-w+1):i+1])`
4. Sweep factor in `{1.5, 1.75, 2.0, 2.25, 2.5, 3.0}`.
5. Evaluate floor option 1 absolute values `{0.10, 0.15, 0.25, 0.35, 0.50}`
   and the per-encoder shoulder from the non-surprise p99.9.
6. Evaluate floor option 2 relative guard only if approved as a scoped
   code change through the normal branch/PR pipeline.
7. Report AUC, achieved false alerts/min at explicit factor thresholds,
   missed-onset rate, cross-encoder parity, and feed parity.
8. Run negative controls: steady-noise injection, relocated onset ablation,
   and gradual habituation stream.

Example rolling computation reference:

```python
def rolling_normalised(values: list[float], window: int) -> list[float]:
    out: list[float] = []
    for i, value in enumerate(values):
        start = max(0, i + 1 - window)
        mean = sum(values[start:i + 1]) / (i + 1 - start + 1e-12)
        out.append(value / (mean + 1e-12))
    return out
```

## Likely ranges

These are provisional ranges from the recorded scale anchors, not fitted
values:

- Normalisation window: likely `16-32` utterance windows on VAD-segmented
  feeds; on continuous-window feeds, document the equivalent seconds before
  changing the integer-count knob.
- Alert factor: likely `2.0-2.5`. A value below 2.0 risks losing the
  current spectral stability; above 2.5 risks missing lower-salience onsets.
- Absolute floor:
  - spectral: likely `0.10-0.25`.
  - dasheng/wavjepa: likely `0.25-0.75`.
- Cross-encoder parity test is expected to fail for a single absolute floor;
  if it does, either select Option 2 (relative guard, requires code change) or
  accept that spectral remains the practical default because its shoulder is
  smallest.

## Command plan

Feed records (after 6.6 gate passes):

```bash
cd /var/home/erik/Projects/kaineone/kaine
.venv/bin/python scripts/bench_audition_feeds.py --blocks 300 --seed 42 --out \
  docs/records/audition-feed-bench-seeded.json
```

Repeat with the playlist and stimulus-source feed families once their loaders
and event-mark rules exist. Each feed must get its own output file; do not
conflate evidence in one JSON.

Baseline 600-block bake-off reproducibility check:

```bash
.venv/bin/python scripts/bench_audition_encoders.py --blocks 600 --device cuda:0
cmp docs/records/audition-encoder-bakeoff.json \
  docs/records/audition-encoder-bakeoff-600blocks-baseline-*.json
```

Candidate-window sensitivity experiment, after analysis flag exists:

```bash
.venv/bin/python scripts/bench_audition_encoders.py \
  --blocks 600 --device cuda:0 \
  --dump-analysis-json /tmp/audition-analysis-600.json
```

Then generate candidate calibration records:

```bash
.venv/bin/python - <<'PY'
import json
src = "/tmp/audition-analysis-600.json"
# Candidate aggregation logic belongs here once the analysis schema is frozen.
# Output: docs/records/audition-salience-calibration-<feed>.json
PY
```

Blockers and unresolved dependencies

1. 6.6 incomplete (only the 2026 seeded synthetic path plus 1200-block snapshot).
2. Playlist loader requires PyAV and a synchronous capture boundary.
3. Stimulus-source label rule (heartbeat thud versus maternal-state/cross-modal
   transition) is not approved.
4. Native 480-sample block versus 8000-sample harness contract remains open.
5. Per-block analysis dump not yet available.
6. GPU lock and peak RSS budgets: wavjepa ~3.1 GB; dasheng ~1.7 GB.
7. FA metric is internally defined, so absolute alert behaviour is not yet
   measured.
8. Single absolute floor is not fair across encoders; Option 2 requires a
   scoped code change and tests.
9. No winner is selected; Tier 0 stays `spectral` regardless of 6.6 outcome.
10. WavJEPA MMN mode (6.9) is still needed before WavJEPA promotion.

## Acceptance before 6.7 closes

- Per-feed calibration records exist for all feed families.
- Each record contains feed metadata required by the readiness note.
- Chosen window, factor, and floor supported by candidate tests A-E in
  `audition-salience-recalibration-2026-11-16.md`.
- No config edited until a separate PR follows the normal pipeline.