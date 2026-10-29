## Why

The eleventh test boot's log shows "self-model assigned launch name" lines for Seabrink, Ghostly, Torrent and Peridot, while the entity is "Kaine Whipple". They come from the preflight's throwaway self-model instances, but they read as if the entity had been renamed four times.

## What Changes

- A self-model built for the preflight does not log a launch-name assignment as if it were the entity's. Its log line, if any, is labelled as a preflight check and names no surname.
- The entity's own self-model keeps its log line, which now says whether the name was adopted from the identity or minted.

## Capabilities

### Modified Capabilities

- `self-model`: preflight instances do not report launch names.

## Impact

- `kaine/modules/self_model/module.py`, `kaine/cycle/preflight.py` (or wherever the preflight builds modules), tests.
- Behaviour: none for the entity.
