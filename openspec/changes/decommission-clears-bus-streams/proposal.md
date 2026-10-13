## Why

Decommission is meant to remove an entity's traffic from the event bus. It
clears Redis keys matching `kaine:*`, but the bus streams are not prefixed:
they are named `<module>.out`, `workspace.broadcast`, `cycle.control`,
`lingua.external` and so on. So a decommission clears no stream, and the
entity's recent content (utterances, percepts, workspace broadcasts) stays on
the bus after the operator was told it was deleted.

A review then found three more faults. Decommission connects without the bus
password (it reads `config["redis"]`, which never holds it), so against the
shipped `requirepass` Redis it clears nothing and reports the authentication errors
as non-fatal notes before saying the state was deleted. It scans the whole
keyspace once per name and deletes whatever matches, of any type. And deleted
entries stay in the Redis append-only file until a rewrite.

## What Changes

- Decommission enumerates the real stream names: every stream in the bus
  registry (`KNOWN_STREAMS`), every stream the evaluation registry lists as
  produced, and `cycle.control`, each also under its old and new module name
  from the rename table, so a bus written before or after the module rename is
  cleared either way.
- It connects through `load_bus_config()`, with the password the cycle uses. A bus
  that cannot be reached or refuses authentication fails the step: the CLI stops
  with exit code 8 before deleting anything, and never reports success.
- It checks each name's `TYPE` and `UNLINK`s only streams, one call per name, with
  no keyspace scan. A listed name that holds another type is reported and kept.
- After deleting, when the append-only file is on, it asks Redis to rewrite it
  (`BGREWRITEAOF`) so the deleted entries leave the on-disk log, and reports the
  status.
- The CLI prints every stream it cleared, a dry run lists only the streams that
  exist, and every real run appends a content-free audit record (what was removed,
  when, the outcome, the backup path) to `state/audit/decommission.jsonl`.
- Tests: an in-memory Redis checks exact-name deletion, type checks and dry runs; a
  real `redis-server` with `requirepass` (skipped when none is installed) checks
  that the authenticated client clears the streams and starts the rewrite and that
  a wrong or missing password fails with nothing deleted; CLI tests check the
  printed streams, the audit record and the failure exit. A test checks that the
  list covers every stream the evaluation registry names as produced, since
  decommission may not import that registry.

## Capabilities

### Modified Capabilities

- `entity-decommission`: decommission clears the entity's bus streams.

## Impact

- `kaine/lifecycle/decommission.py`, `kaine/lifecycle/__main__.py` (exit code 8,
  output, audit record) and the decommission tests. No change to what is backed
  up or to the deletion of state files and memory collections; the wider coverage
  is the separate design `decommission-complete-coverage`.
