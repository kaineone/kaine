## 1. Streams

- [x] 1.1 Enumerate the entity's stream names from the bus and evaluation registries, with old and new module names
- [x] 1.2 Delete them by exact name in the dry run and the real run
- [x] 1.3 Test with an in-memory Redis that listed streams go and unrelated keys stay

## 2. Review fixes

- [x] 2.1 Connect through `load_bus_config()`; an unreachable or refusing bus fails the step and the CLI deletes nothing (exit 8)
- [x] 2.2 Check `TYPE` and `UNLINK` only streams, one name at a time, with no keyspace scan
- [x] 2.3 Request `BGREWRITEAOF` after deletion when the append-only file is on, and report its status
- [x] 2.4 Print the cleared streams, list only existing streams in a dry run, and write a content-free audit record
- [x] 2.5 Test against a real `redis-server` with `requirepass` (skipped when none is installed) and through the CLI
