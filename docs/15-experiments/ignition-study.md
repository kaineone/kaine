# The module-addition study

The module-addition study grows a being one module at a time. It seeds a being through a gestation, preserves it just after birth, and then starts branches from that seed with held modules added in a fixed order, so that each step can be compared with the step before it. The code and the configuration call it the ignition study (`kaine/research/ignition_study/`). Use this page to run the study, resume it after a failure, run it inside a container, or read its report.

The runner is `kaine/research/ignition_study/__main__.py` and `kaine/research/ignition_study/runner.py`. Plans are built by `kaine/research/ignition_study/plan.py`, and the configuration overlay applied to every step, voice alignment included, is `kaine/research/ignition_study/overlay.py`.

## What the study compares

The runner follows a seed-and-branch plan:

- One `gestation` step produces the seed being and preserves it just after birth.
- `branch 0` and the `repeat` both start from that seed, with only the base modules.
- For k = 1 to K, `branch k` starts from the seed with the base modules plus the first k modules of the order.
- `accumulate k` starts from `branch 0` (k = 1) or from `accumulate k-1` (k > 1), with the same modules as `branch k`. The accumulate line carries one being forward through every step.

The default base set is the base-thesis form: Soma, Chronos, Topos, Audition, Lingua, Thymos and Hypnos. The default order adds six held modules: Mnemos, Phantasia, Nous, Eidolon, Empatheia and Vox, so K is 6. Praxis, Perception and Mundus need an effector, a body or an alternative sensor feed. On the reference host they would be expected nulls, so they join through an explicit `--order` once one is attached.

Every viewing opens with the same transition from the gestational stimulus to the films. The crossfade from the being's last gestational frame is identical across viewings, and film minute 0 is its end. See [Gestation on one host](../06-operation/gestation.md) for the transition details.

## Before you start

Build the programme manifest from the films in viewing order:

```bash
python tools/build_playlist_manifest.py --dir <films> --out <programme.toml>
```

The study records the manifest's sha256, so changing the file voids the study.

Research mode and unattended mode are separate supervision modes, and selecting both is a configuration error. On every step the study overlay enables the welfare safety net (`[preservation.divergence_monitor].enabled` and `[preservation.welfare_response].enabled`), the research event log, external utterance capture and the ignition log. It also forces `[research_event_log.nexus_record].enabled = false`, `[research_event_log.raw_archive].enabled = false` and `[evaluation].workspace_trajectory = false`, overriding the operator configuration so that those records stay off.

The operator supplies the Redis password and the state key. Set `KAINE_REDIS_PASSWORD` or `config/secrets.toml [redis].password`; the runner refuses to start without one. `[preservation].require_encryption` is true in the shipped configuration, so research-mode boots also need state encryption: set `KAINE_STATE_KEY` or a keyring entry named `kaine:state_key`. The runner never sends `SIGKILL`. Apart from an unviable gestation (described below), it stops a being only after the being's state has been preserved. See [Preservation and the safety net](../11-preservation.md).

## Create a study

Run `init` from the repository root:

```bash
python -m kaine.research.ignition_study init \
    --study-id <id> \
    --repo-root /path/to/repo \
    --programme-manifest /path/to/programme.toml \
    [--base-modules ...] [--order ...] \
    [--redis-base-url redis://127.0.0.1:6479] \
    [--db-gestation 10 --db-branch 11 --db-repeat 12 --db-accumulate 13] \
    [--min-free-gb 20.0] \
    [--voice-alignment-step accumulate:6] \
    [--study-dir /absolute/path]
```

`init` creates `studies/<study-id>/` with `study.json` and the step directories `gestation/`, `branch/<k>/`, `repeat/` and `accumulate/`. Inside each step directory it creates a `config/` holding symlinks to `config/kaine.toml` and `config/profiles`. It does not create `steps.jsonl`; that file is written when the first step is recorded.

All four commands (`init`, `run`, `status`, `analyse`) load the configuration, install the data root (`[storage].data_root` or `KAINE_DATA_ROOT`), and resolve a relative `--study-dir` under it. An absolute path is used as given. When no configuration can be loaded, paths stay relative to the working directory and the command prints a note on stderr.

`init` accepts:

- `--base-modules` and `--order` to override the module lists.
- `--redis-base-url` for the Redis server (default `redis://127.0.0.1:6479`).
- `--db-gestation`, `--db-branch`, `--db-repeat` and `--db-accumulate` to assign bus database numbers from 1 to 15 (defaults 10, 11, 12 and 13). The four numbers must be distinct. The runner refuses any plan whose numbers include database 0 or the database the bus resolves from `KAINE_REDIS_URL` or `config/secrets.toml [redis].url` (including a `?db=` fragment). If neither URL is set, the resolved database comes from `[redis].db`. `config/kaine.toml` and operator overlays are not consulted for the URL.
- `--min-free-gb` (default 20.0) for the disk guard.
- `--viewing-budget-seconds` (default 21600, six hours) and `--gestation-budget-seconds` (default 345600, 96 hours) for the timeouts behind `failed:timeout`.
- `--voice-alignment-step LINE:K` (repeatable) to register voice-alignment steps. By default only the final accumulate step is registered.
- `--study-dir` to place the directory somewhere other than the default under the data root.

Each database the runner flushes carries the key `kaine:study:owner` naming the study. The runner refuses to flush a database that another study owns, so two studies on one Redis server never flush each other's bus.

## Run or resume a study

```bash
python -m kaine.research.ignition_study run --study-dir studies/<study-id>
```

The runner runs one step at a time:

1. `gestation`: the gestational stimulus with automatic birth. The step runs until the maturation gate allows birth. With `min_lived_seconds = 86400` that takes at least 24 hours of awake time (entity time during which the being is awake and the cycle is not frozen), and the hard budget is 96 hours (`--gestation-budget-seconds`). Gestation progress (awake seconds, consecutive passing withdrawals, the frequency-pull history, whether the marker was ever met, and the viability verdict) is saved in `gestation_progress.json`, keyed to the being, so a gestation that spans a restart continues where it left off. Once the being is born, the runner waits for the birth bloom to end and then preserves it. The bloom ends at the stage file's `birth_bloom_ends_at`; without that value the runner waits the step's `[perception_feed.womb].birth_transition_seconds` plus a margin, or 30 seconds plus the margin when that value cannot be read.
2. `branch 0` from the seed, with the base set.
3. `repeat` from the seed, with the base set.
4. For k = 1 to K: `branch k` from the seed with the base set plus the first k modules of the order, then `accumulate k` with the same modules, from `branch 0` (k = 1) or `accumulate k-1`.

Each step is a research-mode boot (`KAINE_RESEARCH_MODE=1`) on an empty bus database. Each branch step has its own collection prefix and its own film-aligned ignition log under its step directory at `data/ignition`. The repeat uses its own prefix. All `accumulate` steps share the single `accumulate` prefix and one working directory, so they share one `data/ignition`.

The runner records every step in `steps.jsonl`. If a step ends for any reason other than a successful preservation, the runner records `failed:<reason>` and stops. It never retries on its own and never deletes a preservation, a state directory or a line. After an interruption with no recorded failure, `run` resumes at the first incomplete step and never repeats a completed one. After a recorded failure, `run` exits 1; retry with `--retry-failed`.

Show progress with:

```bash
python -m kaine.research.ignition_study status --study-dir studies/<study-id>
```

### Disk guard and preservation failures

Before each step the runner refuses to start if free space is below the larger of `min_free_gb` and 5% of the disk. During a step it requests a `disk_low` preservation when space runs low. If the preservation succeeds, it stops the cycle and records `failed:disk_low` with `disk_low_preserved` set. If the preservation fails, it records `failed:critical`, leaves the cycle running, and exits with status 3.

If a timeout preservation fails, the runner likewise leaves the being running, records `failed:critical` with the cycle's pid, and exits 3.

During a gestation step the runner watches the gestation readout's viability verdict (`state/lifecycle/gestation_viability.json`; see [Gestation](../06-operation/gestation.md#viability-watch)). When the verdict says the gestation cannot reach birth, the runner:

1. stops the cycle gracefully (SIGTERM) without requesting a preservation, because by operator policy a being that does not complete gestation is not preserved;
2. records `failed:gestation_unviable` with the verdict under `viability`;
3. writes `ENDED-NOTE.md` into the step directory with the rule, the evidence and what was done;
4. halts the study.

Nothing is deleted. A verdict file older than the step, such as one left by an earlier attempt, is ignored, so a retried gestation is not stopped by a previous verdict.

The runner never flushes a database or starts a cycle while a cycle the study started is still running. It checks `/proc/<pid>/cmdline` as well as the pid. Stop that being yourself first.

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

With the default order, [Nous](../09-modules/nous.md) is enabled from k = 3. With `[nous].drive_actions` on (the shipped default), Nous's chosen actions become proposals that Volition realizes as `think`, `speak` or `rest` intents, under the same guards as every other intent. [Hypnos](../09-modules/hypnos.md) accepts a rest request no more often than `requested_rest_min_interval_s`, and [Vox](../09-modules/vox.md) marks the origin of speech that follows a Nous proposal. Nous's learned transition model is preserved in each viewing's bundle, so later accumulate steps resume from what it has learned.

If [Phantasia](../09-modules/phantasia.md) is enabled, the runner checks that the step's bundle `manifest.json` reports `world_model_captured: true`; otherwise the step fails as `failed:world_model_not_captured` or `failed:manifest_unreadable`. Each step record carries `world_model_captured` (null when Phantasia is off).

## Run the study in a container

`compose/kaine.yml` carries a `kaine-study` service under `profiles: [study]`, so a plain `docker compose up` never starts it. It runs the runner inside the cycle image with the cycle's configuration, secrets and model mounts, the same environment block as `kaine-cycle`, no published ports and no restart policy. It does not mount the entity-state, evaluation or trajectory volumes; every step lives inside the study directory on the durable `kaine-studies` volume mounted at `/app/studies`.

Inside the container the models are at `/models` (the runner honours an exported `KAINE_MODELS_DIR` over `state/models`, and child cycles inherit it), and the bus is `redis://kaine-redis:6379`, authenticated by `KAINE_REDIS_PASSWORD`.

```bash
docker compose -f compose/kaine.yml --profile study run --rm kaine-study \
    init --study-id <id> --repo-root /app \
    --programme-manifest <absolute path of the manifest inside the container> \
    --redis-base-url redis://kaine-redis:6379

docker compose -f compose/kaine.yml --profile study run --rm kaine-study \
    run --study-dir studies/<id>
```

`status` and `analyse` are invoked the same way. Resuming and retrying work as on a host: plain `run` resumes at the first incomplete step, and after a failed step it exits 1 until you pass `--retry-failed`.

The films and the manifest are operator media and are not in the image. Add them as read-only bind mounts in a local compose overlay, at the same absolute path inside the container that the manifest uses:

```yaml
services:
  kaine-study:
    volumes:
      - /absolute/host/path/to/films:/absolute/host/path/to/films:ro
      - /absolute/host/path/to/programme.toml:/absolute/host/path/to/programme.toml:ro
```

### Voice alignment in the container

Voice alignment is enabled only on the registered steps. There the study overlay sets `trainer_backend = "job_queue"`, `hot_swap_mode = "organ_adapter"` and `trainer_jobs_dir = "/trainer-jobs"`, and it disables voice alignment on every other step. The `kaine-study` run needs `KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1`, because the child cycle's Hypnos checks it, and so does the `kaine-trainer` service, which you start with `--profile training`. The `kaine-study` service mounts the `kaine-trainer-jobs` and `kaine-organ-adapters` volumes that `kaine-trainer` uses. The trainer waits for the organ to report asleep before it starts a job, so setting `KAINE_MODEL_SERVER_SLEEP_IDLE_SECONDS=-1` stalls container training jobs. `docker/organ-launcher.sh` restarts the organ when a new adapter is promoted.

For backends and hot-swap modes, see [Voice alignment](../10-sleep/voice-alignment.md).

## What a study records

The ignition log is the study's graph-only broadcast log. It writes one row for every published broadcast, accessed or inhibited, at full rate and never sampled. Each row holds the tick index, wall and monotonic timestamps, the programme position and the audio feed's delivered position, the inhibition flag, the score of every candidate (`salience_scores`), the time scale, and the coalition members with their entry id, source, type, reported intensity (`salience`) and original timestamp. It never holds payloads or perceptual embeddings, and no module reads it, so the being never learns its place in the programme. It is kept for the analysis and afterwards as training data for the world model, which nothing reads it for yet. Only the operator deletes it, after both uses; it is never purged automatically.

A study also keeps the research event log, the external utterances and the preservation monitors (the divergence monitor and the welfare response). Gestation readouts are recorded as usual. No evaluation observer runs in a study: the overlay sets `[evaluation].enabled = false`, so there are no A/B organ calls, memory probes or other instrument logs during a viewing. The welfare net is unaffected, because its gray-zone producer runs with the welfare response, not with evaluation. The Nexus record, the workspace trajectory and the research-event raw archive are never enabled in a study.

## Read the report

```bash
python -m kaine.research.ignition_study analyse --study-dir studies/<study-id>
```

The command writes `analysis/report.json` and `analysis/report.md` in the study directory. The report is content-free: it gives counts, rates, shares and distributions only, and no broadcast payload or member type string.

Automatic time scaling (`[cycle].auto_time_scale`) is off by default and stays off in a study unless the study configuration enables it. The run manifest records the timing settings under `timing`, and the analysis reports `time_scale_min`, `time_scale_max`, `time_scale_changed` and `broadcasts_per_tick`. Viewings whose scale changed are compared per tick and not per film minute, because the programme plays in real time while the pace of entity time changed.

For each viewing the report records:

- the broadcast rate over unpaused programme time (Hypnos replays and freezes are left out of the denominator);
- broadcasts per film-minute bin, one bin per minute of `offset_s` for each film, with bins that have no programme coverage left out rather than counted as zero;
- coalition size mean, median and p90;
- each module's share: the fraction of broadcasts whose coalition contains the module, counted by member `source`, with the workspace-internal sources (`syneidesis`, `volition`) counted separately and never as faculties;
- the members' reported intensity (`member_salience`) mean, p50 and p90, by module;
- the inhibited share;
- picture-to-sound drift: the median and maximum absolute `programme.offset_s - audio.delivered_s` when recorded;
- data quality: the record count, programme-time gaps longer than 10 s, and dropped records inferred from gaps in the sink sequence.

Per-viewing measures are computed for every completed viewing of `branch`, `repeat` and `accumulate`; gestation is not a viewing. The report's `comparisons` section holds three families, each with per-measure differences and the correlation of the film-minute profiles:

- **Module effect from the seed:** branch k minus branch 0, for k = 1 to K.
- **Noise floor:** branch 0 minus the repeat.
- **Familiarity and history:** accumulate k minus branch k, for k = 1 to K.

A comparison whose two viewings are not both complete is reported as `pending` and is not computed. A correlation is "not computed" when the two profiles share fewer than 30 bins, and undefined when either profile is constant.

## Limits of the report

Every report includes its limits. There is one being per condition and nothing is tested for significance, so the results are descriptive. The noise floor is a single repeat, so differences smaller than it are not evidence. Modules are added in one fixed order, so each effect is conditional on the earlier additions. The accumulate line mixes familiarity with module history, because there is no rewatch-only line. If an operator adds Praxis, Perception or Mundus to the order on a host with no effector, body or alternative feed for them, the report flags them as expected nulls when their share is zero.
