## Why

The sleep module sets `_fatigue_triggered_sleep` when the first fatigue sleep starts and never clears it. From then on every sleep summary reports `fatigue_triggered: true`, whatever started the sleep. A maintenance request, an emotion-regulation request, a developmental rest, an accepted rest request and the backstop all read as fatigue sleeps, so no record can tell a fatigue sleep from the backstop. The flag is also set for both maintenance requests, because they share the fatigue path. The paper (section 3.5) names what starts a sleep: fatigue crossing its threshold, the interoception module requesting maintenance, emotion regulation's tier 3 through the maintenance path, one entity hour awake as a backstop, and in the developmental phase a spent stimulus. The code adds a rest request from action selection.

## What Changes

- Each sleep records the trigger that started it, passed from the start site to the pipeline instead of kept in a module flag. The values are `fatigue`, `maintenance_request` (interoception), `affect_regulation` (tier 3), `developmental_rest`, `requested` (an accepted rest request) and `backstop` (the maintenance poll). A direct `enter_sleep()` call without a trigger records null.
- `sleep.sleep.started`, `sleep.sleep.completed` and the aborted `sleep.sleep.completed` carry `trigger` on every sleep. `fatigue_triggered` stays in the summary and is true only when that sleep's trigger is `fatigue`.
- The research log keeps `trigger` on `sleep.sleep.started` and `sleep.sleep.completed`.
- The faithful narration of a completed sleep names its trigger.
- Nothing about when a sleep starts, what it does or how long it lasts changes.

## Capabilities

### Modified Capabilities

- `hypnos-fatigue-phases`: every sleep records its own trigger.

## Impact

- `kaine/modules/sleep/module.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/faithful/templates.py`, `docs/09-modules/sleep.md`, `docs/10-sleep/README.md`, `docs/17-research-data/event-streams.md`, tests.
- Behaviour: none for the entity. The records now say which trigger started each sleep.
