# Agent runner job queue manual

One-page reference for authoring and running KAINE maintainer agent jobs.
Queue files are plain JSON; no Python edits or knowledge are required to define,
inspect, or hand off a job set. Local execution is capped at 4 lanes.

## Job schema

Each job is one object. Field aliases are accepted; use the canonical name.

| Field | Aliases | Type / meaning |
|---|---|---|
| `id` | `name`, `title`, `task`, `job`, `job_id` | stable job name (sanitized to safe path) |
| `brief` | `brief_path`, `brief_file`, `prompt`, `prompt_file`, `brief_text` | path or inline task text |
| `allow` | `allow_paths`, `allowed`, `allowed_paths`, `paths` | files the worker may write (`string[]`) |
| `apply` | `apply_output`, `write`, `do_apply` | write allowed files into repo (default `true`) |
| `command` | `worker_command`, `apply_command`, `run`, `action`, `script` | optional override command |
| `cwd` | `working_dir`, `workdir`, `path`, `workspace`, `root` | working directory |
| `verify` | `verification`, `verify_command`, `verify_commands`, `checks` | post-gen verify commands |
| `tests` | `test`, `test_command`, `test_commands`, `validation` | post-verify test commands |
| `timeout` | `time_limit`, `timeout_seconds` | per-step timeout (seconds) |
| `retries` | `retry_count`, `max_retries`, `attempts` | retry budget (default `0`) |
| `lane` | `lane_id`, `worker_lane` | preferred lane (`int`, modulo lane count) |
| `model` | `worker_model` | worker model tag |
| `env` | `environment`, `environment_variables` | extra env vars (`{KEY: value}`) |

## Queue example

```json
{
  "lanes": 4,
  "repo": ".",
  "out_root": "agent_batch_out",
  "model": "beam:cloud",
  "max_retries": 2,
  "retry_base_delay": 1.0,
  "retry_max_delay": 10.0,
  "verify_default": ["pytest -q"],
  "jobs": [
    {
      "id": "fix-slug",
      "brief": "prompts/fix-slug.md",
      "allow": ["kaine/util/slug.py"],
      "verify": ["pytest tests/test_slug.py"],
      "tests": ["pytest -q"],
      "retries": 2
    },
    {
      "id": "docs-pass",
      "brief": "Review README and fix stale references.",
      "allow": ["README.md"],
      "apply": true
    }
  ]
}
```

## Command template

Dry run (planning only, no worker calls):

```sh
python3 tools/maintainer/agent_batch_runner.py queue.json \
  --dry-run --lanes 4 --out-dir agent_batch_out
```

Execute (4 lanes, retry budget, report):

```sh
python3 tools/maintainer/agent_batch_runner.py queue.json \
  --lanes 4 --out-dir agent_batch_out --retries 2 \
  --retry-base-delay 1 --retry-max-delay 10 --timeout 3900 \
  --model beam:cloud --report agent_batch_out/report.md
```

Single worker (manual, no queue):

```sh
tools/maintainer/worker.py brief.txt out/job \
  --allow kaine/util/slug.py --apply . --model beam:cloud
```

## Retry / backoff

Retries trigger on non-zero exit or an empty worker response (under 10 chars).
Delay per attempt:

`delay = min(max_delay, base * 2^(attempt-1) + random(0.0, 0.5))`

Defaults: `base=1.0s`, `max=10.0s`, `retries=0`.
Each attempt is captured as `worker_attempt_N.stdout` / `.stderr` in the job's
output directory; final status is in `job_state.json`.

## 4-lane local cap

- Never run more than **4 concurrent lanes** on the local host.
- The runner clamps requested lanes to the configured local maximum.
- Prefer 1-3 lanes for heavy GPU steps; reserve 4 for short, I/O-bound jobs.
- Combine with the Ollama 10-request cloud ceiling: 4 lanes x ~2-3 model calls
  per job stays inside it.