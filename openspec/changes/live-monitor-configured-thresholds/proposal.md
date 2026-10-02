# The live preservation monitor uses the configured divergence thresholds

## Why
`assess_divergence()` marks organ-level divergence when the latest consolidation `divergence_rate` or `divergence_magnitude` crosses its threshold. The thresholds are configured in `[hypnos.voice_alignment]` (`consolidation_divergence_rate_threshold`, `consolidation_divergence_magnitude_threshold`). The decommission CLI reads them; the live `DivergenceMonitor` calls `assess_divergence()` without them, so it always uses the built-in 0.5 and 0.25. An operator who sets different thresholds gets two different answers to "has this entity diverged?", which the `divergence-assessment` spec forbids ("the two consumers cannot disagree"). The operator decided (2026-10-02) that the live monitor uses the configured thresholds.

Research impact: none with the shipped values or the current operator configuration, which do not set the keys (both equal the built-in defaults). Where an install sets different thresholds, preservation now triggers on the same divergence decommission sees; record that as a protocol change between studies.

## What changes
- `DivergenceMonitor` takes `consolidation_rate_threshold` and `consolidation_magnitude_threshold` (defaulting to the built-in values) and passes them to every `assess_divergence()` call.
- The cycle composition root reads them with the same `consolidation_thresholds_from_config(kaine_config)` the decommission CLI uses and passes them to the monitor.

## Impact
- Code: `kaine/cycle/preservation_monitor.py`, `kaine/cycle/__main__.py`.
- Specs: `divergence-assessment` (ADDED).
- Docs: the preservation chapter and the configuration appendix stop saying the live monitor uses fixed thresholds.
