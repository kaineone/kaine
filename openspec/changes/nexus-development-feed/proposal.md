## Why

The dashboard's development panel and perception-feed panel lag behind what the developmental phase now publishes.

- The hearing band's stage reaches only `development.out` and the log. The dashboard does not read that stream, and the stream also carries a stimulus-presence event every second, so the newest stage event can lie tens of thousands of entries back. An operator cannot see which band the entity hears.
- The maturation gate's status carries `world`, `conditions` and the readiness's `not_applicable` markers, but the dashboard keeps a fixed key list without the first two, never shows a not-applicable marker, and always prints "consolidation passes" even when consolidation is not required.
- In stimulus-source mode the perception-feed panel shows only the mode chip, without the heartbeat, the colour ramp, the maternal voice or the hearing band.
- The module grid's "capturing" flag reads the live camera and microphone state only, so the vision and audition modules read as not capturing under every seeded, playlist, screen or stimulus-source feed.

## What Changes

- `HearingStageWatch` keeps its newest reading (`current`), and the cycle writes it into `state/cycle/runtime.json` as `hearing_stage` on every runtime write. The published event, the stage clock, the filter and the audio are unchanged.
- `/diagnostics/maturation.json` returns that reading as `hearing`, and keeps the gate's `world` and `conditions`. The development panel shows the hearing stage and its band, the world, each not-applicable condition, and consolidation passes only when consolidation is required (otherwise it says it is not required).
- The perception-feed block gains a content-free `stimulus_source` summary in stimulus-source mode: base heartbeat rate and drift, the colour ramp's time constant and hue gain, whether the maternal voice is on, and the hearing band's span and whether it is on. The panel shows them, and shows the current hearing stage from the same reading.
- The module grid marks the vision and audition modules capturing when the running cycle has them and the configured feed is seeded, playlist, screen or stimulus-source, or when the live sensor is active, and names the feed.

## Capabilities

### Modified Capabilities

- `developmental-stimulus`: the cycle's runtime file carries the hearing band's current stage.
- `dashboard-observability`: the development panel, the perception-feed panel and the module grid show the developmental feed and the gate's conditions.

## Impact

- `kaine/cycle/hearing_stage_watch.py`, `kaine/cycle/__main__.py` (`_start_stimulus_source_presence`, `_write_runtime_state` and its call), `kaine/cycle/boot_context.py`, `kaine/dashboard/maturation.py`, `kaine/dashboard/health/blocks.py` (`perception_feed_block`, `module_states`), `kaine/dashboard/health/prober.py`, `kaine/dashboard/templates/_development_panel.html`, `_perception_feed.html`, `_health_board.html`, `kaine/dashboard/static/dashboard_maturation.js`, `kaine/dashboard/static/dashboard.js` (module grid), `docs/05-dashboard.md`, `docs/06-operation/development.md`.
- Privacy: every new field is a number, a boolean, a stage index or a fixed label. No frame, sample, utterance or prompt content.
