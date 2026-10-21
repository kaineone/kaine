## Why

The console's title always reads "KAINE". `ConversationState` has `update_from_self_model` and `update_from_sleep`, but nothing outside the tests calls them: the dashboard never reads the self-model's `self_model.document` events or the sleep module's lifecycle events into it, and it never reads the name the self-model module persists. The left-rail status chip has the same gap at page load: it learns that the entity sleeps only from a sleep event that arrives while the page is open, so a page opened during a sleep reads "awake" until the entity wakes.

## What Changes

- The bus bridge accepts observers. Each observer sees every event read from a tailed stream, before the privacy filter and whether or not a browser is connected. An observer that raises is logged and the bridge carries on.
- `ConversationState.observe` takes the name from `self_model.document` events (the `name` field only) and the sleep state from `sleep.sleep.started` and `sleep.sleep.completed`.
- At start the dashboard reads the name from the self-model file (`[self_model].persistence_path`, by default `state/self_model/self_model.json`) through the self-model document loader, so an encrypted file decrypts. When that file holds no name it reads an optional `name` field from the identity file (`state/identity/entity.json`). With neither it keeps "KAINE". A missing, unreadable or undecryptable file is logged at debug level and changes nothing.
- When the app starts, it reads the newest `self_model.document` on `self_model.out` and the newest `sleep.sleep.started` or `sleep.sleep.completed` among the last 500 entries of `sleep.out`, through a new `AsyncBus.recent`, within a 5 s bound. A bus error leaves the state as it was.
- The console shows the name in the page title and under the wordmark in the left rail. The status chip carries the server's sleep state in a `data-sleeping` attribute, and the chip script starts from it.

## Capabilities

### Modified Capabilities

- `dashboard-observability`: the console shows the entity's name and starts the status chip from the server's sleep state.

## Impact

- `kaine/bus/client.py` (`AsyncBus.recent`), `kaine/dashboard/bridge.py`, `kaine/dashboard/conversation.py`, `kaine/dashboard/app.py`, `kaine/dashboard/__main__.py`, `kaine/dashboard/templates/console.html`, `kaine/dashboard/static/dashboard.js`, `docs/05-dashboard.md`.
- New tests: `tests/test_dashboard_entity_name.py`, `tests/test_dashboard_status_chip_js.py` with `tests/js/dashboard_status_chip_harness.js`.
- Privacy: the observer reads only the name and the event type. The SSE stream to the browser is unchanged and still passes through the privacy filter.
