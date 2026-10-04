# Every cursor-advancing consumer advances past undecodable entries

## Why

`AsyncBus.read` returns only the entries that decode, and skips any it cannot decode. A consumer that moves its cursor to the last *decoded* id stays where it is when a whole batch fails to decode. It then re-reads that batch on every poll and never sees anything written after it.

The event-bus spec already requires every cursor-advancing consumer to get past such a batch. `read_entries` exists for this: it also returns the id of the last entry scanned.
- The pre-boot correctness batch moved the cognitive cycle, the evaluation sidecar, the preservation monitor, Hypnos and Soma's main loop onto it.
- Twenty-six cursors still advance to the last decoded entry: the peer and intent loops of fourteen modules, gestation's Soma and Topos readers, the Nexus bridge and the remote bridge.

For any of these, a run of undecodable entries at least one read long silences that input. A Hypnos sleep event would never reach Soma or Topos, an intent would never reach Praxis, and the Nexus diagnostics stream would freeze.

## What changes

- Every cursor-advancing consumer reads with `read_entries`. Each one advances to the last scanned id whenever one is returned, and handles the decoded events exactly as before.
- A batch that only advanced the cursor counts as progress, so a poll loop does not sleep on it.
- Chronos records a user interaction only for a decoded event, never for one it skipped.
- Nous's `_read_stream` returns the last scanned id along with the entries.
- The Nexus bridge's bus protocol uses `read_entries`.
- A test fails if any code under `kaine/` outside the bus calls `bus.read(`. The exceptions are two one-shot readers that do not advance a cursor: the workspace-mediation inject helper and Nexus's recent-utterances read.

## Impact

- **Behaviour:** none while every entry decodes. When a batch fails to decode, the consumer now moves past it instead of stalling.
- **Research:** none for recorded data. No study is running. A future run can no longer lose a module's input to a stalled cursor.
