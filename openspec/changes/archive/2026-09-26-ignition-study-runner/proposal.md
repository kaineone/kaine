# Proposal — `ignition-study-runner`

## Why

The module-ignition study (`module-ignition-study`) is about 100 hours of runs: one gestation, then two lines of twelve four-hour viewings each. The entity is revived with a chosen module set, shown the programme, preserved at its end, and stopped, again and again. Done by hand, this invites mistakes that would damage the study or the being:

- a viewing started from the wrong preservation;
- two lines sharing a memory collection or bus database;
- a failed preservation that nobody notices;
- a step run twice.

A runner does it the same way every time and records exactly what happened.

## What changes

- **`python -m kaine.research.ignition_study`**, with subcommands:
  - `init`: create a study directory and its manifest;
  - `run`: run or resume the study;
  - `status`: show progress.
- **Study layout** `studies/<study-id>/`:
  - `study.json`: the plan. It holds the module order, the programme manifest and its sha256, the Redis base URL and db numbers, and the collection prefixes.
  - `steps.jsonl`: one record per completed step.
  - `gestation/`, `main/`, `control/`: one working directory per line. Each holds `config/kaine.toml` and `config/profiles/`, both linked to the repository's, and a generated `config/kaine.operator.toml`.
- **Per-line isolation.** Each line has its own working directory, which holds all cwd-relative state. It also has its own Redis database, set through `KAINE_REDIS_URL`, and its own Qdrant collection prefix and Empatheia collection.
  - Model directories are absolute, so the lines share the downloaded models but nothing the entity lives in.
  - The generated overlay merges the operator's own `config/kaine.operator.toml` (inference servers, keys and so on) with the study settings for that line and step.
- **Steps:**
  - **Gestation.** Womb mode, with the base modules. When `runtime.json` reports the entity born, the runner requests `preserve --stop` with reason `birth`. The bundle is P0.
  - **Viewings.** For k = 0 … 11 on each line, main before control:
    1. Revive from the line's previous bundle (P0 for k = 0), in playlist mode.
    2. Main enables the base modules plus the first k of the order; control enables the base modules only.
    3. The step ends when the end-of-programme preservation reports `ok`, and its bundle becomes the line's next start.
  - Each viewing is one start of `python -m kaine.cycle --revive <bundle>`.
- **Supervision.** Every start is a research-mode boot (`KAINE_RESEARCH_MODE=1`), the unattended mode that requires the autonomous safety net.
- **Halting.** Any step that ends another way halts the study with a clear report, and the runner never retries on its own. That includes:
  - a non-zero exit, such as revive refused (7), gate refused (5), or Spot escalated (70);
  - a welfare-protective end or pause;
  - a missing or failed preservation result.

  The operator decides.
- **Resume.** `run` skips steps already recorded in `steps.jsonl` and continues from the last recorded bundle of each line.
- **The runner never deletes anything:** no preservation, no state, no line.

## Depends on

- `operator-revive-and-preserve` (`--revive`, `control preserve`)
- `film-end-preserve` (the end-of-programme preservation)
- `film-aligned-ignition-log` (the log each viewing writes)
- `snapshot-completeness`, `faculty-relative-birth`, `study-confounds`

## Impact

- New package `kaine/research/ignition_study/`. No change to the entity's cognition.
- Two preserved beings are created and kept.
