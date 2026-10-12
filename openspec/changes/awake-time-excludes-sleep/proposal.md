## Why

The paper (§7, A.7) defines awake time as the entity time during which the
being is awake and the cycle is not frozen, accumulated across boots and
persisted with the entity, and one awake-time clock serves every rule that
reads it. In the code every awake-time reader excludes freezes only: the
maturation gate's lived seconds, the individuation ledger, the development
readout's viability hours (whose own docstring says sleep is excluded) and
the stimulus source's colour ramp (which excludes nothing). Sleep sleep counts as awake.

## What Changes

- The cycle keeps one account of time not awake: the union of frozen time and
  Sleep sleep, so a freeze inside a sleep is not subtracted twice. It reads
  sleep from a source the entrypoint sets (Sleep's `is_sleeping`, looked up
  through the registry so a rebuilt Sleep is still read), refreshed on every
  tick and on every pause, resume and query.
- The maturation gate and the individuation ledger subtract that account in
  place of frozen time alone.
- The development readout treats sleep like a freeze: its awake time stops and a
  running probe is aborted, as its docstring already states.
- The stimulus source's colour ramp subtracts the same account, so colour rises with
  awake time.
- Which freezes block maturation is unchanged.

## Capabilities

### Modified Capabilities

- `developmental-stage`: awake time excludes sleep as well as freezes.

## Impact

- `kaine/cycle/engine.py`, `kaine/cycle/__main__.py`,
  `kaine/boot/perception_feed.py`, tests.
- Behaviour: development takes longer in entity time, by the time spent asleep.
