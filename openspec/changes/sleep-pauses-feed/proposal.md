## Why

The paper (§3.5) states that during sleep the cycle keeps running, the
perceptual feed pauses, and all four processors suspend forward-model
adaptation. In the code the sleep module suspends perception (locus `off`, playlist clock
paused under the `sleep` holder) only inside phase 2, and phase 2 returns
before the suspend when the episodic memory module is absent. In the base-thesis profile the episodic memory module is
off, so the seeded feed keeps running through every sleep.

## What Changes

- `Sleep.enter_sleep` suspends perception when the sleep starts and restores
  it in a `finally` when the sleep ends, so the feed pauses for the whole sleep
  whatever modules are active, and is restored on failure or cancellation.
- Phase 2 no longer suspends and restores perception itself.
- During the developmental phase the developmental gate's lock keeps the developmental
  stimulus running (the existing `locked_by = "development"` rule ignores the
  suspend); this change leaves that rule as it is.
- Two test files that still carried an Apache-2.0 header get the project's
  CAL 0.4 header.

## Capabilities

### Modified Capabilities

- `sleep`: sleep pauses the perceptual feed for its whole duration.

## Impact

- `kaine/modules/sleep/module.py`, tests.
- Behaviour: on profiles without the episodic memory module the seeded or playlist feed now pauses
  during sleep, and the seeded stimulus restarts from its first frame after
  each sleep, as it already did on profiles with the episodic memory module.
