## 1. Make event decode tolerant

- [x] 1.1 In `kaine/bus/client.py` `_decode_event`, decode `salience` leniently:
      an empty or unparseable value becomes `0.0` (no raise). Keep valid values
      parsing exactly as before.
- [x] 1.2 Add a per-entry guard in `read()` and `range()`: wrap the
      `_decode_event` call; on failure log and skip that entry, continuing the
      scan. Never let one entry raise out of the batch. (Factored `_decode_entry`,
      used by both read and range. Skip logged at DEBUG, not WARNING — a large
      legacy backlog otherwise floods the log with stack traces every boot.)
- [x] 1.3 Confirm `publish` and its validation are untouched (publishing
      missing/out-of-range salience still rejected). (No change to publish path.)
- [x] 1.4 Cursor advancement past all-undecodable batches: add
      `AsyncBus.read_entries()` returning `(decoded_entries, last_scanned_id)`,
      refactor `read()` to delegate to it, extend the `BusReader` protocol, and
      make `StreamSubscriberObserver._run` advance its cursor to `last_scanned_id`.
      Skipping alone is insufficient — a batch of entirely undecodable entries
      returns no decoded events, so a skip-only consumer's cursor never moves and
      it re-reads the same poison batch forever (observed live: 64 entries
      re-read 147k times). Update fakes (`FakeBus`, `FailingReadBus`).

## 2. Regression tests

- [x] 2.1 Test: `_decode_event` on fields with `salience=""` returns an event
      with `salience == 0.0` and does not raise.
- [x] 2.2 Test: a valid salience still roundtrips exactly (no regression of the
      existing "Float salience roundtrips exactly" behavior).
- [x] 2.3 Test: `read`/`range` over a stream whose first entry has empty
      salience returns all entries (the bad one decoded to 0.0) without raising,
      so the cursor can advance.
- [x] 2.4 Test: an entry that cannot be decoded at all is skipped (omitted from
      results) while the remaining entries are returned.
- [x] 2.5 Test: `read_entries` over a batch of entirely undecodable entries
      returns no decoded events but a non-null `last_scanned_id` equal to the
      last entry's id, so a consumer can advance past the whole poison batch.

## 3. Verify and apply to the live entity

- [x] 3.1 Run the full suite (`.venv/bin/python -m pytest -q`) — all green
      (796 passed, 12 skipped, shipped all-off defaults).
- [x] 3.2 Restart the running cycle so it loads the patched bus client, then
      confirm the evaluation `attribution`/`trajectory` observer warnings stop
      (no new `observer ... read failed` lines accruing) while `tick_index`
      keeps advancing. (Verified: 0 observer warnings; tick_index 44→57; now
      running 9 modules incl. audio_in + topos.)
