## Why

A single malformed entry in a Redis stream wedges every consumer that reads it.
`_decode_event` (`kaine/bus/client.py:50`) does `salience=float(_get("salience"))`,
which raises `ValueError` on an empty string. The exception escapes `read()`
(`client.py:172`), so the whole batch read fails, the consumer's cursor never
advances past the bad entry, and it re-reads the same poison entry every poll
forever. Observed live at first boot: the evaluation sidecar's `attribution`
and `trajectory` observers (both reading `WORKSPACE_STREAM`) emitted 200+
identical warnings within a minute against a legacy entry with empty salience
left in persisted Redis.

Publish-time validation already rejects malformed events, but persisted Redis
predates that validation and contains legacy entries. The read path must
tolerate what publish now forbids, so old data can't wedge a live consumer.

## What Changes

- `_decode_event` SHALL treat an empty or unparseable `salience` as `0.0`
  rather than raising — the salience floor, so a recovered legacy event is
  never spuriously promoted.
- `read()` and `range()` SHALL guard decoding per entry: if an entry still
  fails to decode, it is logged once and skipped, and the scan continues — a
  single malformed stored entry SHALL NOT raise out of a batch read.
- Publish-time validation is **unchanged**: `publish` still rejects events with
  missing/out-of-range salience. Only the read path becomes tolerant of legacy
  stored data.
- Regression tests cover empty-salience decode and a poison entry mid-stream
  not wedging a reader.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `event-bus`: adds a requirement that reading stored entries is resilient to
  malformed/legacy entries (tolerant salience decode + per-entry guard on
  `read`/`range`), while publish-time validation stays strict.

## Impact

- **Code**: `kaine/bus/client.py` — `_decode_event`, `read`, `range`. No change
  to `publish`/validation, module code, or the evaluation observers (they
  recover automatically once reads stop raising).
- **Operational**: the evaluation sidecar's warning flood stops; observers
  advance past legacy entries. Already-running cycle must be restarted to pick
  up the code (it loads the bus client at process start).
- **Tests**: new coverage under `tests/test_bus_client.py` (or sibling).
