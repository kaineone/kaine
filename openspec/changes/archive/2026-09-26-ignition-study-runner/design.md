# Design — `ignition-study-runner`

## Plan (`study.json`)

```json
{"study_id": "...", "created_at": "...", "repo_root": "/abs/repo",
 "base_modules": ["soma","chronos","topos","audition","lingua"],
 "order": ["thymos","mnemos","hypnos","phantasia","nous","eidolon","empatheia","vox","praxis","perception","mundus"],
 "programme": {"manifest": "/abs/programme.toml", "sha256": "..."},
 "redis": {"base_url": "redis://127.0.0.1:6479", "db": {"gestation": 10, "main": 11, "control": 12}},
 "collections": {"gestation": "study_<id>_g_", "main": "study_<id>_m_", "control": "study_<id>_c_"},
 "viewings_per_line": 12}
```

- Syneidesis and Volition are not modules; they always run.
- `init` validates the plan:
  - every module name is known;
  - no duplicates;
  - base and order are disjoint;
  - the three db numbers differ;
  - the programme sha256 matches the file.
- It writes the plan once. A second `init` on an existing study refuses.

## Line directories

- `init` creates `gestation/`, `main/` and `control/`, each with `config/kaine.toml` and `config/profiles` as symlinks to the repository's. The copies are never edited.
- Before every start, the runner writes the line's `config/kaine.operator.toml`. It deep-merges:
  1. the operator's `<repo>/config/kaine.operator.toml`, when present;
  2. the study overlay:
     - `[modules]`: exactly the step's set enabled, every other module disabled;
     - `[perception_feed]`: `mode` and `playlist_manifest`;
     - `[developmental_stage].enabled = true`;
     - `[mnemos].collection_prefix`, `[empatheia].collection`;
     - `[ignition_log].enabled = true`;
     - `[research_event_log].enabled = true`;
     - `[preservation.divergence_monitor].enabled = true`, `[preservation.welfare_response].enabled = true`;
     - `[phantasia].training_enabled = true`, `[phantasia].persist_weights = true`;
     - model directories made absolute against the repository.
- The overlay is recorded in the step record (as its sha256 plus the module set). It is never secret-bearing: keys stay in the environment or keyring.

## Process control

- **Start.** `subprocess.Popen([python, "-m", "kaine.cycle", "--revive", bundle], cwd=line_dir, env=...)`. The environment is `os.environ` plus `KAINE_RESEARCH_MODE=1` and `KAINE_REDIS_URL=<base>/<db>`. Gestation starts have no `--revive`.
- **Gestation.**
  1. Poll `line/state/cycle/runtime.json` every 5 s. When `developmental_stage.stage == "embodied"`, run `python -m kaine.cycle.control preserve --reason birth --stop --wait 600` in the line directory.
  2. Wait for the process to exit, and read `state/cycle/preserve_result.json`.
- **Viewing.**
  1. Wait for the process to exit.
  2. Read `preserve_result.json`. The step is complete only if the result is `ok` and its request reason is `programme end`, the request having been written by the end-of-programme watcher.
  3. Otherwise the step failed.
- **Timeout.** When a start exceeds its budget (default: programme length + 2 h, or 72 h beyond the 24 h gestation minimum), the runner does not kill it.
  1. It requests `preserve --stop --reason timeout`, so the being is saved before it stops.
  2. If that preservation reports success, the step is recorded `failed:timeout` with the bundle kept.
  3. If it fails or never reports, the runner leaves the process running, logs at CRITICAL, and exits non-zero for the operator.
  
  The runner never sends SIGKILL, and never stops a being it could not preserve.
- **Reading the result.** The runner reads the request file (`state/cycle/preserve_request.json`) for the reason, and the result file for the outcome, matched by request id.
- **Command.** The cycle command is a parameter (default `[sys.executable, "-m", "kaine.cycle"]`). Tests pass a stand-in script, and the plan records which command ran. The runner makes no claim a real run did not produce.

## Step record (`steps.jsonl`)

`{"line", "step", "modules", "started_at", "ended_at", "exit_code", "revived_from", "preservation_id", "bundle", "run_id", "ignition_log_dir", "overlay_sha256", "outcome"}`

- `outcome` is `complete` or `failed:<reason>`.
- `run_id` comes from `runtime.json` while the process runs, or from the run manifest.
- A failed step is recorded and the run stops. `run` refuses to continue past a failed step until the operator runs `run --retry-failed`, which re-runs that step from the same start bundle.

## Order

- gestation, then for k = 0 … 11: main k, then control k. Never two starts at once.
- **Resume.** Replay `steps.jsonl` to find each line's last complete bundle and the next step.
- **Locking.** `run` takes an exclusive lock file in the study directory, so two runners cannot drive one study.
