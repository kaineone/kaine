## Why

A `WetwareOscillator` records one firing-fraction sample each time its module publishes, and reads the territory's latest window. KAINE's silicon oscillator records how its population answered that publish's drive. Once the substrate follows KAINE's cycle, the response to a stimulation arrives in the next window. So when a module publishes less often than the cycle ticks, the latest window no longer holds the response to its stimulation, and the sample is background firing. The history then stops reflecting salience, and phase-locking between modules compares noise.

## What Changes

- Each `step` tags its exchange with a step counter, and records the firing fraction of the window that answers the oscillator's own stimulation:
  - before the substrate follows the cycle, the window the step runs, as today;
  - once it follows the cycle, the response to the oscillator's previous step, however many ticks ago that was.
- A response is recorded once. A step that arrives before any response exists, or that would read the same response again, records nothing.
- Steps with zero drive are tagged too, so their sample is the territory's activity after that publish, like the silicon oscillator at zero drive.
- docs/cl1.md notes the one-publish delay.

It uses the broker's tagged exchange from nous-on-wetware, and adds no broker code.

Also fixed here: `test_drive_mode_records_taken_proposal` (added by #251) built its `TerritoryObservation` with only `tag` and `spikes`, so it raised TypeError. No CI job runs the plugin suite, so it merged red. Its stub now builds a complete observation.

## Impact

- Affected spec: `oscillator-wetware-backend` (modified requirement "Module phase can be sourced from the substrate").
- Affected code: `plugins/kaine-cl1/src/kaine_cl1/backends/oscillator.py`, its tests, `docs/cl1.md`.
