## Why

Decommission is meant to remove an entity's traffic from the event bus. It
clears Redis keys matching `kaine:*`, but the bus streams are not prefixed:
they are named `<module>.out`, `workspace.broadcast`, `cycle.control`,
`lingua.external` and so on. So a decommission clears no stream, and the
entity's recent content (utterances, percepts, workspace broadcasts) stays on
the bus after the operator was told it was deleted.

## What Changes

- Decommission enumerates the real stream names: every stream in the bus
  registry (`KNOWN_STREAMS`), every stream the evaluation registry lists as
  produced, and `cycle.control`, each also under its old and new module name
  from the rename table, so a bus written before or after the module rename is
  cleared either way.
- It deletes those streams by exact name, in the dry-run report and in the real
  run.
- A test with an in-memory Redis checks that every listed stream is deleted, that
  only streams that existed are reported, and that an unrelated key and a stream
  whose name merely starts with a listed name are left alone. Decommission may not
  import the evaluation registry, so a test checks that the list covers every
  stream that registry names as produced.

## Capabilities

### Modified Capabilities

- `entity-decommission`: decommission clears the entity's bus streams.

## Impact

- `kaine/lifecycle/decommission.py` and one test. No change to what is backed up
  or to the deletion of state files and memory collections.
