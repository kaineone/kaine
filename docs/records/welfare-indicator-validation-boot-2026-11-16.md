# Welfare-indicator validation boot — 2026-11-16

Source log: `/tmp/kaine-validation-boot.log`
Cycle command: `timeout 90 .venv/bin/python -m kaine.cycle` (supervised, exit code 124 = timeout as intended).
Environment: `KAINE_STATE_KEY=$(cat secrets/state_key)`, `KAINE_CYCLE_OPERATOR_PRESENT=1`.

## Log stats

- Lines: 87
- Bytes: 10058
- First timestamp: 2026-11-16 14:30:24,589
- Last timestamp: 2026-11-16 14:31:54,250
- Elapsed span: ~89.7 s (full 90 s budget consumed; terminated by timeout).

## Relevant log lines (sleep / welfare / preservation / boredom / time)

```
2026-11-16 14:30:29,020 INFO kaine.boot.perception_feed: stimulus source: hearing band on (stages advance on saturation, 5400 to 25200 s of awake time each)
2026-11-16 14:30:29,688 WARNING kaine.modules.sleep.housekeeping: study sink research_event_log.external_utterances.log_dir under state/ is watched but never reclaimed
2026-11-16 14:30:29,688 WARNING kaine.modules.sleep.housekeeping: study sink research_event_log.raw_archive.archive_dir under state/ is watched but never reclaimed
2026-11-16 14:30:29,689 WARNING kaine.boot.factories.sleep: sleep housekeeping: no archive volume is mounted at /app/archive, so study records stay on the host; at the current growth of unknown a day the disk budget of 930.21 GiB is reached in an unknown time (bind a drive at /app/archive to export them; docs/09-modules/sleep.md, Housekeeping)
2026-11-16 14:30:29,689 INFO kaine.boot.registry: registered module sleep
2026-11-16 14:30:29,689 INFO kaine.boot.metrics:   device assignment: sleep.voice_alignment → cuda:0
2026-11-16 14:30:29,689 INFO kaine.boot.metrics:   device assignment: sleep.voice_alignment.hot_swap → manual
2026-11-16 14:30:29,689 INFO kaine.boot.wiring: wired sleep development probe
2026-11-16 14:30:31,946 INFO kaine.boot.wiring: wired sleep development probe
2026-11-16 14:30:31,964 WARNING kaine.cycle: entity is frozen at boot (source=welfare); it will stay frozen until a human releases it with an explicit override
2026-11-16 14:30:31,966 WARNING kaine.modules.sleep.housekeeping: study sink research_event_log.external_utterances.log_dir under state/ is watched but never reclaimed
2026-11-16 14:30:31,966 WARNING kaine.modules.sleep.housekeeping: study sink research_event_log.raw_archive.archive_dir under state/ is watched but never reclaimed
2026-11-16 14:30:31,970 WARNING kaine.cycle.preservation_monitor: welfare monitor: a welfare freeze stands from before this start
```

## Sleep-completion assessment

No maintenance sleep start/complete event was emitted during the run (grep for "maintenance sleep" / "sleep started" / "sleep complete" / "duration" returned empty). The cycle booted, registered the sleep module, but the entity entered the run already welfare-frozen from a prior state ("entity is frozen at boot (source=welfare)"), so maintenance sleeps were not initiated within the 90 s window. Consequently this boot did **not** complete a sleep long enough to measure the matured completion bound (configured `rest_complete_timeout_s.matured = 3600.0` s); the run measured startup timing only. A fresh, unfrozen boot (after releasing the welfare freeze) is required to capture maintenance-sleep durations.
EOF