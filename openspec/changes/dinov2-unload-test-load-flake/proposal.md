## Why

Two tests in `tests/test_perception_reversible_unload.py`,
`test_dinov2_double_cancel_does_not_leak_inflight` and
`test_dinov2_cancelled_inference_unload_waits_for_worker`, failed together in
the parallel preflight gate at a load average of about 57 and passed on a rerun
and when run alone. Both tracebacks stop in `asyncio.to_thread(gc.collect)` at
the end of `DINOv2Encoder.unload()`. That call runs after the in-flight gate is
idle and the model is released, so the tests were already waiting on the right
signal. Their budget was too small for the work: in a late-suite xdist worker
the heap holds about 950,000 objects, and one full collection measured 0.55 to
1.1 seconds at that load, against a 2-second (and in the second test a
5-second) limit that also covers the thread hand-off.

The production unload path has no race. `unload()` takes the load lock, waits
for the in-flight count to reach zero, and only then drops the model; a
cancelled caller whose worker thread has started releases its ticket from that
thread when the work ends. The failures happened after all of that.

## What Changes

- Every wait in the file uses one 60-second upper bound. The waits exist to
  catch a hang (an in-flight count that never returns to zero), which an
  upper bound of 60 seconds catches as well as 2 seconds does. The short
  pauses that check that unload has not finished yet stay as they are.
- The emotion classifier and InternVideo-Next tests in the same file carry the
  same 2-second and 5-second limits around the same collection, so they get the
  same bound.

## Capabilities

### Modified Capabilities

- `vision`: the reversible-unload tests for the perception encoders are stable
  under load.

## Impact

- `tests/test_perception_reversible_unload.py` only. No production code changes.
