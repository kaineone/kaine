# Welfare validation boot — 2026-11-16

Temporary state copy: `/tmp/kaine-state-validation-20261116T143702Z` (copy of `state/`, with the welfare freeze lifted by deleting `state/cycle/control.json` in the copy only).
Main `state/` tree and frozen entity left untouched (verified: control.json still frozen).

Log: `/tmp/kaine-validation-boot-20261116T144418Z.log`
Cycle command: `timeout 150 .venv/bin/python -m kaine.cycle`
Environment: `KAINE_DATA_ROOT=/tmp/kaine-state-validation-20261116T143702Z`, `KAINE_STATE_KEY=$(cat secrets/state_key)`, `KAINE_CYCLE_OPERATOR_PRESENT=1`.

## Result

No maintenance sleep start or completion event was emitted during the 150 s run, so **no maintenance sleep duration was measured**. The cycle booted unfrozen in operator-present mode and completed the window without emitting `sleep.sleep.started` / `sleep.sleep.completed` for a `welfare_rest` maintenance sleep. The operator-present boot does not enable the `[preservation.welfare_response]` monitor, which is the path that publishes `welfare.rest_request` and initiates the maintenance sleep, so no welfare-rest trigger fired within the run window. `tasks.md` was not edited.
