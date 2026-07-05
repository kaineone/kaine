## 1. Package + state

- [ ] 1.1 Add `kaine.modules.hypnos` to setuptools packages
- [ ] 1.2 Add `[project.optional-dependencies]` `training = ["unsloth>=2024.0"]` (loose pin) for the real DPO trainer

## 2. Scheduler

- [ ] 2.1 Implement `kaine/modules/hypnos/scheduler.py` with `RestScheduler`, `is_due`, `try_defer`, `mark_completed`
- [ ] 2.2 Tests for deferral within window, rejection past window, mark_completed resets schedule

## 3. Phases

- [ ] 3.1 Implement `kaine/modules/hypnos/phases.py` with `PhaseResult` dataclass + async functions `consolidate_memory`, `revise_beliefs`, `reset_affect`, `recalibrate_time`. Each takes the relevant collaborator and a config; each handles exceptions internally.
- [ ] 3.2 Tests for each phase using fake collaborators; one-phase-fails-but-others-still-run path

## 4. Voice alignment

- [ ] 4.1 Implement `kaine/modules/hypnos/voice_alignment.py` with `DPOPair` dataclass, `DPOPairBuilder` (reads JSONL, filters), `Trainer` protocol, `TrainingResult`, `FakeTrainer` (always rejects), `UnslothDPOTrainer` skeleton (lazy import, optional)
- [ ] 4.2 Tests: builder filters empty fields; chosen=faithful_rendering; FakeTrainer integration; capability-loss veto path

## 5. Module

- [ ] 5.1 Implement `kaine/modules/hypnos/module.py` with `Hypnos(BaseModule)`. `enter_sleep()` runs the five phases under an asyncio.Lock; HypnosBusyError on concurrent calls. Publishes hypnos.sleep.started and hypnos.sleep.completed
- [ ] 5.2 Update `kaine/modules/__init__.py` exports

## 6. Config

- [ ] 6.1 Add `[hypnos]` + `[hypnos.voice_alignment]` blocks to `config/kaine.toml`
- [ ] 6.2 Add `hypnos = false` under `[modules]`

## 7. Module tests

- [ ] 7.1 `tests/test_hypnos_module.py`: enter_sleep runs all five phases in order; partial-phase-failure path; concurrent-rejected; sleep.started/completed events; voice alignment rejection path

## 8. Verification + tag

- [ ] 8.1 Full unit suite passes
- [ ] 8.2 `openspec validate hypnos --strict` clean
- [ ] 8.3 Commit, merge, archive change, drop branch
- [ ] 8.4 Tag `v0.6-maintenance`
