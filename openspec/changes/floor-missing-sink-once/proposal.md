## Why

The eleventh test boot's awake floor logged two warnings a minute, "volume raw_bus_archive / external_utterances path ... is missing, skipping", 956 lines in eight hours. The two sinks are configured but disabled, so their directories never exist. The repetition buries real warnings.

## What Changes

- The awake floor warns once per watched volume when its path is missing, and again only when that changes: the path appears, or disappears after having existed. A volume that stays missing is skipped silently after the first warning.
- The floor's behaviour on a missing volume (skip it) is unchanged.

## Capabilities

### Modified Capabilities

- `sleep`: the awake floor reports a missing volume once per state change.

## Impact

- `kaine/cycle/housekeeping_floor.py`, tests.
- Behaviour: none for the entity.
