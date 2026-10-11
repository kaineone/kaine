## Why

Paper Appendix A.1 defines the age of a module's broadcast context as the
entity time elapsed since the broadcast's publication, read when the module
forms a prediction. `BroadcastContext` measures it from the moment the module
receives the broadcast, and Audition, which receives no entity clock, measures
it on the monotonic wall clock.

## What Changes

- The cycle stamps each broadcast with `published_at`, the entity-clock time
  at publication; `WorkspaceSnapshot` carries it and the module base decodes
  it.
- `BroadcastContext` measures age from `published_at` when the snapshot has
  it, and from receipt otherwise; the age is never negative.
- Audition receives the shared entity clock at boot, like Topos and Soma, and
  its context uses it.

## Capabilities

### Modified Capabilities

- `cognitive-cycle`: the context age is entity time since publication.

## Impact

- `kaine/cycle/types.py`, `kaine/cycle/engine.py`, `kaine/modules/base.py`,
  `kaine/modules/context.py`, `kaine/modules/audition/module.py`,
  `kaine/boot/factories/audition.py`, `kaine/boot/registry.py`, tests.
