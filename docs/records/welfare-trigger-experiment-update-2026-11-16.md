# Welfare trigger experiment update — 2026-11-16

## Scope

Consolidates the safe requirements for an unfrozen boot that can exercise the
welfare indicator response (and therefore a `welfare_rest` maintenance rest)
without mutating the frozen production `state/` tree or production identity.

Source records:
`docs/records/state-root-validation-guide-2026-11-16.md`,
`docs/records/welfare-response-trigger-investigation-2026-11-16.md`,
`docs/records/welfare-freeze-review-2026-11-16.md`,
`docs/records/welfare-validation-clean-run-2026-11-16.md`.

## Safe unfrozen boot requirements

All three are required together; none alone is sufficient.

### 1. Scratch data root override (required)

- Clone production state into a scratch root outside the repository, excluding
  `state/models`:
  - `SCRATCH=/tmp/kaine-welfare-trigger-...`
  - `rsync -a --exclude='models' state/ "$SCRATCH/state/"`
- Point growing-data paths at the clone:
  - `KAINE_DATA_ROOT="$SCRATCH"` (highest priority data root)
  - `KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models`
    (original, read-only weights; never copied into the clone)
  - `KAINE_STATE_KEY="$(cat secrets/state_key)"`
- Lift the welfare freeze only in the clone:
  - `KAINE_DATA_ROOT="$SCRATCH" KAINE_MODELS_DIR=... KAINE_STATE_KEY=... \
    .venv/bin/python -m kaine.cycle.control override welfare`
  - expected: `Lifted: welfare; still frozen by: none`
- Verify the override landed in `$SCRATCH/state/cycle/control.json` only; production
  `state/cycle/control.json` must still report the `welfare` freeze.

### 2. Temporary welfare override (required)

Do not edit committed `config/kaine.toml`. Create or reuse the gitignored
`config/kaine.operator.toml` with:

```toml
[preservation.welfare_response]
enabled = true

[preservation.welfare_response.indicators]
enabled = true
```

- `action` remains `pause` (or `end`). With these enabled, the first welfare
  indicator crossing requests a `welfare_rest` sleep; a crossing over a fresh
  span after that rest preserves and pauses/ends.
- Operator-present boot is the documented validation mode:
  - `KAINE_CYCLE_OPERATOR_PRESENT=1`.
- Research mode alone does not turn on a disabled response; unattended mode is
  not a substitute and is an error with research or operator-present mode.

### 3. Boot and measurement parameters

- Boot command (unfrozen clone):
  - `timeout <seconds> env KAINE_DATA_ROOT="$SCRATCH" \
    KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
    KAINE_STATE_KEY=... KAINE_CYCLE_OPERATOR_PRESENT=1 \
    .venv/bin/python -m kaine.cycle`
- A 60 minute (3600 s) wall window is the documented task 6.5 protocol; it is
  long enough to clear the 1200 s interoception warm-up if a crossing occurs.
- Inspect logs for `welfare.rest_request`, `sleep.sleep.started`,
  `sleep.sleep.completed`, freeze/preservation events, and maintenance-sleep
  lengths.

## Can this run without touching production identity?

**Yes.** The procedure is designed to run without touching production identity
or world-model weights:

- Production `state/` (including `state/identity`, `state/forks`,
  `state/models`, and frozen `state/cycle/control.json`) is never the
  `KAINE_DATA_ROOT` and is not modified. Only a scratch clone's
  `cycle/control.json` is rewritten.
- Identity/world-model files may be present in the clone for read/load access,
  but writes (including any world-model checkpoint update) land only under
  `$SCRATCH/state/`; the production checkpoint under `state/world_model/` is not on
  any resolved write path.
- Models are read, not duplicated: `KAINE_MODELS_DIR` points at the original
  read-only `state/models`; models are excluded from the rsync.
- No committed config or task files are edited; only the gitignored temporary
  operator override is used.
- Cleanup removes the scratch tree after measurement; no production state is left
  altered by the run.

Verification before any write-sensitive command:

- `echo "$KAINE_DATA_ROOT"` must be the scratch path (never empty and never the
  project root).
- Production control remains frozen: inspect `state/cycle/control.json` before
  and after; holder must remain `welfare`.

## Limits carried forward

- There is no flag to force a welfare indicator crossing; whether one occurs
  within the window depends on entity evolution and the 1200 s warm-up.
- With `action = "pause"`, the first crossing after a fresh span freezes the
  clone; further maintenance rests require restarting the procedure.
- A matured completion bound of up to 3600 s unfrozen entity time may require
  more than one wall-clock hour unless entity time is accelerated.