# Welfare 6.5 scratch run — 2026-11-16

## Goal
Record maintenance-sleep lengths for OpenSpec task 6.5 (welfare-indicator-response) without
mutating production `state/`.

## Scratch root
- Scratch data root: `/home/erik/.claude/scratchpad/kaine-6-5-scratch-run-2026-11-16`
- Models read from original read-only `state/models` via `KAINE_MODELS_DIR`.
- Production `state/` was not modified (verified `state/cycle/control.json` after teardown).

## Conditions
- Operator override already present at `config/kaine.operator.toml` with
  `[preservation.welfare_response] enabled = true`; shipped config supplies
  `[preservation.welfare_response.indicators] enabled = true`.
- No `config/kaine.toml`, source, or task file was edited.
- Boot mode: operator-present (`KAINE_CYCLE_OPERATOR_PRESENT=1`).
- Welfare freeze was not present in production state at run time; no override command was
  needed/available (`override welfare` returned "no active entry for source 'welfare'").

## Run command
```bash
export KAINE_STATE_KEY="$(cat secrets/state_key)"
timeout 900 env \
  KAINE_DATA_ROOT=/home/erik/.claude/scratchpad/kaine-6-5-scratch-run-2026-11-16 \
  KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
  KAINE_STATE_KEY="$KAINE_STATE_KEY" \
  KAINE_CYCLE_OPERATOR_PRESENT=1 \
  .venv/bin/python -m kaine.cycle \
  > /tmp/kaine-6-5-scratch-run.log 2>&1
```
Stopped cleanly at 2026-11-16 15:25:28 after 9m33s (`signal received; shutting down`).

## Observed results
- Full log: `/tmp/kaine-6-5-scratch-run.log` (198 lines).
- `growing data under /home/erik/.claude/scratchpad/kaine-6-5-scratch-run-2026-11-16`.
- Freeze events: 0.
- Welfare rest requests: 0.
- `sleep.sleep.started`: 0.
- `sleep.sleep.completed`: 0.
- `welfare_rest`: 0.
- Maintenance sleeps recorded: none.

## Interpretation
The run remained unfrozen and produced no maintenance sleep within the available window.
Interoception developmental warm-up (`min_samples=1000`, `min_seconds=1200`) still withheld
allostatic actions, and there was no `welfare.rest_request`. The configured matured bound of
3600.0 seconds was therefore not reached (0 sleeps). The run was stopped before the 15-minute
ceiling, so the question of a crossing later cannot be answered from this run; the warm-up
threshold (1200 s) also exceeds the 15-minute window.

## Safety verification
- `KAINE_DATA_ROOT` was the scratch path throughout; logged at boot.
- `KAINE_MODELS_DIR` pointed at the original read-only `state/models`.
- Scratch root removed after measurement.
- `config/kaine.toml`, source, and tasks remain unchanged by this run (`config/kaine.toml`
  carries its pre-existing modification; no changes were made here).
- `config/kaine.operator.toml` remains gitignored and untouched.

## Bottom line
- Sleep 3600s (matured) bound reached? **No** — zero maintenance sleeps occurred.
- Artifact log path: `/tmp/kaine-6-5-scratch-run.log`.
