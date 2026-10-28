## Why

The dashboard sleep harness case "asleep shows time so far" sets `started_at` to the real `Date.now()` minus 60 s and accepts only "1 min 0 s so far" or "1 min 1 s so far". A slow runner produced "1 min 2 s so far" and knocked #606 out of the merge queue (run 40721577566).

## What Changes

- The sandbox the harness runs `dashboard_sleep.js` in gets a `Date` whose `now()` returns a fixed time, and the case builds `started_at` from the same constant. The expected text is exactly "1 min 0 s so far".
- It is the only test under `tests/js` that reads the clock (searched for `Date.now` and `new Date`).

## Impact

- `tests/js/dashboard_sleep_harness.js` only. No dashboard code changes.
