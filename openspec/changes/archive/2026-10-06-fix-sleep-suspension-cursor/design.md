## Context

Redis `XREAD` with the id `$` means "entries newer than the stream's last entry at the moment of this call". Without `BLOCK` the command returns at once, so the result is always empty, and the next call resolves `$` afresh. A consumer that keeps `"$"` until it scans an entry therefore never scans one. `read_entries` returns `None` for the last-scanned id when nothing is read, so the consumer keeps `"$"` forever.

## Decisions

### D1. Refuse, don't resolve, in the bus
`read_entries` could resolve `"$"` to the stream tail itself. But that only moves the bug: a caller that keeps `"$"` (because nothing was scanned) would resolve the tail again on every poll and miss whatever arrived between polls. The cursor has to be resolved once, by the consumer, before it polls. So the bus raises `ValueError` for a non-blocking `"$"` read, which turns a silent stall into a loud error on the first poll.

### D2. Seed at initialize, from one helper
Consumers seed their cursor with `AsyncBus.last_entry_id(stream)` in `initialize`, before their loop task starts. An empty stream gives `"0-0"`, so the first sleep event ever published is seen. Audition's private `_hypnos_tail_cursor` is replaced by the same call, so there is one way to do it.

### D3. Tests on the real bus path
Each fixed consumer gets a test on a fakeredis-backed `AsyncBus`: initialize the module, publish `hypnos.sleep.started`, and the forward model is suspended within a poll; publish `hypnos.sleep.completed`, and it resumes. Each test is mutation-checked by reverting that consumer's seeding. The bus refusal has its own test: non-blocking `"$"` raises for all three read methods, and a blocking read from `"$"` still returns an entry published after it starts.
