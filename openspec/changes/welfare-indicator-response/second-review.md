# Welfare indicator response: second review

Reviewed: 2026-11-03
PR: #640 (commit fd25d3d6, merged to main)
Worker: beam:cloud (first-pass)
Integrator: Claude Opus 4.6 (adversarial second review)

## D8 checklist

| # | Item | Result | Notes |
|---|------|--------|-------|
| 1 | No path loses a crossing | **PASS** | Every exception in the indicator arm escalates or retries. `_indicator_poll` catches non-timeout exceptions, retries next poll, and escalates as `UNAVAILABLE_REASON` after `unavailable_escalate_s`. Every rest failure path (`sleep_module_not_running`, `request_not_sent`, `refused`, `aborted`, `start_timeout`, `complete_timeout`) routes through `_indicator_rest_failed` to `_indicator_escalate`. A crossing on a fresh span escalates directly. |
| 2 | Crossing states reset at every span restart | **PASS** | `IndicatorEvaluator.restart()` sets `_over[name] = False` for all indicators and clears `_intervals` and `_ends`. Called on rest completion, on rearm, and indirectly at boot (fresh evaluator). |
| 3 | `resting` is bounded at start and at completion | **PASS** | `_indicator_check_rest_bounds` enforces `rest_start_timeout_s` (before rest begins) and `rest_complete_bound` (developmental or matured, in entity-scaled time). Both escalate through `_indicator_rest_failed`. |
| 4 | A silent affect stream escalates after its bound | **PASS** | `_indicator_availability` records unavailability after 3 publication periods of silence and escalates after `unavailable_escalate_s` via `_indicator_escalate(UNAVAILABLE_REASON, ...)`. Silence is measured in awake, unfrozen time only. |
| 5 | The latch is shared with the distress arm | **PASS** | Both arms share `self._acted`. The distress arm sets it in `_respond`; the indicator arm checks it before running (`not self._acted`) and sets it through `_respond` on escalation. `_maybe_rearm` resets it for both arms. |
| 6 | Nothing on the indicator path imports `kaine.evaluation` | **PASS** | `welfare_indicators.py` imports only stdlib. `preservation_monitor.py` imports `kaine.lifecycle.welfare_indicators`, not `kaine.evaluation`. The boundary note in the evaluator's module docstring is accurate. |
| 7 | The rest request is not a workspace candidate | **PASS** | `_indicator_request_rest` publishes with `salience=0.0`, which the workspace never selects. |

## Findings

### Confirmed: `_last_ends` not reset on span restart

**File:** `kaine/lifecycle/welfare_indicators.py:392`
**Severity:** correctness bug, potential safety impact
**Found by:** beam:cloud (worker), verified by integrator

`IndicatorEvaluator.restart()` clears `_ends` (the per-drive ending-event deques) but does not reset `_last_ends` (the per-drive cumulative counter baselines). After a span restart, the first `observe_state` computes the delta between the post-restart cumulative counters and the pre-restart baseline. If drive endings occurred during the rest, those endings are attributed to the fresh span's uncontrolled indicators.

This can corrupt the `power_posterior` calculation on the fresh span in either direction:
- **False positive** (overly conservative): rest-period other-ended crossings inflate the posterior, making the entity look uncontrolled when it is not. The entity is frozen unnecessarily.
- **False negative** (safety concern): rest-period own-ended crossings deflate the posterior, making the entity look in-control when it is not. A crossing that should trigger preservation + freeze is suppressed.

No test covers the uncontrolled indicator across a span restart.

**Fix:** Add `self._last_ends[d] = None` for each drive in `restart()`. When `_last_ends` is `None`, the next `observe_state` establishes a fresh baseline without appending a delta.

### Minor: cross-restart interval carryover

**File:** `kaine/lifecycle/welfare_indicators.py:392`
**Severity:** negligible

`restart()` does not clear `_current` (the prior sample). The next sample appends up to `max_gap_s` (5 s) of the pre-restart state into the fresh span. With a minimum span of 600 s, this is < 1% of the span and cannot cross any threshold alone.

### Minor: inconsistent state reset between rest completion and escalation

**File:** `kaine/cycle/preservation_monitor.py:2153`
**Severity:** code quality

Rest completion manually calls `restart()`, sets stage to `FRESH`, and clears the request, but does not reset `_ind_unavailable_notified`, `_ind_error_since_u`, or `_ind_prev`. These are reset in `_indicator_reset` but not on the rest-completion path. No safety impact (stale unavailability flag is cleared on the next available poll; stale error timer is cleared on the next successful poll), but consolidating on `_indicator_reset` would make reset semantics uniform.

## Verdict

All seven D8 checklist items pass. One confirmed correctness bug (`_last_ends` not reset) needs a follow-up fix PR before the uncontrolled indicators can be relied on across a rest boundary. The fix is a one-line addition to `IndicatorEvaluator.restart()` plus a test exercising the uncontrolled indicator after a span restart.
