## 1. Change
- [x] 1.1 `DivergenceMonitor.__init__` accepts the two thresholds and `_poll_once` passes them to `assess_divergence`.
- [x] 1.2 `kaine/cycle/__main__.py` passes `consolidation_thresholds_from_config(kaine_config)` to the monitor.

## 2. Tests
- [x] 2.1 With a consolidation record at rate 0.3 and thresholds (0.2, 0.25), the monitor's assessment is diverged; with the defaults it is not.
- [x] 2.2 The composition root passes the configured values (unit test on the wiring helper or the constructor call).
- [x] 2.3 Mutation-check: dropping the pass-through fails 2.1.

## 3. Docs
- [x] 3.1 Preservation chapter and configuration appendix.
