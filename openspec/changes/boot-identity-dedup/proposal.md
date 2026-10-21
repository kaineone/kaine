## Why

`kaine/cycle/__main__.py` defines `_resolve_boot_identity` and `_persist_revived_identity` twice, with identical bodies. Python keeps the later definitions, so the earlier copies are dead. A fix applied to the first copy would silently do nothing, as nearly happened in launch-name-at-first-boot.

## What Changes

- The earlier, dead copies of the two functions are removed. Behaviour is unchanged.
- A test parses `kaine/` and fails when a module defines the same top-level function or class name twice. An `if`/`else` that defines one name in each branch does not count.

## Capabilities

### Modified Capabilities

- `architecture-boundaries`: a module defines each top-level name once.

## Impact

- `kaine/cycle/__main__.py`, a new test.
- Behaviour: none.
