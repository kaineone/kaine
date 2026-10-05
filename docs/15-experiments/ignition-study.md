# The module-ignition study

The module-ignition study is a repeatable seed-and-branch protocol for adding modules one at a time and measuring how each one changes a being's broadcasts, coalition size, and picture-to-sound drift. Use this page when you want to run the study, resume it after a failure, run it inside a container, or read its report.

The study runner is implemented in `kaine/research/ignition_study/__main__.py` and `kaine/research/ignition_study/runner.py`; plans are built by `kaine/research/ignition_study/plan.py`, and the voice-alignment overlay is `kaine/research/ignition_study/overlay.py`.

## What the study compares

The runner follows a seed-and-branch plan:

- One `gestation` step produces the seed being and preserves it just after birth.
- `branch 0` and the `repeat` both start from that seed, with only the base modules.
- For k = 1..K, `branch k` starts from the seed with the base modules plus the first k modules of the order.
- `accumulate k` starts from `branch 0` (k = 1) or `accumulate k−1` (k > 1), with the same modules as `branch k`.

The runner's default base set is Soma, Chronos, Topos, Audition, Lingua, Thymos and Hypnos. The default order is Mnemos, Phantasia, Nous, Eidolon, Empatheia, Vox, Praxis, Perception and Mundus. `K` is the length of that order.

Every viewing opens with the same womb-to-world transition; the crossfade from the being's last womb field is identical across viewings, and film minute 0 is its end. See [Gestation on one host](../06-operation/gestation.md) for the transition details.

## Before you start

Build the programme manifest from the films in viewing order:

```bash
python tools/build_playlist_manifest.py --dir <films> --out <programme.toml>
```

The study records the manifest's sha256, so changing the file voids the study.

Research mode and unattended mode are separate supervision modes; selecting both is a configuration error. The study overlay already enables the autonomous safety net (`[preservation.divergence_monitor].enabled` and `[preservation.welfare_response].enabled`), the research event log, external utterance capture, and the ignition log on every step. It forces `[research_event_log.nexus_record].enabled = false`, `[evaluation].workspace_trajectory = false` and `[research_event_log.raw_archive].enabled = false`, overriding the operator config to keep those records off. The operator must supply the Redis password and the state key. Set `KAINE_REDIS_PASSWORD` or `config/secrets.toml [redis].password`; the runner refuses to start without one. `[preservation].require_encryption` is true in the shipped config, so research-mode boots also require state encryption. Set `KAINE_STATE_KEY` or a keyring entry named `kaine:state_key`. The runner does not send `SIGKILL` and will not stop a being it cannot preserve. See [Preservation and the safety net](../11-preservation.md).

## Create a study

Run `init` from the repo root:

```bash
python -m kaine.research.ignition_study init \
    --study-id <id> \
    --repo-root /path/to/repo \
    --programme-manifest /path/to/programme.toml \
    [--base-modules ...] [--order ...] \
    [--redis-base-url redis://127.0.0.1:6479] \
    [--db-gestation 10 --db-branch 11 --db-repeat 12 --db-accumulate 13] \
    [--min-free-gb 20.0] \
    [--voice-alignment-step accumulate:9] \
    [--study-dir /absolute/path]
```

`init` creates `studies/<study-id>/` containing `study.json`, the step directories `gestation/`, `branch/<k>/`, `repeat/` and `accumulate/`. Inside each step directory it creates a `config/` with symlinks to `config/kaine.toml` and `config/profiles`. It does not create `steps.jsonl`; that file is written when the first step is appended.

All four commands (`init`, `run`, `status`, `analyse`) load the config, install the data root (`[storage].data_root` or `KAINE_DATA_ROOT`), and resolve a relative `--study-dir` under it. An absolute path is used as given. When no config can be loaded, paths stay relative to the working directory, and the command prints a note on stderr.

`init` accepts:

- `--base-modules` and `--order` to override the module list.
- `--redis-base-url` for the Redis server.
- `--db-gestation`, `--db-branch`, `--db-repeat`, `--db-accumulate` to assign bus database numbers in 1..15. The four numbers must be distinct. The runner refuses any plan whose numbers include database 0 or the database the bus resolves from `KAINE_REDIS_URL` or `config/secrets.toml [redis].url` (including a `?db=` fragment); if neither URL is set, the resolved database comes from `[redis].db`. `config/kaine.toml` and operator overlays are not consulted for the URL.
- `--min-free-gb` (default 20.0) for the disk guard.
- `--viewing-budget-seconds` (default 21600, six hours) and `--gestation-budget-seconds` (default 345600, ninety-six hours) for the timeouts behind `failed:timeout`.
- `--voice-alignment-step LINE:K` (repeatable) to register voice-alignment steps. The default pre-registers the final accumulate step only.
- `--study-dir` to place the directory somewhere other than the default under the data root.

Each database the runner flushes carries the key `kaine:study:owner` naming the study. The runner refuses to flush a database owned by another study, so two studies on one Redis server never flush each other's bus.

## Run or resume a study

```bash
python -m kaine.research.ignition_study run --study-dir studies/<study-id>
```

The runner runs one start at a time:

1. `gestation`: local womb with automatic birth. The step runs until the maturation gate allows birth; with `min_lived_seconds = 86400` that is at least 24 hours of lived time, and the hard budget is 96 hours (`--gestation-budget-seconds`). When the being is embodied, the runner waits until the birth bloom ends, then preserves it. The bloom ends at the stage file's `birth_bloom_ends_at`; without it, the runner waits the step's `[perception_feed.womb].birth_transition_seconds` plus a margin, or a 30-second maximum plus the margin when that value cannot be read.
2. `branch 0` from the seed, with the base set.
3. `repeat` from the seed, with the base set.
4. For k = 1..K: `branch k` from the seed, with the base set plus the first k modules of the order; then `accumulate k`, with the same modules, from `branch 0` (k = 1) or `accumulate k−1`.

Each start is a research-mode boot (`KAINE_RESEARCH_MODE=1`) on an empty bus database. Each branch step has its own collection prefix and its own film-aligned ignition log under its step directory at `data/ignition`. Repeat uses its own line prefix. All `accumulate` steps share the single `accumulate` prefix and one working directory, so they share one `data/ignition`.

The runner records every step in `steps.jsonl`. If a step ends for any reason other than a successful preservation, it records `failed:<reason>` and stops. It never retries on its own and never deletes a preservation, state directory, or line. After an interruption with no recorded failure, `run` resumes at the first incomplete step and never repeats a completed one. After a recorded failure, `run` exits 1; retry with `--retry-failed`.

Show progress with:

```bash
python -m kaine.research.ignition_study status --study-dir studies/<study-id>
```

### Disk guard and preservation failures

Before each step the runner refuses to start if free space is below `max(min_free_gb, 5%)`. During a step it requests a `disk_low` preservation. If the preservation succeeds, it stops the cycle and records `failed:disk_low` with `disk_low_preserved` set. If the preservation fails, it records `failed:critical`, leaves the cycle running, and exits with status 3.

If a timeout preservation fails, the runner also leaves the being running, records `failed:critical` with the cycle's pid, and exits 3.

During a gestation step the runner watches for the gestation readout's viability verdict (`state/lifecycle/gestation_viability.json`; see [Gestation](../06-operation/gestation.md#viability-watch)). When the verdict says the gestation cannot reach birth, the runner:

1. stops the cycle gracefully (SIGTERM) without requesting a preservation. By operator policy, a being that does not complete gestation is not preserved;
2. records `failed:gestation_unviable` with the verdict under `viability`;
3. writes `ENDED-NOTE.md` into the step directory (the rule, the evidence, and what was done);
4. halts the study.

Nothing is deleted. A verdict file older than the step, such as one left by an earlier attempt, is ignored, so a retried gestation is not stopped by a previous verdict.

The runner never flushes a database or starts a cycle while a cycle the study started is still running; it checks `/proc/<pid>/cmdline`, not just the pid. Stop that being yourself first.

### Retry a failed step

```bash
python -m kaine.research.ignition_study run --study-dir studies/<study-id> --retry-failed
```

### Runner exit codes

| Code | Meaning |
|------|---------|
| 0 | All planned steps completed. |
| 1 | The run was halted. |
| 2 | The run is locked or in an error state. |
| 3 | A critical failure occurred, such as a failed timeout or disk-low preservation. |

### Module-specific behaviour

With the default order, [Nous](../09-modules/nous.md) is enabled from k = 3. With `[nous].drive_actions` on (the shipped default), Nous's chosen actions become proposals that the executive realizes as `think`, `speak` or `rest` intents, subject to the same volition guards as every other intent. [Hypnos](../09-modules/hypnos.md) accepts a rest request no more often than `requested_rest_min_interval_s`, and [Vox](../09-modules/vox.md) marks the origin of speech that follows a Nous proposal. Nous's learned transition model is preserved in each viewing's bundle, so later accumulate steps resume from what it has learned.

If [Phantasia](../09-modules/phantasia.md) is enabled, the runner checks that the step's bundle `manifest.json` reports `world_model_captured: true`; otherwise it fails as `failed:world_model_not_captured` or `failed:manifest_unreadable`. Each step record carries `world_model_captured` (null when Phantasia is off).

## Run the study in a container

`compose/kaine.yml` carries a `kaine-study` service under `profiles: [study]`, so a plain `docker compose up` never starts it. It runs the runner inside the cycle image with the cycle's configuration, secrets, and model mounts, the same environment block as `kaine-cycle`, no published ports, and no restart policy. It does not mount the entity-state, evaluation, or trajectory volumes; every step lives inside the study directory on the durable `kaine-studies` volume mounted at `/app/studies`.

Inside the container, models are at `/models` (the runner honours an exported `KAINE_MODELS_DIR` over `state/models`, and child cycles inherit it), and the bus is `redis://kaine-redis:6379`, authenticated by `KAINE_REDIS_PASSWORD`.

```bash
docker compose -f compose/kaine.yml --profile study run --rm kaine-study \
    init --study-id <id> --repo-root /app \
    --programme-manifest <absolute path of the manifest inside the container> \
    --redis-base-url redis://kaine-redis:6379

docker compose -f compose/kaine.yml --profile study run --rm kaine-study \
    run --study-dir studies/<id>
```

`status` and `analyse` are invoked the same way. After an interruption with no recorded failure, `run` resumes at the first incomplete step. After a failed step, retry with `--retry-failed`; plain `run` exits 1.

The films and manifest are operator media and are not in the image. Add them as read-only bind mounts in a local compose overlay, at the same absolute path inside the container that the manifest uses:

```yaml
services:
  kaine-study:
    volumes:
      - /absolute/host/path/to/films:/absolute/host/path/to/films:ro
      - /absolute/host/path/to/programme.toml:/absolute/host/path/to/programme.toml:ro
```

### Voice alignment in the container

Voice alignment is enabled only on the pre-registered steps. The study overlay sets `trainer_backend = "job_queue"`, `hot_swap_mode = "organ_adapter"` and `trainer_jobs_dir = "/trainer-jobs"` there, and disables it elsewhere. The `kaine-study` run itself needs `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`, because the child cycle's Hypnos checks it, and so does the `kaine-trainer` service. The `kaine-study` service mounts the `kaine-trainer-jobs` and `kaine-organ-adapters` volumes used by the `kaine-trainer` service. Start the trainer with `--profile training`; it needs `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED`. The trainer waits for the organ to report asleep before starting a job, so setting `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS=-1` stalls container training jobs. `docker/organ-launcher.sh` restarts the organ when a new adapter is promoted.

For details on backends and hot-swap modes, see [Voice alignment](../10-sleep/voice-alignment.md).

## What a study records

The ignition log is the workspace-graph record. It writes one row for every successful workspace broadcast, at full rate and never sampled, because an ignition is a discrete event and sampling would miss them. Each row contains coalition members (entry id, source, type, salience, original timestamp), salience scores, inhibition, timing, programme position and time scale. It never holds payloads or perceptual embeddings. It grows about 11 MB per hour of running. It is kept for the paper analysis and afterwards as training data for the world model; nothing reads it for training yet. Only the operator deletes it, after both uses; it is never purged automatically.

A study also keeps the research event log, external utterances, and the preservation monitors (divergence monitor and welfare response). Gestation readouts are recorded normally. No evaluation observer runs in a study: the overlay sets `[evaluation].enabled = false`, so there are no A/B organ calls, memory probes or other instrument logs during a viewing. The welfare net is unaffected, because its gray-zone producer runs with the welfare response, not with evaluation. The Nexus record, the workspace trajectory, and the research-event raw archive are never enabled in a study.

## Read the report

```bash
python -m kaine.research.ignition_study analyse --study-dir studies/<study-id>
```

This writes `analysis/report.json` and `analysis/report.md` in the study directory. The report is content-free: it emits counts, rates, shares and distributions only; no broadcast payload or member type strings.

Automatic time dilation is off during study runs unless enabled in the study configuration. The run manifest records timing settings under `timing`, and the analysis reports `time_scale_min`, `time_scale_max`, `time_scale_changed` and `broadcasts_per_tick`. Viewings whose scale changed are compared per tick rather than per film minute, because the programme plays at real time while the subjective tick pace changed.

Per viewing, the report records:

- Broadcast rate over unpaused programme time (Hypnos replays and freezes are excluded from the denominator).
- Broadcasts per film-minute bin, one bin per minute of `offset_s` for each film; bins with no programme coverage are absent rather than zero.
- Coalition size mean, median and p90.
- Module share: the fraction of broadcasts whose coalition contains each module, by member `source`. Workspace-internal sources (`syneidesis`, `volition`) are counted separately, never as faculties.
- Member salience mean, p50 and p90, by module.
- Inhibited share.
- Picture-to-sound drift: median and maximum absolute `programme.offset_s - audio.delivered_s` when recorded.
- Data quality: record count, programme-time gaps longer than 10 s, and dropped records inferred from gaps in the sink sequence.

Per-viewing measures are computed for every completed viewing of `branch`, `repeat` and `accumulate`; gestation is not a viewing. The report's `comparisons` section holds three families, each with per-measure differences and the film-minute profile correlation:

- **Module effect from the seed**: branch k − branch 0, for k = 1..K.
- **Noise floor**: branch 0 − repeat.
- **Familiarity and history**: accumulate k − branch k, for k = 1..K.

A comparison whose two viewings are not both complete is reported as `pending` and is not computed. Correlations are "not computed" when the two profiles share fewer than 30 bins, and undefined when either profile is constant.

## Limits of the report

The limits section is part of every report: there is one being per condition and nothing is tested for significance; the noise floor is a single repeat, so differences smaller than it are not evidence; modules are added in one fixed order; the accumulate line mixes familiarity with module history because there is no rewatch-only line; and Praxis, Perception and Mundus have no input channel on this host and are expected nulls.
