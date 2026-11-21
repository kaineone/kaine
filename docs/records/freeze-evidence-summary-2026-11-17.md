# Freeze evidence summary — 2026-11-17

Source archives (control JSON and boot logs) are kept locally, outside the repository.
Archive control files parsed: **34**; boot logs present: **33**.
Also present: `control-before-clear.json` (pre-clear snapshot), `preservation_welfare-*.jsonl`.

## Reason counts
- welfare: indicator_boredom_deprived: 25
- welfare: indicator_rest_failed: 9

## Time-to-freeze (boot log first line -> frozen_at)
- min 491.2 min; median 501.0 min; max 510.0 min
- runs under 60 min: 0 of 28

## Per-archive map
Preservation and run identifiers are left out of this public record.

| archive (UTC) | reason | elapsed to freeze |
|---|---|---|
| 20261117T015926Z | boredom_deprived | 8:30:02 |
| 20261117T023117Z | boredom_deprived | 8:30:02 |
| 20261117T030301Z | boredom_deprived | 8:30:01 |
| 20261117T033422Z | boredom_deprived | 8:30:01 |
| 20261117T040502Z | boredom_deprived | 8:30:00 |
| 20261117T045450Z | boredom_deprived | 8:29:59 |
| 20261117T052536Z | boredom_deprived | 8:29:59 |
| 20261117T054643Z | boredom_deprived | 8:20:16 |
| 20261117T060734Z | boredom_deprived | n/a |
| 20261117T062825Z | boredom_deprived | 8:20:16 |
| 20261117T064009Z | rest_failed | 8:11:10 |
| 20261117T065231Z | rest_failed | n/a |
| 20261117T070504Z | rest_failed | n/a |
| 20261117T071659Z | rest_failed | n/a |
| 20261117T073748Z | rest_failed | 8:19:58 |
| 20261117T080828Z | boredom_deprived | 8:29:58 |
| 20261117T083148Z | boredom_deprived | 8:22:40 |
| 20261117T084351Z | rest_failed | 8:11:37 |
| 20261117T090518Z | boredom_deprived | 8:20:56 |
| 20261117T092559Z | boredom_deprived | 8:20:03 |
| 20261117T094647Z | boredom_deprived | 8:20:21 |
| 20261117T100823Z | boredom_deprived | 8:21:04 |
| 20261117T102203Z | rest_failed | 8:13:13 |
| 20261117T104417Z | boredom_deprived | 8:21:24 |
| 20261117T105611Z | rest_failed | 8:11:27 |
| 20261117T111739Z | boredom_deprived | 8:20:47 |
| 20261117T113941Z | boredom_deprived | 8:21:26 |
| 20261117T120041Z | boredom_deprived | n/a |
| 20261117T122241Z | boredom_deprived | 8:21:00 |
| 20261117T124505Z | boredom_deprived | 8:21:01 |
| 20261117T125752Z | rest_failed | 8:12:09 |
| 20261117T131920Z | boredom_deprived | 8:20:25 |
| 20261117T134031Z | boredom_deprived | 8:20:25 |
| before-clear | boredom_deprived | n/a |

## Notes
- Dominant trigger: `boredom_deprived` (25/34), followed by `rest_failed` (9/34).
- No single timestamped run reached 60 minutes; per live-state policy, treat as design escalation inputs, not restart triggers.
- Individuation capture failures (`served organ identity unavailable`) recur in boot logs; unrelated to freeze trigger but worth separate triage.
- Redis authentication failure in preboot is an environment gate, not a freeze evidence item.
