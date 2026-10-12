## Why

The reviews of #470 left three follow-ups that this change closes.

1. The world model module's scenario window. The world model module opens its window when its 50 ms
   peer poll sees `hypnos.sleep.started`, the race #470 removed from the episodic memory module.
   The poll reads `mnemos.out` before `hypnos.out`, so when phase 1 is quick
   the `mnemos.replay` cues of phase 2 and the sleep start arrive in the same
   poll, the cues are handled first against a closed window, and no scenario
   is imagined from them.
2. The sleep module's shutdown. The sleep module has no `shutdown` of its own. A sleep task in
   flight at shutdown is never cancelled, and the tasks the sleep module holds in
   `_shielded_tasks` (the final affective reset and the aborted-completion
   publish) are never awaited. The event loop then destroys them pending, or
   cancels the sleep after the bus has closed, so neither the reset nor the
   aborted `hypnos.sleep.completed` is sure to happen.
3. NaN timestamps. `_payload_timestamp` returns a NaN or infinite payload
   timestamp as is. NaN makes the in-memory heap order undefined, and
   SQLite reads NaN as NULL (ranked 0.0) but infinity as a real infinity, so
   `recent_points` ranks such points differently on each backend.

A fourth follow-up, synaptic downscaling on the Qdrant and sqlite-vec
backends, is left out: every backend ranks by cosine similarity and Qdrant
normalizes cosine vectors on upload, so scaling the stored vectors would
change nothing that recall or replay reads. The paper does not say what the
downscaled quantity is, so that question goes to the operator.

## What Changes

- The world model module gains `open_scenario_window()` and `close_scenario_window()`.
  The sleep module opens the window before phase 2, whose replay cues the world model module through
  `mnemos.replay`, and closes it in a `finally` after phase 3, which cues it
  directly. `hypnos.sleep.started` no longer opens the window; it still pauses
  the waking path for the whole sleep and starts the training pass.
  `hypnos.sleep.completed` still closes the window, as a backstop.
- The world model module answers a replay cue while the window is open, and also a cue
  handled after the window closed whose timestamp lies inside the latest
  window, so the poll interval cannot drop cues that phase 2 published.
  While a window is open, a cue stamped before it opened is ignored, and the
  last four closed windows are kept, so a late cue from the first of two
  back-to-back sleeps is still answered. `initialize()` clears the sleep state
  and the window, so a light restart that misses `hypnos.sleep.completed`
  cannot leave the waking path off.
- The sleep module gains `shutdown()`. It stops the background loops, cancels a sleep
  still in flight and waits for it, so the sleep ends with the affective reset
  and the aborted completion, then waits for the held shielded tasks. Each
  wait is bounded; a task still pending after it is logged.
  The cycle's shutdown and the supervisor's halt shut the sleep module down first (new
  `shutdown_order()` in `kaine/modules/registry.py`), so the sleep ends while
  The episodic memory, affect and world model modules are still up. Only the sleep module moves; the other
  modules keep their registration order.
- `_payload_timestamp` returns 0.0 for a NaN or infinite timestamp, and the
  sqlite-vec `recent_points` query maps a NULL or infinite timestamp to 0.0,
  so every backend ranks such a point as the oldest.

## Capabilities

### Modified Capabilities

- `phantasia`: the scenario window is opened and closed by the sleep module, and cues
  published inside it are answered even when handled after it closes.
- `hypnos`: the sleep module opens the world model module's window around phases 2 and 3, and its
  shutdown settles an in-flight sleep and its held tasks.
- `mnemos`: `recent_points` ranks a non-finite timestamp as 0.0 on every
  backend.

## Impact

- `kaine/modules/phantasia/module.py`, `kaine/modules/hypnos/module.py`,
  `kaine/modules/mnemos/storage.py`, `kaine/modules/registry.py`,
  `kaine/cycle/__main__.py`, `kaine/cycle/spot.py`, tests, and the world model module, the sleep module and
  sleep pages of the book.
- Base-thesis form: no world model module and no episodic memory module, so the change there is the
  shutdown path only.
