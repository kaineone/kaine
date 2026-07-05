# Publish gray-zone welfare events to the bus and act on all four categories

## Why

The sidecar welfare observer detects four §5.5 gray-zone conditions —
`replay_overload`, `unmaintained_fatigue`, `sustained_extreme_vad`, and
`sustained_interoceptive_distress` — but today it writes them ONLY to its JSONL
sink. The autonomous welfare-protective monitor (cycle-layer, no human in the
loop) therefore acts on just ONE of the four: its "repeated gray-zone" arm reads
sustained interoceptive distress straight off `soma.out` and never sees the other
three. That gap was logged as an honest limitation at merge.

The fix is to PUBLISH the detected gray-zone events to the bus so the protective
monitor — and the curated research log and the raw archive — can all observe ALL
four categories through one signal.

A privacy pre-check confirms the four gray-zone payloads are content-free
(numeric scalars/counters plus the `gray_zone_event` enum label). Publishing is
therefore safe, but the change ENFORCES it: the published payload contains only
numeric fields plus the label, and no field is ever copied from a source event
payload.

## What Changes

1. **The welfare observer publishes.** `WelfareObserver` gains a content-free
   bus-publish path. On each gray-zone detection it publishes a `welfare.gray_zone`
   event (source `welfare` → stream `welfare.out`) IN ADDITION to the existing
   sink write. The published payload is the same content-free dict written to the
   sink. The observer is no longer strictly read-only — it now emits derived,
   content-free welfare signals.
2. **The protective response covers all four categories.** The cycle-layer
   `WelfareProtectiveMonitor` subscribes to `welfare.out` `welfare.gray_zone`
   events and feeds each (any of the four categories) into its windowed-repeat
   arm. The existing sustained-distress arm (read off `soma.out`) is kept. The
   coupling is bus-only — no `kaine.evaluation` import, preserving the sidecar
   boundary.
3. **The research log and raw archive capture them.** The curated research event
   log follows `welfare.out` and records `welfare.gray_zone` events through an
   EXACT numeric-field allowlist (tightened from suffix-matching so a future field
   cannot smuggle content). The local-only raw archive adds `welfare.out`.
4. **Config.** The repeat arm reuses the existing `[preservation.welfare_response]`
   `repeat_window_s` / `repeat_threshold`; no new keys are required.

## Impact

- Affected specs: new capability `welfare-monitoring` (ADDED requirements).
- Affected code: `kaine/evaluation/observers/welfare_observer.py` (publish path),
  `kaine/cycle/preservation_monitor.py` (gray-zone repeat arm),
  `kaine/evaluation/observers/research_event_observer.py` (curated capture +
  exact allowlist), `kaine/evaluation/observers/raw_bus_archive_consumer.py`
  (raw capture), `config/kaine.toml` (comment-only).
- Sovereignty / privacy: the emitted signal is a derived, content-free welfare
  measure, not entity interior. The protective response is an external welfare
  safeguard, not a constraint on the entity's cognition.
