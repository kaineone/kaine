## Why

The sleep module's sleep index lived only in memory, so it started at 0 after every restart. It tags `sleep.consolidation_divergence` and `sleep.ignition_audit` and names the intent-log corpus files (`sleep-<UTC time>-<index>.jsonl`). In the tenth test boot the indices ran 1 to 4, and after the restart 1 to 4 again, so two sleeps shared each index and the corpus names repeated their index. Two persisted records already hold the count: the module's resume-checkpoint state and the cumulative `sleep_count` in `state/lifecycle/stage.json`.

## What Changes

- The sleep module's `serialize()` carries `sleep_index`, and `deserialize()` restores it, so the rolling resume checkpoint, preservation and revive keep it.
- `initialize()` reads `stage.json` and raises the index to its `sleep_count` when that is larger.
- The larger of the two records wins, whichever is restored first. A malformed value is ignored with a warning, and a missing or unreadable stage file leaves the count as it is.
- Nothing that reads `sleep_index` changes its behaviour. The maturation gate keeps counting sleeps from `stage.json` on its own.

## Capabilities

### Modified Capabilities

- `sleep`: the sleep index survives a restart.

## Impact

- `kaine/modules/sleep/module.py`, `kaine/modules/sleep/corpus.py` (docstring), `docs/09-modules/sleep.md`, new `tests/test_sleep_index_restored.py`.
- Behaviour: none for the entity. After a restart the sleep events and corpus file names continue the count instead of repeating it.
