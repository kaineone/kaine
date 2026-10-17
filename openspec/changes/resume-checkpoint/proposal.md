## Why

Paper Appendix A.7 states that awake time, $f_{w0}$, the consecutive-pass count, whether the marker was ever true, the pull history "and all module state ($\ell$ included) persist with the entity, checkpointed each entity minute and at shutdown, so a restart neither resets nor repeats them." Today module state is restored only by a revive from a preservation bundle. A plain start of an existing state tree (compose down and up, a crash, or the module-addition study runner resuming an interrupted development step) builds every module fresh. The live test boot of main 3ce0bbfa showed it: the self-rhythm's adapted recovery time $\ell$ (the entrainment learning), the affect drives and their outcome counts, the goal ledger, the interoception forward model, fatigue and expected error all reset on a restart. The study's seed step runs for 14 hours or more and has to survive one.

## What Changes

- The cycle keeps one rolling resume checkpoint of every module's `serialize()` state at `state/lifecycle/checkpoint/checkpoint.json`, beside the stage file. Each write replaces the previous file atomically, so there is exactly one checkpoint. It is written through the process-wide `StateEncryptor` (`[security.state_encryption]`), so it is encrypted at rest like the rest of the entity state, and carries the entity identity.
- It is written after every 60 s of awake entity time (entity time with the cycle neither frozen nor asleep), and once at a clean shutdown (SIGTERM, SIGINT, `control preserve --stop`, the end of the cycle) unless the sleep module is mid-sleep then. No periodic write happens while the cycle is frozen or asleep, so a checkpoint never holds a sleep phase in progress.
- A module whose own store or file is authoritative on a plain start (the self-model module's file, the episodic memory and social cognition stores, the world model's weight checkpoint) is not part of the checkpoint, so a checkpoint up to a minute old can never roll that store back. Bus cursors (interoception, embodiment, sequence) are left out, so a resumed module never replays bus events it already read.
- On a plain start (no `--revive`), after the modules initialise and before the cognitive cycle starts, the cycle restores each checkpointed module through its `deserialize()`, the same call a revive makes for module state. It does so only when the checkpoint's entity id matches the state tree's identity. None of the revive-only side effects happen: no `revived_from`, no developmental files set aside, no identity change. A missing checkpoint is logged at info level; an unreadable, undecryptable, malformed or other-entity checkpoint is ignored with one warning. In both cases the start proceeds with fresh modules, as today. A module absent from the checkpoint starts fresh; a checkpointed module not enabled now is skipped.
- A revive keeps today's behaviour exactly and never reads the checkpoint. Once the revive lands, the cycle immediately replaces any checkpoint in the tree with the revived state (or removes it if that write fails), so a stale checkpoint can never override a revive.
- Decommission backs up and deletes the checkpoint directory with the other entity state.

## Capabilities

### Modified Capabilities

- `entity-preservation`: module state persists across a plain restart through a rolling, encrypted resume checkpoint, and a revive always wins over it.

## Impact

- New `kaine/lifecycle/resume_checkpoint.py`; `kaine/cycle/__main__.py` (restore after module initialisation, a write after a landed revive, a new `_phase_checkpoint`, the shutdown write); `kaine/cycle/boot_context.py`; `kaine/lifecycle/decommission_locations.py`.
- Docs: `docs/06-operation/development.md`, `docs/11-preservation.md`, `docs/15-experiments/ignition-study.md`.
- Tests: new `tests/test_resume_checkpoint.py` and `tests/test_resume_checkpoint_boot.py`; `tests/test_boot_phases.py` gains the new phase.
- Behaviour: a plain restart of an existing entity resumes its module state from at most one entity minute ago instead of starting fresh. Revive, fork and preservation are unchanged. Disk use is bounded to one checkpoint file per state tree.
