## Why

When Lingua fails to realize a `speak` or `think` intent (the language-organ request raises), it is meant to emit a content-free `realization_failed` audit record on `lingua.internal`. Hypnos's sleep-time ignition audit reads `lingua.internal` and counts these records separately from realized speech. The emission calls `self._publish(...)`, a method that does not exist on `Lingua` or `BaseModule`. The resulting `AttributeError` is swallowed by the surrounding `except Exception: log.debug(...)`, so the record has never been written, the audit's `realization_failed_count` is always zero, and failed realizations are invisible in research logs. No test exercises the failure path.

## What Changes

- Lingua writes `realization_failed` to `lingua.internal` using the same record format as its utterances (`source`, `type`, `salience`, `timestamp`, `causal_parent`, JSON `payload`), through one shared helper that both utterances and the failure record use.
- The payload stays content-free: `mode` (the intent kind) and `reason_class` (the exception class name) only — never the prompt, text or exception message.
- A failure during that emission is logged at WARNING, not DEBUG, so a broken audit path is visible.
- Tests inject a failing chat client and assert the record lands on `lingua.internal` with exactly the content-free fields, and that Hypnos's `classify_realizations` counts it.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `lingua`: add a requirement for the content-free realization-failure audit record.

## Impact

- `kaine/modules/lingua/module.py`
- `tests/test_lingua_module.py`
- No config, schema or stream changes; no entity boot needed.
