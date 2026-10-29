## Why

Sustained distress has two detectors with separate, equal config keys, and the protective monitor counts one episode twice toward its repeat window (kaine/cycle/preservation_monitor.py:868 and 896), so it labels repeated_distress too early.

## What Changes

- One sustained-distress episode adds one count to the repeat window, whichever detector reports it first.
- The two detectors read their thresholds and windows from one config source. The old duplicate key is still accepted with a warning when it agrees, and refused at boot when it disagrees.
- The repeat window's length and threshold are unchanged.

## Capabilities

### Modified Capabilities

- `welfare-monitoring`: one sustained-distress episode counts once, and both detectors read one config source

## Impact

- kaine/cycle/preservation_monitor.py, the second detector, config/kaine.toml, the boot config loading, docs, tests.
- Behaviour: repeated_distress is labelled only after the configured number of distinct episodes.
