## 1. Cycle changes

- [ ] 1.1 Add an internal `_cycle_control_loop()` background task to `CognitiveCycle.run_forever` (and started by `initialize`-equivalent path) that reads `cycle.control` events and applies them.
- [ ] 1.2 Apply rate updates; publish a `cycle.rates` event to `cycle.out` after each successful update.

## 2. Tests

- [ ] 2.1 `tests/test_cycle_runtime_control.py`: bus-driven rate change, invalid rate rejected, ratio fidelity at 3:1, 7:3, 100:1.

## 3. Verification

- [ ] 3.1 Full suite passes
- [ ] 3.2 `openspec validate variable-speed-cognition --strict` clean
- [ ] 3.3 Commit, merge, archive change
