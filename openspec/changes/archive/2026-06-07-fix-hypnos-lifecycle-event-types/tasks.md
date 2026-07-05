## 1. Correct the consumers

- [x] 1.1 `kaine/evaluation/sleep_snapshots.py`: `hypnos.began_rest` →
      `hypnos.sleep.started`, `hypnos.ended_rest` → `hypnos.sleep.completed`
      (+ update the docstring/comments).
- [x] 1.2 `kaine/evaluation/voice_tracking.py`: `hypnos.cycle_complete` →
      `hypnos.sleep.completed`.
- [x] 1.3 `kaine/nexus/conversation.py`: `hypnos.began_rest` →
      `hypnos.sleep.started`, `hypnos.ended_rest` → `hypnos.sleep.completed`.

## 2. Tests

- [x] 2.1 Correct the wrong-type literals in `tests/test_evaluation_observers.py`
      (sleep_snapshots + voice_tracking) to the canonical types — these become
      the regression guard.
- [x] 2.2 Add a conversation test: `hypnos.sleep.started` → sleeping,
      `hypnos.sleep.completed` → awake.

## 3. Verify

- [x] 3.1 Full suite green — no skips/xfails added.
- [x] 3.2 `openspec validate "fix-hypnos-lifecycle-event-types"` passes.
