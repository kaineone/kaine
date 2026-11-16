# Welfare 6.5 blocker summary — 2026-11-16

Scope: blocker status for OpenSpec task 6.5 of
`openspec/changes/welfare-indicator-response` ("At the validation boot, record the
length of every maintenance sleep, to check the matured completion bound against
them"). No task checkboxes were edited.

## Source records combined

- `docs/records/welfare-freeze-review-2026-11-16.md`
- `docs/records/welfare-validation-boot-2026-11-16.md`
- `docs/records/welfare-validation-clean-run-2026-11-16.md`
- `docs/records/state-root-validation-guide-2026-11-16.md`

## Observed state

### Prior production freeze

- Freeze timestamp 2026-11-16 13:57:28,700.
- Indicator `boredom_deprived` crossed at 13:47:26,202 and requested a
  maintenance rest.
- Preservation ID `bab6cfe409d44804` (`reason=welfare`), with follow-up
  `indicator_boredom_deprived crossing → preserved (...) + pause`.
- The entity remains frozen at boot with `source=welfare`; the freeze persists
  across boots. Production `state/cycle/control.json` is still frozen.

### 150-second operator-present validation boot

- Lifted the welfare freeze **only** in a scratch state copy
  (`/tmp/kaine-state-validation-20261116T143702Z`) by deleting `control.json`
  in the copy only.
- Boot completed unfrozen in operator-present mode, but no maintenance sleep
  started or completed.
- Reason recorded by that run: the operator-present boot does not enable the
  `[preservation.welfare_response]` monitor, which is the path that publishes
  `welfare.rest_request` and initiates the maintenance sleep.

### 120-second clean scratch run

- Scratch root `/tmp/kaine-scratch-validation-20261116b`, models excluded and
  read from the original `state/models`.
- Freeze lifted only in the clone, verified by `Lifted: welfare; still frozen
  by: none`.
- No freezes, no `welfare net` rest requests, and no `sleep.sleep.*` events.
- Interoception developmental warm-up was active (`min_samples=1000`,
  `min_seconds=1200`), withholding allostatic actions, so no welfare-driven
  `welfare_rest` sleep could trigger within the window.

## Why 6.5 cannot currently be measured

1. **Production state is frozen.** The `welfare` freeze on
   `state/cycle/control.json` prevents the entity from running its cycle, and no
   maintenance sleep can start or complete while frozen. The freeze cannot be
   cleared in production.
2. **Operator-present mode keeps the welfare response dormant.** The shipped
   config has `[preservation.welfare_response].enabled = false` ("SHIPS
   DISABLED"), and `KAINE_CYCLE_OPERATOR_PRESENT=1` does not enable it; it only
   satisfies the boot requirement. The outer response must be enabled
   explicitly through an operator override before any indicator can request a
   rest.
3. **Warm-up withholding.** Even with the response enabled, the developmental
   interoception warm-up withholds allostatic actions until its sample and
   second thresholds pass, so a short window cannot produce a crossing.
4. **Completion bound.** The matured completion bound is configured at
   `rest_complete_matured_s = 3600.0` (`config/kaine.toml`,
   `[preservation.welfare_response.indicators].rest_complete_timeout_s.matured`).
   No maintenance sleep ran long enough to violate or satisfy it. The
   developmental bound is smaller (`[sleep].developmental_rest_s + 300`,
   1710 s), but the 90-150 second validation windows never allowed a sleep to
   start.
5. **Possible re-freeze.** If a crossing occurs, the response preserves the
   entity and applies `action = "pause"`; a new welfare freeze would again block
   further measurement unless the cycle is restarted from a clean clone.

No task checkbox was edited. Task 6.5 therefore remains `[ ]`.

## Minimum clean experiment protocol

Goal: measure at least one maintenance-sleep completion, including its length,
without modifying production `state/`, without enabling the welfare response in
committed configuration, and without unauditably overriding the production
freeze.

### Preconditions

- Work from `/var/home/erik/Projects/kaineone/kaine`.
- Verify free disk space before work:
  `df -h /var/home/erik/Projects/kaineone/kaine`.
- Keep the original `state/models` read-only and out of the copy.
- Do not run the override against production `state/`.

### 1. Scratch copy plus models redirect

```bash
export KAINE_STATE_KEY="$(cat secrets/state_key)"
SCRATCH=/home/erik/.claude/scratchpad/kaine-6-5-2026-11-16
rm -rf "$SCRATCH" && mkdir -p "$SCRATCH"
rsync -a --exclude='models' state/ "$SCRATCH/state/"
```

### 2. Operator override (temporary, gitignored)

Back up any existing `config/kaine.operator.toml`, then create a temporary
override that enables the welfare response only for this run. Do not edit
`config/kaine.toml`.

```bash
cp -a config/kaine.operator.toml "$SCRATCH/kaine.operator.toml.bak" 2>/dev/null || true
cat > config/kaine.operator.toml <<'TOML'
[preservation.welfare_response]
enabled = true

[preservation.welfare_response.indicators]
enabled = true
TOML
```

### 3. Lift the welfare freeze only in the clone

```bash
KAINE_DATA_ROOT="$SCRATCH" \
KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
KAINE_STATE_KEY="$KAINE_STATE_KEY" \
.venv/bin/python -m kaine.cycle.control override welfare
```

Expected output: `Lifted: welfare; still frozen by: none`.
Verify production freeze remains:
`cat state/cycle/control.json` should still report `welfare`.

### 4. 60-minute instrumented run

Run for a full 60-minute (3600 s) wall window so at least one maintenance
sleep can cross warm-up and complete its developmental or matured bound.

```bash
timeout 3600 env \
  KAINE_DATA_ROOT="$SCRATCH" \
  KAINE_MODELS_DIR=/var/home/erik/Projects/kaineone/kaine/state/models \
  KAINE_STATE_KEY="$KAINE_STATE_KEY" \
  KAINE_CYCLE_OPERATOR_PRESENT=1 \
  .venv/bin/python -m kaine.cycle > /tmp/kaine-6-5-run.log 2>&1
```

### 5. Inspect results

```bash
grep -c "freeze" /tmp/kaine-6-5-run.log
grep -c -i "welfare net" /tmp/kaine-6-5-run.log
grep -n "sleep.sleep.started\|sleep.sleep.completed" /tmp/kaine-6-5-run.log
grep -n "welfare_rest" /tmp/kaine-6-5-run.log
```

Record every `sleep.sleep.started` / `sleep.sleep.completed` pair whose trigger
is `welfare_rest`, including its duration, and check those durations against
the configured matured bound (3600.0) and the developmental bound
(`[sleep].developmental_rest_s + 300`). The log is the measurement artifact
for task 6.5.

### 6. Teardown and verification

```bash
rm -rf "$SCRATCH"
if [ -f "$SCRATCH/kaine.operator.toml.bak" ]; then
  mv "$SCRATCH/kaine.operator.toml.bak" config/kaine.operator.toml
else
  rm -f config/kaine.operator.toml
fi
```

Then verify:
- `git status --short` shows no changes to `config/kaine.toml`,
  `openspec/changes/welfare-indicator-response/tasks.md`, or any
  `openspec/changes/*/tasks.md`.
- `cat state/cycle/control.json` still shows the production welfare freeze.
- `git status --short config/kaine.operator.toml` reports no tracked change
  (`config/kaine.operator.toml` is gitignored).

### Notes

- If a welfare crossing triggers `action = "pause"`, the entity will freeze in
  the clone and further maintenance sleeps will not start until that clone is
  restarted through the same procedure.
- The production tree remains untouched throughout; the override, freeze lift,
  and any inferred world-model update occur only under `$SCRATCH`.
- Enabling the welfare response only through the temporary operator override keeps
  the shipped "SHIPS DISABLED" policy intact and does not edit tasks or source.
