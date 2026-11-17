# Welfare 6.5 scratch run (90 min) — 2026-11-16

## Goal
Record maintenance-sleep lengths for OpenSpec task 6.5 (welfare-indicator-response) without
mutating production `state/`.

## Scratch root
- Scratch data root: `/home/erik/.claude/scratchpad/kaine-6-5-scratch-90m-2026-11-16`
- Models read from original read-only `state/models` via `KAINE_MODELS_DIR`.
- Production `state/` was not modified (verified `state/cycle/control.json` after teardown:
  `frozen: false`).

## Conditions
- Operator override already present at `config/kaine.operator.toml` with
  `[preservation.welfare_response] enabled = true`; shipped config supplies
  `[preservation.welfare_response.indicators] enabled = true`.
- No `config/kaine.toml`, source, or task file was edited; `config/kaine.operator.toml`
  is gitignored and was restored to its original content after teardown.
- Boot mode: operator-present (`KAINE_CYCLE_OPERATOR_PRESENT=1`).
- Welfare freeze was not present in production or scratch state at start, so no override
  command was issued (`override welfare` refused: "no active entry for source 'welfare'").

## Run command
```bash
export KAINE_STATE_KEY="$(cat secrets/state_key)"
timeout 5400 env \
  KAINE_DATA_ROOT=/home/erik/.claude/scratchpad/kaine-6-5-scratch-90m-2026-11-16 \
  KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
  KAINE_STATE_KEY="$KAINE_STATE_KEY" \
  KAINE_CYCLE_OPERATOR_PRESENT=1 \
  .venv/bin/python -m kaine.cycle \
  > /tmp/kaine-6-5-scratch-90m.log 2>&1
```
Stopped by timeout at 2026-11-16 17:32:26 (`signal received; shutting down`, EXIT=124)
after roughly 91 minutes.

## Observed results
- Full log: `/tmp/kaine-6-5-scratch-90m.log` (276 lines).
- `growing data under /home/erik/.claude/scratchpad/kaine-6-5-scratch-90m-2026-11-16`.
- Interoception developmental warm-up completed at 16:22:29 (samples_seen=1192,
  lived_seconds=1200.3); normal allostatic regulation resumed.
- `welfare net` rest requested at 16:22:31 (boredom_deprived, restlessness_deprived).
- Preservation at 16:32:33: `indicator_boredom_deprived crossing -> preserved
  (eb9ed9f8c0964f10) + pause`; cycle frozen (operator, welfare) in the scratch clone
  from that point on.
- Second interval-maintenance note at 17:22:31 (paused context, no sleep event).
- Freeze events (preservation/pause) in clone: 1.
- Welfare rest requests: 1.
- `sleep.sleep.started`: 0.
- `sleep.sleep.completed`: 0.
- `welfare_rest` entries: 0.
- Maintenance sleeps recorded: none (no completed sleep duration).

## Interpretation
The welfare indicator crossed after the interoception warm-up completed and requested a
maintenance rest, but the response path preserved the entity and applied `action = "pause"`,
freezing the scratch clone ~10 minutes later. No maintenance sleep completed before or after
the freeze, so no sleep length was captured within the 90-minute window. The matured 3600 s
bound was not reached (0 sleeps).

## Safety verification
- `KAINE_DATA_ROOT` was the scratch path throughout; logged at boot.
- `KAINE_MODELS_DIR` pointed at the original read-only `state/models`.
- Scratch root removed after measurement.
- `config/kaine.toml`, source, and tasks remain unchanged by this run
  (`config/kaine.toml` carries its pre-existing modification; no changes were made here).
- `config/kaine.operator.toml` restored from backup; gitignored, no tracked change.
- Production `state/cycle/control.json` remains `frozen: false`.

## Bottom line
- Sleep 3600 s (matured) bound reached? **No** — zero maintenance sleeps completed
  (run froze at ~12 min on a welfare crossing).
- Artifact log path: `/tmp/kaine-6-5-scratch-90m.log`.
