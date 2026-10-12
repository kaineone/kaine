## Why

The paper (§3.3, §4) says that with the episodic memory module present the consolidation phases of
the sleep module have material to work on, and that sleep combines the replay of
selectively strengthened traces (Wilson and McNaughton 1994; Wei et al. 2016)
with synaptic downscaling. In the code, phase 1 moves every short-term entry
into the episodic store, and phase 2's `replay_now()` then builds its
candidates from the short-term buffer alone. By the time phase 2 runs the
buffer is empty, so a sleep replays nothing. The episodic memory module page records
this as a known gap. The episodic memory module is held, so the base-thesis form is unaffected.

## What Changes

- `MnemosCore.consolidate_now()` keeps the batch it moved in this pass, each
  entry with the episodic point id it was stored under. Each pass replaces the
  previous batch, so a later sleep never replays an earlier sleep's traces.
- `Mnemos.replay_now()` adds that batch to its candidates, with the episodic
  point id as the replayed `memory_id`. Selection, the window guard and
  redaction are unchanged.
- The episodic memory module drops the batch when it sees `hypnos.sleep.completed`, so the batch
  lives only for the sleep that made it. A preservation import drops it too.
- When a `mnemos.replay` event is a member of a stored broadcast, the episodic memory module
  records it as `<replay of {memory_id}>` without the replayed text. Storing
  the text would nest the old trace inside the new one on every sleep, now
  that replay publishes events.
- The phase order, the perception suspension for the whole sleep, and the
  phase metadata keys are unchanged.

## Capabilities

### Modified Capabilities

- `mnemos-replay`: replay in a sleep draws on the traces that sleep's
  consolidation moved.

## Impact

- `kaine/modules/mnemos/memory.py`, `kaine/modules/mnemos/module.py`,
  `kaine/modules/hypnos/phases.py` (docstrings), tests, and the episodic memory module and
  sleep pages of the book.
- Behaviour: only with the episodic memory module enabled. Phase 2 now publishes up to
  `selection_top_k` `mnemos.replay` events per sleep.
