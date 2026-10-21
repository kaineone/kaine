## Why

The welfare panel predates the affect welfare record, and the dashboard cannot tell one sleep from another.

- The welfare observer writes an `affect_welfare` record to its JSONL log every 300 s of unfrozen time (paper 6.2, A.4): the negative-valence share, and per deficit the share of crossings ended without the entity's own response, that count per awake hour, the deprivation share, the crossings ended by the sleep reset and whether a crossing is open, and curiosity's interest share. The entity-care panel shows only the gray-zone counters and sensor advisories.
- A developmental rest (paper 3.5: a spent stimulus brings a 21-minute rest) shows as an ordinary sleep. The sleep module states its trigger (`developmental_rest` or `requested` on `sleep.sleep.started`, `trigger`, `rest_seconds` and `fatigue_triggered` on `sleep.sleep.completed`), and the affect module publishes `affect.rest_request` when the stimulus is spent, but the dashboard shows none of it.

## What Changes

- `kaine/experiment/welfare_counts.py` gains `affect_welfare_from_jsonl`: the newest `affect_welfare` record in the welfare rollup, reduced to its numeric measures and its timestamp, with a flag saying whether it was written since the observer's latest start. The health snapshot's `welfare` block carries it as `affect_welfare`, and a new panel in the welfare board shows it per drive.
- `ConversationState` follows the sleep lifecycle and the rest requests: the current or last sleep's trigger, its start, its duration, the developmental rest's length and whether it was aborted, and the last `affect.rest_request` (reason, drive, stall length, time). The trigger is the one the sleep module states (`developmental_rest`, `requested`). For a sleep that states none and whose start the dashboard saw, it is `backstop` (the one-hour interval) while no fatigue sleep has happened since boot, and `fatigue_or_backstop` after one: the sleep module sets `fatigue_triggered` at the first fatigue sleep and never clears it, so the flag cannot tell the two apart. When the app starts it reads the newest of these from the last 2000 entries of `sleep.out` and `affect.out`.
- `GET /diagnostics/sleep.json` returns that view, and a sleep-and-rest panel in the welfare board polls it every 5 s.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: the welfare board shows the affect welfare record and the sleep trigger, rest length and rest requests.

## Impact

- `kaine/experiment/welfare_counts.py`, `kaine/dashboard/health/blocks.py` (`welfare_block`), `kaine/dashboard/conversation.py`, `kaine/dashboard/app.py`, new `kaine/dashboard/static/dashboard_sleep.js`, new `kaine/dashboard/templates/_affect_welfare.html` and `_sleep_panel.html`, `_diagnostics_sections.html`, `_base.html`, `docs/05-dashboard.md`.
- Builds on `nexus-entity-name` (the bridge observer and the start-up backfill).
- Privacy: numbers, booleans, timestamps and fixed labels only. Labels from the bus are kept only when they are short lower-case identifiers.
