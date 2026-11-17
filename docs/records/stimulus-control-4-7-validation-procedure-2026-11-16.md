# Stimulus-control task 4.7 validation procedure (supervised boot)

Date: 2026-11-16. Docs only. No source, config, branch, run, or experiment
changes were made while producing this file, and no commands were executed.

This is the pre-execution procedure for OpenSpec task `4.7` in
`openspec/changes/stimulus-control-act/tasks.md`:

> One supervised validation boot on a branch before the join.

It covers three things before any boot is started: the act-intent wiring test
pass that must be green first, the operator configuration that temporarily
enables stimulus control, and the exact supervised-boot command sequence. It
does **not** perform the boot; the run itself is reported in a later dated
record under `docs/records/`.

Sources:
- `openspec/changes/stimulus-control-act/tasks.md` (task 4.7)
- `openspec/changes/stimulus-control-act/design.md` (D1-D7, migration and
  ordering)
- `openspec/changes/stimulus-control-act/specs/action-selection/spec.md`
- `docs/records/welfare-indicator-validation-boot-2026-11-16.md`
- `docs/records/welfare-response-trigger-investigation-2026-11-16.md`
- `config/kaine.toml` (`[stimulus_control]`, ships `enabled = false`)
- `config/kaine.operator.toml` (operator overlay, gitignored)

## 1. Ground rules

- No committed file is edited by this procedure. `config/kaine.toml` stays at
  `enabled = false` so off-equals-absent holds.
- Stimulus control is enabled only through the gitignored operator overlay
  `config/kaine.operator.toml`, which already pins `[stimulus_control]
  enabled = true`, `[effectors] enabled_effectors = ["stimulus"]`, and
  `[preservation.welfare_response] enabled = true`. Those three are mandatory
  and are refused at boot without all three.
- The run is operator-supervised (`KAINE_CYCLE_OPERATOR_PRESENT=1`). It is not
  a research-mode run, and no study (`KAINE_STUDY`) is set.
- The workspace-mediation and workspace-feedback arms refuse stimulus control,
  so their study configs must not be selected for this boot.
- Distinct run only: do not reuse seeds, run ids, or state from any
  validation boot recorded earlier.
- If anything below fails, stop and record the failure in a follow-up record.
  Do not join stimulus control into the development run until this boot
  completes and is reviewed.

## 2. Branch and baseline

```
set -eu
REPO=/var/home/erik/Projects/kaineone/kaine
cd "$REPO"

# Operator confirms the starting commit first; record it in the later run record.
git status --short
# git switch -c feat/stimulus-control-validation-boot-2026-11-16

# Disk baseline before a run (documented guardrail).
df -h /var/home/erik
du -sh data/evaluation 2>/dev/null || true

# Confirm no pinned local model collides with KAINE GPU use.
ollama ps 2>/dev/null || true

# Committed config must still be disabled.
grep -n '^enabled = false' config/kaine.toml >/dev/null
git diff --quiet -- config/kaine.toml

# Operator overlay must enable all three required surfaces.
grep -A1 '^\[stimulus_control\]' config/kaine.operator.toml
grep -A1 '^\[preservation.welfare_response\]' config/kaine.operator.toml
grep -n 'enabled_effectors' config/kaine.operator.toml
```

## 3. Act-intent wiring tests (must pass before the boot)

These cover the signed-intent path that stage M and the stimulus effector use:
signed act intents name the stimulus effector, provenance verification,
ready/interval gating, off-equals-absent identity, credit-window opening, and
the boot-wiring of the stimulus source. Run them alone first; they are fast and
they are the gate for task 4.7.

```
set -eu
cd "$REPO"

.venv/bin/python -m pytest -q \
  tests/test_intent_signing.py \
  tests/test_effector_stimulus.py \
  tests/test_stimulus_stage_m.py \
  tests/test_affect_stimulus_credit.py \
  tests/test_stimulus_disabled_identity.py \
  tests/test_stimulus_off_in_mediation_arms.py \
  tests/test_stimulus_source_boot_wiring.py \
  tests/test_stimulus_source_presence_wiring.py
```

Expected: exit status `0`. If any test fails, do not proceed to the boot;
fix the wiring on the branch first and update the test record.

Optional but recommended cross-checks (kept separate so a failure is
attributable):

```
set -eu
cd "$REPO"

# Signed-intent path through the effectors module.
.venv/bin/python -m pytest -q tests/test_effectors_module.py tests/test_action_selection.py

# Bounded pausing and first-hours stop criterion.
.venv/bin/python -m pytest -q tests/test_stimulus_pause_bound.py tests/test_stimulus_first_hours_stop.py

# Real feed follow-a-jump and programme-clock paths.
.venv/bin/python -m pytest -q tests/test_stimulus_programme_clock.py tests/test_stimulus_feed_real.py
```

Spec validation (read-only):

```
set -eu
cd "$REPO"
openspec validate stimulus-control-act --strict
```

## 4. Supervised validation boot

Prerequisites for the overlay (checked in section 2):

- `[stimulus_control].enabled = true`, `stage = "minimal"`
- `[effectors].enabled_effectors` contains `"stimulus"`
- `[preservation.welfare_response].enabled = true` (welfare indicator response
  is the monitor that permits stimulus control to boot)
- no `KAINE_STUDY` value set

Run (time-bounded, operator supervised; exit code `124` from `timeout` is the
intended end, as in the welfare-indicator validation boot):

```
set -eu
REPO=/var/home/erik/Projects/kaineone/kaine
cd "$REPO"

# Scratch clone is optional; use it when the run must not touch production state.
# export KAINE_DATA_ROOT="$REPO/.scratch/stimulus-validation-$(date -u +%Y%m%dT%H%M%SZ)"
# mkdir -p "$KAINE_DATA_ROOT"
# cp -a state "$KAINE_DATA_ROOT/state"   # never copy state/models or state/forks into an overlay of unknown provenance without review

export KAINE_STATE_KEY="$(cat secrets/state_key)"
export KAINE_CYCLE_OPERATOR_PRESENT=1

timeout 180 env KAINE_STATE_KEY="$KAINE_STATE_KEY" \
  KAINE_CYCLE_OPERATOR_PRESENT=1 \
  .venv/bin/python -m kaine.cycle > /tmp/kaine-stimulus-validation-boot.log 2>&1

# timeout returns 124 when it stops the supervised run; that is expected.
echo "exit_status=$?"
```

Log triage commands (run after the boot stops):

```
REPO=/var/home/erik/Projects/kaineone/kaine
LOG=/tmp/kaine-stimulus-validation-boot.log
wc -l -c "$LOG"
grep -n "stimulus" "$LOG" | head -80
grep -nE "refus|Refused|registered module|effector|act:|effectors.action|stimulus_control" "$LOG" | head -120
```

Expected observations for a valid supervised boot with stimulus control on:

- The boot completes past perception-feed construction and registers the
  stimulus effector only because the whitelist names it.
- No stimulus-control refusal (exit code dedicated to that refusal). If the boot
  refuses, the log names the cause: workspace-mediation arm, welfare response
  off, or invalid `[stimulus_control]` section.
- The welfare log / run manifest carries a `stimulus_control` entry with
  `stage = "minimal"` and the configured bounds (`min_interval_s`,
  `seeks_per_awake_hour`, `pause_max_s`, `pause_share_max`, `gain_step_db`,
  `gain_max_db`, channels).
- The entity reaches the run with the stimulus-control runtime present but does
  not itself demonstrate an act within the 180 s window; an act (stage M,
  triggered by a boredom or restlessness drive event after maturation) may or
  may not fire in that window and is not required for this structural check.

## 5. Completion criteria for task 4.7

A supervised validation boot counts as completing task 4.7 only when all of
the following hold:

- [ ] All commands in section 3 exit `0`.
- [ ] Committed `config/kaine.toml` remains `enabled = false` and its working
      tree diff is empty.
- [ ] The boot in section 4 runs operator-supervised and does not refuse
      stimulus control.
- [ ] A run record is appended (dated, under `docs/records/`) with the log
      stats, relevant log lines, run id, manifest stimulus_control entry, and
      the starting commit SHA.
- [ ] No other OpenSpec task is marked complete by this run; in particular,
      task 5.x (development-run join) remains blocked on
      `development-run` and is not advanced here.
- [ ] `tests/test_stimulus_disabled_identity.py` still passes after the branch
      work (off-equals-absent preserved).

## 6. After this procedure

- Open the PR from
  `feat/stimulus-control-validation-boot-2026-11-16` against the validation
  base, with this record and the run record attached.
- Adversarial review before merge (welfare-high-risk). The stimulus-control
  component changes the entity's experience directly; an independent second
  review is required.
- On merge, update `openspec/changes/stimulus-control-act/tasks.md` to mark
  `4.7` complete and record the validation boot's run id in the change's
  progress. The `5.x` join tasks remain gated on `development-run`.
- Add a MemoryGraph note with the run id, boot log path, and the commit SHA so
  the result survives compaction.
