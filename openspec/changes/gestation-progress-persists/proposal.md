## Why

A gestation runs for many hours of awake time (the budget is 96 hours), so it spans restarts. The pre-conference audit of 2026-10-10 found that the gestation readout keeps its awake-time clock, its count of consecutive passing withdrawals, its history of frequency pull, and whether the marker was ever met only in memory: each boot starts them at zero. After a restart the viability watch can fire again at its six-hour rule, its deadline starts over, and three consecutive passes can never accumulate across a restart. The verdict file is written but never read back. The revised paper (§7, Appendix A.7) states that these quantities persist with the being's state.

## What Changes

- The readout saves its progress to `gestation_progress.json` beside its readout file: awake seconds, consecutive passes, the frequency-pull history, whether the marker was ever met, and the viability verdict, keyed by the same seed and self-rhythm identity as the stored baseline.
- On construction it restores that progress when the key matches, and ignores it (with a log line) otherwise.
- It saves after every scored withdrawal and every 60 seconds of awake time.

## Capabilities

### Modified Capabilities

- `gestational-stimulus`: gestation progress persists across restarts.

## Impact

- **Code:** `kaine/cycle/gestation.py`.
- **Behaviour:** a gestation continues where it left off after a restart.
