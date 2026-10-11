## Why

Paper A.1 defines the broadcast as carrying the full table of candidate
scores, one score for each candidate of the tick's batch $E_k$. Syneidesis
keys that table by the bus entry id alone. A Redis stream entry id
(`<milliseconds>-<sequence>`) is unique only within its stream, so two
candidates read from different streams that were published in the same
millisecond with the same sequence number share an id. The second score
written overwrites the first: the table loses a candidate, and every reader
that looks up a coalition member's score by its id (`BroadcastContext`,
Volition's report policy, the Nous proposal filter, the faithful renderer,
the workspace-mediation harness) can read the other candidate's score. The
coalition itself is chosen from the scored list, not from the table, so
selection and the inhibition flag are unaffected; per-member access, the
score table in the broadcast and the research log, and the live oscillatory
ablation's top score and candidate count are affected.

## What Changes

- The cycle names each candidate by a stream-qualified key,
  `<stream>:<entry_id>` (for example `soma.out:1760000000000-0`), when it
  gathers the tick's batch. That key is the candidate's id everywhere
  downstream: in `selected_events`, in `salience_scores`, in each coalition
  member's `entry_id` in the broadcast payload, and in an intent's
  `entry_id`. Keys and member ids therefore agree in every arm (competitive,
  matched and pooled) and in both halves of the dual-path selection.
- `kaine.bus.schema` gains `stream_entry_key(stream, entry_id)` and
  `split_stream_entry_key(key)`, which returns `(None, key)` for a bare entry
  id written before this change.
- The canonical within-tick order stays the paper's: source, event type, then
  the bus entry id. The stream is a final tie-break, reached only when one
  source publishes the same type on two streams.
- Syneidesis refuses a candidate list in which two candidates share an id,
  in every arm, so a collision can no longer pass silently.
- Readers are unchanged in code: each looks up a member's score with the
  member's own id, and in any one broadcast or log record the member ids and
  the table's keys have the same form. A research log written before this
  change keys its table by bare entry ids and needs no migration. Its tables
  can be short by one candidate wherever a collision occurred, and that score
  cannot be recovered.
- Docs describe the key; the oscillatory-ablation stimulus comment that
  relied on unique ids across streams is corrected.

## Coordination

PR #478 (tone-analysis-inputs) joins an `audition.emotion` record to a
broadcast member on (source, type, entry_id). Its research-log record must
carry the stream-qualified key, `stream_entry_key(stream, entry_id)`, since
the member's id now has that form.

## Impact

- Specs: `syneidesis` (one added requirement), `cognitive-cycle` (the
  canonical ordering requirement).
- Code: `kaine/bus/schema.py`, `kaine/cycle/engine.py`,
  `kaine/workspace/syneidesis.py`; docs under `docs/08-cognitive-cycle/` and
  `docs/17-research-data/`.
