# The diagnostics page renders while no cycle is running

## Why
With controls enabled (not read-only) and no cycle running, `GET /diagnostics/` answered 500. The metrics snapshot for a stopped cycle carries only `cycle_status` and a hint. The rate-control form tested `metrics.experiential_rate_effective_hz is not none`, which an undefined value passes, then formatted it and raised. The read-only study view hid the form, so this went unseen until Nexus returned to its normal view.

Research impact: none (observation surface).

## What changes
- The form tests that the value is defined before testing it against none.
- A test renders the page with controls on and no cycle running.
