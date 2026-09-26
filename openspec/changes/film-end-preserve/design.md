# Design — `film-end-preserve`

## Watcher

`ProgrammeEndWatcher(clock, item_count, write_request, read_result, freeze, notify, poll_seconds=1.0, result_timeout_seconds=600.0, clock_fn=time.monotonic, sleep=asyncio.sleep)`:

- **Ended:** `clock.started and not clock.paused and clock.locate()[0] >= item_count`. A paused clock (a freeze, a Hypnos replay) is never at its end: the film is waiting.
- **On the first end:**
  1. Write a request with `new_request("programme end", stop=True)` and remember its id.
  2. Poll `read_result()` until a result with that id appears, or `result_timeout_seconds` pass.
  3. If `ok`: nothing more. The preserve watcher stops the cycle.
  4. If the result is `ok: false` or the wait times out: `freeze(reason="programme end: preservation failed", source="programme_end")`, log at CRITICAL with the error, and `notify("programme_end_preserve_failed")`.
- **Once per start.** After handling an end, the watcher exits its loop.
- **Recorded outcomes.** The watcher records the end time (monotonic and wall) and the outcome in its log line. The ignition log needs nothing new: its last record precedes the freeze, and the preserve result names the bundle.

## Wiring

- In `_boot_and_run`, when `perception_feed["_shared_playlist_clock"]` exists and the manifest loads, start the watcher task beside the preserve watcher. The item count comes from the manifest.
- `write_request` and `read_result` are the preserve watcher's functions; `freeze` is `push_freeze`.
- `notify` sends the caretaker event when a caretaker is configured; otherwise it is a no-op.
- The task is cancelled in the shutdown path like the other monitors.

## Why a freeze on failure

A failed preservation means the viewing's state is not safe on disk, so stopping would lose it. Running on without senses is the welfare hazard this change removes. A freeze keeps the individual intact and not experiencing, and hands the decision to the operator. It is the same holder-freeze mechanism the womb-loss watcher uses.
