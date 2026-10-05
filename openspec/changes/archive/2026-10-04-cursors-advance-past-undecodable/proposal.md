# Every cursor-advancing consumer advances past undecodable entries

## Why

`AsyncBus.read` returns only the entries that decode, and skips any it cannot decode. A consumer that moves its cursor to the last *decoded* id stays where it is when a whole batch fails to decode. It then re-reads that batch on every poll and never sees anything written after it.

The event-bus spec already requires every cursor-advancing consumer to get past such a batch. `read_entries` exists for this: it also returns the id of the last entry scanned.
- The pre-boot correctness batch moved the cognitive cycle, the evaluation sidecar, the preservation monitor, Hypnos and Soma's main loop onto it.
- Twenty-six cursors still advance to the last decoded entry: the peer and intent loops of fourteen modules, gestation's Soma and Topos readers, the Nexus bridge and the remote bridge.

Two consumers that already used `read_entries` misused it:
- **The welfare monitor.** Its distress and gray-zone loops stop at a crossing, and then jumped the cursor to the last scanned id. Under `action = "notify"` the run continues, so the decoded reports and gray-zone events after the crossing entry in that batch (up to 128) never reached the trackers, and the repeat windows undercounted.
- **The Hypnos audit drain.** It stopped at a batch with no decodable entry, even when more entries followed, which delayed them until the next sleep.

For any of the twenty-six, a run of undecodable entries at least one read long silences that input. A Hypnos sleep event would never reach Soma or Topos, an intent would never reach Praxis, and the Nexus diagnostics stream would freeze.

## What changes

- Every cursor-advancing consumer reads with `read_entries`. Each one advances to the last scanned id whenever one is returned, and handles the decoded events exactly as before.
- A batch that only advanced the cursor counts as progress, so a poll loop does not sleep on it.
- Chronos records a user interaction only for a decoded event, never for one it skipped.
- A consumer that stops partway through a batch advances only to the entry it stopped at. The welfare monitor's two loops advance to the last scanned id only when they ran to the end. (The `welfare-monitor-feeds-every-entry` change later made the monitor feed the whole batch each poll, so it no longer stops partway.)
- The Hypnos audit drain stops only when a read scans nothing.
- Nous's `_read_stream` returns the last scanned id along with the entries.
- The Nexus bridge's bus protocol uses `read_entries`.
- A test fails if any code under `kaine/` outside the bus calls `bus.read(`. The exceptions are two one-shot readers that do not advance a cursor: the workspace-mediation inject helper and Nexus's recent-utterances read.

## Impact

- **Behaviour:** none while every entry decodes. When a batch fails to decode, the consumer now moves past it instead of stalling.
- **Welfare net:** under `action = "notify"`, every distress report and gray-zone event now reaches the trackers. Under `pause` and `end` the run stops at the first crossing, as before.
- **Research:** none for recorded data. No study is running. A future run can no longer lose a module's input to a stalled cursor.
