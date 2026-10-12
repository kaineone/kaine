## Why

The paper (§3.5, the sleep module) lists the consolidation phases as memory replay,
synaptic downscaling, associative replay, and adaptation of the language
organ's voice, and says that sleep ends with the affective reset. The code
differs in three ways that #460 left for this change.

1. Phase order. Phase 2 downscales before it replays, and the voice
   alignment phase runs after the affective reset, so sleep does not end with
   the reset.
2. Replay window race. The episodic memory module opens its replay window only when its 50 ms
   peer poll sees `hypnos.sleep.started` on the bus. When phase 1 finishes
   inside that interval (an empty short-term buffer is enough), phase 2's
   `replay_now()` raises `ReplayWindowError`, phase 2 is recorded as failed,
   and the sleep summary goes out at alert intensity. The same bus-driven open
   also leaves the window open while awake if the poll sees a late
   `hypnos.sleep.started` after the sleep has ended.
3. Cross-period traces. `select_cross_period_traces()` reads the short-term
   buffer and the episodic collection only through the in-memory backend's
   private `_collections`. On the Qdrant and sqlite-vec backends it sees only
   the short-term buffer, which phase 1 has just emptied, so phase 3
   (associative replay, off by default) has nothing to combine.

## What Changes

- Phase 2 runs the replay first and the synaptic downscaling after it. Replay
  ranks candidates by affect intensity and recency and never reads vectors,
  and downscaling changes only the vectors, so the same traces replay in
  either order. The change brings the order into line with the paper.
- Voice alignment, with its intent-log rotation and voice measures, runs
  before the affective reset, and the affective reset is the last phase of
  every sleep. `hypnos.sleep.completed`, which resets the interoception module's fatigue, still
  follows it. The phase list in the completion summary becomes
  `light_consolidation`, `deep_consolidation`, `associative_replay`,
  `voice_alignment`, `affective_reset`. With voice training on, the affect module now
  resets after the training pass, so affect that moves during a long pass is
  not carried into waking.
  Phases 1 to 4 and their bookkeeping run inside a `try` whose `finally`
  runs the affective reset once, as its own task awaited through
  `asyncio.shield`, so an exception or a cancel in any earlier phase still
  ends the sleep with the reset, and a second cancel cannot interrupt it. The
  CancelledError is re-raised, never swallowed. `_run_pipeline` publishes the
  aborted `hypnos.sleep.completed` on any exception, including a cancel
  (previously only on `Exception`), so the interoception module's `_in_hypnos` cannot wedge and
  the episodic memory module's sleep-end handling runs.
- The sleep module owns the replay window. The episodic memory module gains `open_replay_window()` and
  `close_replay_window()`. Phase 2 opens the window immediately before it calls
  `replay_now()` and closes it in a `finally` once replay is done, inside the
  sleep lock and with perception suspended for the whole sleep.
  `hypnos.sleep.started` no longer opens the window; `hypnos.sleep.completed`
  still closes it and drops the consolidated batch, as a backstop. The guard in
  `ReplayEngine.replay()` is unchanged, so a replay outside that bracket still
  raises `ReplayWindowError`.
- `select_cross_period_traces()` draws on the short-term buffer, the traces
  phase 1 consolidated (`EpisodicMemoryCore.last_consolidated`), and the persisted
  newest `[mnemos.replay].cross_period_candidates` (default 128, matching
  `short_term_capacity`) points of the episodic collection, read through a
  new `MemoryStorage.recent_points()` that returns id, text, payload and
  affect without vectors. In-memory and sqlite-vec skip the vectors and
  sqlite-vec orders and limits in SQL; Qdrant scrolls with
  `with_vectors=False` and keeps a bounded heap of the newest. Traces are de-duplicated by point id (Qdrant returns a
  hex id in canonical hyphenated form, so ids are compared as UUIDs where they
  parse as one). A storage error propagates, so phase 3 records a failure
  instead of combining from a partial pool.

## Capabilities

### Modified Capabilities

- `hypnos`: the fixed phase order matches the paper and ends with the
  affective reset.
- `hypnos-fatigue-phases`: phase 2 replays before it downscales, inside a
  window that the sleep module opens and closes; the fatigue reset follows the affective
  reset that ends sleep.
- `mnemos-replay`: the replay window is opened and closed by the sleep module through
  the episodic memory module's API around phase 2's replay call.
- `hypnos-consolidation`: cross-period selection draws on the consolidated
  batch and on persisted episodic memory on every backend.

## Impact

- `kaine/modules/sleep/phases.py`, `kaine/modules/sleep/module.py`,
  `kaine/modules/episodic_memory/module.py`, `kaine/modules/episodic_memory/storage.py`,
  `kaine/boot/factories/episodic_memory.py`, `config/kaine.toml`
  (`[mnemos.replay].cross_period_candidates`), `kaine/modules/episodic_memory/replay.py`
  (docstrings), tests, and the sleep module, episodic memory module and sleep pages of the book.
- Behaviour with the episodic memory module enabled: phase 2 no longer fails when phase 1 is
  quick. The base-thesis form has no episodic memory module, so there the change is the phase
  order only: voice alignment is gated off and takes no time, so the reset
  still comes at the end of a sleep that otherwise does no work.
- `enter_sleep()`'s perception suspension (a `try`/`finally` under the sleep
  lock) is unchanged.
