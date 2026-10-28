## Why

The 12th test boot (2026-10-27) stopped a state-cycle rest about 710 s in. After a process restart the log showed "sleep index resumes at 2", then a fresh "state cycle awake time reached, starting a rest" with a full 1410 s. No "sleep: resuming a state-cycle rest after a restart" line appeared, so the entity rested 710 s and then 1410 s. The sleep spec (developmental-state-cycle, "The state cycle survives a restart") requires the rest to resume for its remaining time.

The supervisor's in-process restart carries the rest. A process restart reads the resume checkpoint, and that checkpoint never holds a rest: `write_final` and the periodic loop write nothing while the cycle is asleep or frozen, so the sleep module's `state_cycle` entry there is always phase `awake`. The resting phase never reaches `_restore_state_cycle`.

## What Changes

- Module state is still checkpointed only while awake, so no other module's entry ever holds possibly inconsistent mid-sleep state.
- While a `state_cycle` rest runs, the checkpointer replaces only the sleep module's `state_cycle` entry inside the existing last-awake checkpoint, with phase `resting` and the entity rest time spent so far (frozen time excluded). It does so when the rest starts, after every 60 s of rest, and at a shutdown during the rest. When the rest ends, the entry becomes phase `awake` with `awake_s` 0, so a crash just after a rest does not resume a finished rest.
- The update uses the same atomic encrypted replace, the same entity check and the same revive-record rule as a normal write. With no usable checkpoint it writes nothing. A backstop or other non-`state_cycle` sleep leaves the checkpoint as it is today.
- Wiring: `ResumeCheckpointer` takes an optional `rest_source` (the sleep module's `state_cycle_progress()`, read through the registry) and checks it on its existing 1 s poll, so the sleep module needs no new hooks into its rest loop.

## Capabilities

### Modified Capabilities

- `sleep`: a rest cut by a process restart resumes for its remaining time.
- `entity-preservation`: the resume checkpoint's sleep-in-progress rule gains the one `state_cycle` entry exception.

## Impact

- **Code:** `kaine/lifecycle/resume_checkpoint.py`, `kaine/modules/sleep/module.py` (one accessor), `kaine/cycle/__main__.py` (wiring).
- **Docs:** `docs/06-operation/development.md`.
- **Tests:** `tests/test_rest_resume_process_restart.py`.
- **Preserved entities:** checkpoints written before this change load unchanged.

## Ordering

The sleep delta modifies the requirement "The state cycle survives a restart", which exists in `openspec/specs/sleep/spec.md` only once developmental-state-cycle is archived. This change archives after developmental-state-cycle.
