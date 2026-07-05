## Context

`AsyncBus.read`/`range` decode each Redis stream entry via `_decode_event`.
That function is total in intent but partial in practice: `float("")` and
`datetime.fromisoformat("")` raise. Consumers (`StreamSubscriberObserver`,
`kaine/evaluation/_base.py:73`) advance their cursor only over entries that
`read` returns; when `read` raises before returning anything, the cursor is
pinned and the consumer re-reads the same poison entry every `poll_interval_s`.

The bus already validates events at publish time (the `event-bus` spec's
"Canonical event schema" requirement rejects missing/out-of-range salience), so
no *new* malformed event can be written. The poison entries are legacy data in
long-lived Redis (the `kaine-redis` container persists across reboots), written
before validation existed or under an older schema.

## Goals / Non-Goals

**Goals:**
- A single malformed stored entry never raises out of `read`/`range`.
- Consumers always advance past a bad entry (no infinite re-read).
- A recovered legacy event gets a safe, non-promoting salience (`0.0`).

**Non-Goals:**
- No relaxation of publish-time validation — `publish` stays strict.
- No Redis data migration or stream trimming (that's an operational choice,
  not a code contract; this change makes the code resilient regardless).
- No change to module code or the evaluation observers; they recover for free.
- Not making every conceivable field infinitely lenient — scope is the
  observed failure (salience) plus a per-entry guard catch-all.

## Decisions

- **Tolerant salience, defaulting to `0.0`.** Empty/unparseable salience decodes
  to `0.0` — the floor of the valid range — so a recovered legacy event is
  never spuriously promoted into the workspace. Alternative (drop the entry
  entirely) was rejected as the primary mechanism because dropping the *last*
  entry in a batch leaves the cursor pinned (nothing to advance to); keeping the
  entry guarantees the cursor moves.
- **Per-entry guard in `read`/`range`.** Wrap `_decode_event` per entry; if it
  still raises (e.g., a malformed timestamp, or an empty required field like
  `type` that fails the Event schema), skip it and continue. Logged at **debug**,
  not warning: a real deployment's persisted Redis held ~thousands of malformed
  legacy entries, and a warning-with-stack-trace per entry flooded the log
  (2.88M lines on one boot).
- **Skipping is not enough — the consumer must advance past skipped entries.**
  A consumer (e.g. `StreamSubscriberObserver`) advances its cursor only over the
  entries `read` returns. A batch made *entirely* of undecodable entries returns
  nothing, so a skip-only cursor never moves and the consumer re-reads the same
  poison batch every poll forever (observed live: 64 entries re-read 147k
  times). Fix: add `AsyncBus.read_entries()` returning
  `(decoded_entries, last_scanned_id)`; the observer advances its cursor to
  `last_scanned_id`, moving past skipped entries too. `read()` delegates to it
  and drops the second value, preserving its signature. Rejected alternative:
  fabricating placeholder Events for undecodable entries (pollutes eval data and
  violates the Event schema's non-empty `source`/`type`).
- **Read tolerant, publish strict — asymmetric by design.** New data is
  guaranteed well-formed at the boundary; old data is handled leniently on the
  way out. This keeps the schema contract intact while surviving historical
  drift.

## Risks / Trade-offs

- [Silently defaulting salience could mask a real publisher bug] → Publishers
  can't emit empty salience (publish validation rejects it), so a `0.0` default
  on read can only come from legacy/out-of-band data; we log when the guard
  drops an entry. Live well-formed events are unaffected.
- [Skipping an entry loses an observation] → Only entries that are otherwise
  undecodable are skipped, and a warning records the entry id; the alternative
  (wedging the whole consumer) is strictly worse.

## Migration Plan

Pure code change, backward compatible. Existing well-formed streams decode
identically (a present, valid salience still parses). The running cycle must be
restarted to load the patched bus client. No data changes; operators may
separately trim legacy entries if they wish, but it's no longer required.

## Open Questions

- Should a future change add a one-shot maintenance command to trim/repair
  legacy stream entries? Out of scope here; the code fix removes the urgency.
