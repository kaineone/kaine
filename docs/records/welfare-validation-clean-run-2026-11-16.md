# Welfare validation clean run — 2026-11-16

## Goal
Record maintenance-sleep lengths for task 6.5 without mutating production `state/`.
Performed per `docs/records/state-root-validation-guide-2026-11-16.md`.

## Environment
- Repo root: `/var/home/erik/Projects/kaineone/kaine`
- Git branch: `feat/audition-encoder-bakeoff` (worktree untouched)
- Python: `.venv/bin/python` (3.12)
- Production state remained frozen (source=welfare); it was not modified.

## Exact commands

Scratch data root (outside repo, models excluded):

```bash
SCRATCH=/tmp/kaine-scratch-validation-20261116b
rm -rf "$SCRATCH" && mkdir -p "$SCRATCH"
rsync -a --exclude='models' state/ "$SCRATCH/state/"
```

Override the welfare freeze in the clone only:

```bash
KAINE_DATA_ROOT="$SCRATCH" \
KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
KAINE_STATE_KEY="$(cat secrets/state_key)" \
.venv/bin/python -m kaine.cycle.control override welfare
```
Result: `Lifted: welfare; still frozen by: none` (exit 0). Production `state/cycle/control.json` left untouched and frozen.

Validation boot (120 s max):

```bash
timeout 120 env \
  KAINE_DATA_ROOT="$SCRATCH" \
  KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
  KAINE_STATE_KEY="$(cat secrets/state_key)" \
  KAINE_CYCLE_OPERATOR_PRESENT=1 \
  .venv/bin/python -m kaine.cycle > /tmp/kaine-validation-boot-120.log 2>&1
```
Exit status: `124` / process terminated by timeout at 120 s (`exit=144` SIGTERM), followed by graceful shutdown log.

Teardown:

```bash
rm -rf "$SCRATCH"
```
Both scratch trees removed; no scratch state retained.

## Observed results

- Full log: `/tmp/kaine-validation-boot-120.log` (144 lines).
- Freezes: none observed in the clone (`grep -ci freeze` = 0).
- Welfare rest requests started: 0 (`grep -ci "welfare net"` = 0).
- `sleep.sleep.started` / `sleep.sleep.completed` events: 0 (`grep -ci "sleep.sleep"` = 0).
- Maintenance sleeps recorded: **none** within the 120 s window.
- Interoception developmental warm-up was active (`min_samples=1000`, `min_seconds=1200`), which withholds allostatic actions; consequently no welfare-driven `welfare_rest` maintenance sleep was triggered during the observation window.
- Boot errors present but non-fatal: continued individuation probe failures (`served organ identity unavailable`), plus a failed text embedder fallback (hash embedder). No crash; shutdown was graceful.

## Interpretation

The 120 s validation window did not reach a welfare indicator crossing, so no matured maintenance sleep executed and no length was directly measured. The matured completion bound remains the configured value `rest_complete_matured_s = 3600.0` (see `config/kaine.toml` `[preservation.welfare_response.indicators].rest_complete_timeout_s.matured`); no sleep exceeded or violated it because none ran. A longer run (minutes to hours, or entity-time scaling) would be required to trigger a crossing; that exceeds the permitted 120 s ceiling and was not attempted.

## Safety verification

- `KAINE_DATA_ROOT` was the scratch path during the override and boot (echoed in log: `growing data under /tmp/kaine-scratch-validation-20261116b`).
- `KAINE_MODELS_DIR` pointed at the original read-only `state/models`; models were excluded from the copy.
- Production `state/` (including `state/forks`, `state/models`, `state/identity`, frozen `control.json`) was not copied-over or modified; production control remains frozen by `welfare`.
- Scratch trees are removed; no fork left behind.
- No source or task files were edited.